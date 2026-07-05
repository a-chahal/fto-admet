# pbpk - whole-body PBPK integrator (OUT-OF-BAND: R 4.x + .NET 8 + OSP binaries)

PBPK (Open Systems Pharmacology / **PK-Sim** + **MoBi**) is the pipeline's concentration-time **integrator**.
It is **not a per-molecule SMILES->number predictor** (IO_SPEC §1 #12, Provenance §B#13): a PK-Sim model is
parameterized with **other endpoints' outputs** (clearance, fraction unbound, permeability, logP, pKa) and
simulated with the **`ospsuite` R package** to produce a whole-body C(t) profile, from which the modeler
extracts exposure metrics (Cmax, AUC, tmax, ...). It runs **after** the endpoints that feed it, so it is
**shortlist only**, out of the automated bulk loop.

In the registry: `endpoints = {clearance}`, **`env_manifest = None`**, **`entrypoint = None`**,
**`in_bulk_loop = False`**, `requires_gpu = False`. `core.dispatch` never drives it (it refuses
`env_manifest is None`); its results are **transcribed to the ledger by hand**, exactly like a web-only SOP
tool, via the thin `run.py` helper below.

## Why this model is OUT-OF-BAND (no pixi env)

PBPK / OSP is the **heaviest non-Python dependency in the pipeline** and the one endpoint that breaks the
"Python everywhere" model. Its runtime is **R 4.x + .NET 8 + a Visual C++ redistributable + the OSP Suite
(PK-Sim/MoBi) binaries**, driven through the **`ospsuite` R package** (a Python interface is comparatively
immature; R is the supported scripting path). None of that belongs in a pixi env (CLAUDE.md §4: non-Python
heavy runtimes isolate OUTSIDE pixi), so PBPK is installed and run out-of-band on the box, and its metrics
are transcribed to the ledger.

The **code deliverable is `run.py` as a thin transcription helper** (plus the `pbpk.R` scaffold), **not an
env**. `run.py` runs no simulation: it turns a small JSON of metrics a modeler already extracted from an
`ospsuite` run into `core.schemas.OutputRecord`-shaped JSON. It is pure stdlib (`json` + `argparse`): no pixi
env, no third-party imports, does not import `core`.

## Install recipe (out-of-band; do this ONCE on the box, outside pixi)

Nothing here goes through pixi. Install under `/zfs` (CLAUDE.md §0 storage discipline), never `$HOME`.

1. **R 4.x.** Install R 4.x for Linux (e.g. from CRAN's Ubuntu repo or a `/zfs`-local build). Point R's
   user library under `/zfs` (`R_LIBS_USER=/zfs/sanjanp/fto-admet-envs/pbpk/rlibs`) so packages do not land
   in `$HOME`.
2. **.NET 8 runtime + Visual C++ redistributable.** OSP's compute core is .NET. Install the .NET 8 runtime
   for Linux (Microsoft's package feed) and the matching native prerequisites.
3. **OSP Suite binaries (PK-Sim / MoBi).** Install from `setup.open-systems-pharmacology.org` (the Suite is
   GPLv2, free including commercial). These provide the simulation engine the `ospsuite` R package binds to.
4. **`ospsuite` R package.** **Not on CRAN** (it ships native binaries) - install from the OSP GitHub
   releases / archive, e.g. in R:
   ```r
   # install the companion packages first (rClr / ospsuite.utils), then ospsuite, from the OSP release assets
   install.packages("<path-or-url>/ospsuite_<ver>_R_x86_64-pc-linux-gnu.tar.gz", repos = NULL, type = "source")
   library(ospsuite)   # should load without error once .NET 8 + OSP binaries are present
   ```
5. **Sanity check:** `library(ospsuite); loadSimulation(<a .pkml>)` loads a model without a .NET error.

> The exact `ospsuite` version string, the `.pkml` model, and the resolved PK-Sim parameter paths are the
> residues that require the runtime physically installed. Until then this task is `needs_aaran`: the
> transcription helper + the SOP + the `pbpk.R` scaffold are complete and tested on the laptop; installing
> the R/.NET/OSP stack on the box is the remaining step. PBPK is a POINTER expected to trail the endpoints
> that feed it, so a missing install is `needs_aaran`, **not** blocked.

## Parameterization: which upstream endpoint output feeds which PK-Sim input

PBPK is an integrator, so its "input" is the collected output of the endpoints that ran before it. The
`pbpk.R` scaffold shows the call; the mapping is:

| PK-Sim compound input               | Fed from (upstream endpoint output)                         | Notes |
|-------------------------------------|-------------------------------------------------------------|-------|
| Lipophilicity                       | OPERA `LogP` (or `rdkit_crippen`)                           | log Kow |
| Fraction unbound (plasma)           | OCHEM PPB `fu = 1 - %bound/100` (or OPERA `FuB`)           | 0-1 |
| Specific intestinal permeability    | OPERA `Caco2` (logPapp) / a permeability endpoint          | absorption |
| Hepatic metabolic clearance (CLint) | OPERA `Clint`, or `admet_ai` `Clearance_*_AZ`, or PKSmart CL | **one** descriptor only |
| pKa (ionization)                    | single pKa source - **F-13 placeholder: OPERA `pKa_pred`** | DEFERRED source choice |
| Molecular weight / solubility       | `core` physchem / a solubility endpoint                     | dissolution |

**Clearance stays decomposed (F-3, CLAUDE.md §4):** never pool the clearance numbers numerically. OPERA
`Clint` (uL/min/10^6 cells), PKSmart CL (mL/min/kg), `admet_ai` `Clearance_*_AZ` and DruMAP CLint are in
different units/matrices. PK-Sim consumes **one** clearance descriptor for this compound in its own units;
convert explicitly with `ospsuite` unit tools (`toUnit` / `toBaseUnit`) - do not combine models' CL values.

**F-13 (single pKa source):** wire the one injectable pKa source (documented placeholder: OPERA `pKa_pred`);
the final choice is DEFERRED - do not decide it here. **F-16 (FTO di-cation standardization):** feed the
single canonical `core` input; PK-Sim does its own internal handling. Flag divergences, do not pick a
protonation state (both DEFERRED, CLAUDE.md §4a).

## Simulation invocation (via `ospsuite`)

See `pbpk.R` (commented scaffold, not turnkey). The shape is: `loadSimulation(<pkml>)` ->
`setParameterValues(...)` from the upstream outputs above -> `runSimulation(sim)` ->
`getOutputValues(result, ...)` for the plasma (and a brain/tissue) concentration path -> extract metrics ->
write a metrics JSON that `run.py` transcribes.

## Metrics transcribed to the ledger (NO fixed output schema)

There is **no standardized PBPK output column set** (IO_SPEC §1 #12): the "output" is whatever the modeler
extracts from C(t). Typical set for this program (a CNS FTO inhibitor, so brain exposure matters):

| Metric        | Typical unit | Meaning                                             |
|---------------|--------------|-----------------------------------------------------|
| `Cmax`        | uM (or ng/mL)| peak plasma concentration                           |
| `tmax`        | h            | time to peak                                        |
| `AUC_0_t`     | uM*h         | area under C(t) over the simulated window           |
| `AUC_0_inf`   | uM*h         | area extrapolated to infinity                       |
| `t_half`      | h            | terminal half-life                                  |
| `Vss`         | L/kg         | volume of distribution at steady state              |
| `CL`          | mL/min/kg    | model-derived total clearance (keep DECOMPOSED, F-3)|
| `Kp_uu_brain` | unitless     | unbound brain-to-plasma ratio (key for a CNS target)|

Units are **not** baked into `endpoint_values` - the modeler records the unit per metric in the input
(`{"value", "unit"}`), and the helper preserves it in `raw["units"]`. The metric NAMES are free-form.

## The transcription helper (`run.py`) - uniform CLI

```
python run.py --input <metrics.json> --output <record.json> [--gpu N]
```

- `--input` - the extracted-metrics JSON (one object, or an array for a shortlist batch). Each metric is a
  bare number or a `{"value", "unit"}` object; `parameterization` / `simulation` blocks are optional but
  recommended (they are cached in `raw` so the record is reconstructible).
- `--output` - where the `OutputRecord` JSON is written (object in -> object out; array in -> array out).
- `--gpu` - accepted and ignored (the OSP simulation is CPU).

Numeric metrics land in `endpoint_values`; their units, the upstream parameterization, and the simulation
metadata are cached verbatim in `raw` (raw-output caching, CLAUDE.md §4a - a PBPK result must be
reconstructible if a later OSP release changes behavior). The reserved `uncertainty` envelope is populated
**only** from a modeler-supplied `uncertainty` block (PBPK has no native per-prediction sigma; its
uncertainty is propagated from upstream parameter uncertainty + optional global-sensitivity analysis) - it
is left `null` otherwise (no fabricated sigma, CLAUDE.md §3).

Example input:

```json
{
  "mol_id": "FTO-43",
  "metrics": {"Cmax": {"value": 1.85, "unit": "uM"}, "AUC_0_inf": {"value": 12.4, "unit": "uM*h"},
              "Kp_uu_brain": 0.34},
  "parameterization": {"fraction_unbound": {"source_model": "ochem_ppb", "field": "fu", "value": 0.12}},
  "simulation": {"dose_mg": 100, "route": "iv", "species": "human", "ospsuite_version": "12.x"}
}
```

Example emitted record:

```json
{
  "model": "pbpk",
  "endpoint_values": {"Cmax": 1.85, "AUC_0_inf": 12.4, "Kp_uu_brain": 0.34},
  "uncertainty": null,
  "raw": {"molecule_id": "FTO-43", "kind": "pbpk_simulation_metrics",
          "units": {"Cmax": "uM", "AUC_0_inf": "uM*h"},
          "parameterization": {"fraction_unbound": {"source_model": "ochem_ppb", "field": "fu", "value": 0.12}},
          "simulation": {"dose_mg": 100, "route": "iv", "species": "human", "ospsuite_version": "12.x"},
          "metrics_raw": {"...": "..."}},
  "provenance": {"model": "pbpk", "runtime": "OUT-OF-BAND: R 4.x + .NET 8 + OSP Suite binaries; ...", "...": "..."}
}
```

## Provenance

- **Upstream:** github.com/Open-Systems-Pharmacology (OSP Suite, PK-Sim, MoBi, `ospsuite` R package).
- **Citation:** Lippert J, et al. *Open Systems Pharmacology community: an open access, open source, open
  science approach to modeling and simulation in pharmaceutical sciences.* CPT Pharmacometrics Syst
  Pharmacol 2019, 8:878-882. doi:10.1002/psp4.12473 (PMC6930856).
- **Access tag:** CODE-STANDALONE (out-of-band R + .NET + OSP binaries; not a pixi env).
- **License:** OSP Suite (PK-Sim / MoBi / `ospsuite`) is GPLv2, free including commercial use.
- **Quirks:** an INTEGRATOR, not a predictor (consumes other endpoints' outputs); R scripting path
  (`ospsuite`), not Python; `.pkml` model built once in the PK-Sim GUI; no fixed output schema (metrics are
  modeler-chosen); shortlist only, never in the bulk loop.

## Status: needs_aaran

The transcription helper is complete and green on the laptop (`tests/test_model_pbpk.py`, fast tier - no
OSP), the SOP install recipe + parameterization mapping are documented, and `pbpk.R` is a working scaffold.
The remaining step is installing the R 4.x + .NET 8 + OSP Suite runtime on the box (recipe above), building a
`.pkml` model, and capturing a real FTO-43 simulation. Until then this task is `needs_aaran`: PBPK is a
POINTER expected to trail the endpoints that feed it, not blocked.
