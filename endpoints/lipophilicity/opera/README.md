# opera - OPERA physchem/ADME QSAR consensus models (OUT-OF-BAND: MATLAB MCR + Java)

OPERA (NIEHS) is a suite of curated, externally-validated QSAR consensus models with a native
applicability domain and a per-prediction confidence index. For this pipeline it supplies **LogP, LogD,
pKa (acidic + basic), FuB, Clint, Caco2** - a multi-endpoint lens that cross-cuts three endpoints:

- **lipophilicity** (LogP / LogD are direct lenses),
- **clearance** (Clint cross-checks the metabolism / clearance stack),
- **ppb** (FuB, fraction unbound, cross-checks OCHEM PPB via `1 - FuB`),

and OPERA's LogD / pKa also standardize SFI / BBB Score / CNS MPO downstream (IO_SPEC §2). It is a
**cross-cutting** model in the registry: `endpoints = {lipophilicity, clearance, ppb}`.

## Why this model is OUT-OF-BAND (no pixi env)

OPERA is **compiled MATLAB**. It runs on the free **MATLAB Compiler Runtime (MCR)** plus a **Java** stack
(PaDEL / CDK for the 2D descriptors). Neither the MCR nor the JVM belongs in a pixi env (CLAUDE.md §4:
non-Python heavy runtimes isolate OUTSIDE pixi). So in the registry OPERA has `env_manifest = None` /
`entrypoint = None`, and `core.dispatch` **refuses** it (it never enters the bulk `pixi run` loop). It is
run out-of-band on the box and its predictions are **transcribed to the ledger by hand**, exactly like a
web-only SOP tool.

The **code deliverable is `run.py` as a PARSER / WRAPPER**, not an env. It turns an OPERA `preds.txt` into
`core.schemas.OutputRecord`-shaped JSON. It is pure stdlib (`csv` + `json` + `argparse`): no pixi env, no
third-party imports, does not import `core`.

## Install recipe (out-of-band; do this ONCE on the box, outside pixi)

Nothing here goes through pixi. Install under `/zfs` (CLAUDE.md §0 storage discipline), never `$HOME`.

1. **MATLAB Compiler Runtime (MCR).** OPERA's compiled binary targets a specific MCR version (the current
   release targets **R2019b, MCR v9.7** - confirm against the OPERA release you download; older 2.x used
   v9.1/v912). Download the matching Linux MCR from MathWorks and install unattended:
   ```
   # example - use the MCR version the OPERA release names in its README/installer
   cd /zfs/sanjanp/fto-admet-envs/opera
   unzip MATLAB_Runtime_R2019b_glnxa64.zip -d mcr_installer
   ./mcr_installer/install -mode silent -agreeToLicense yes -destinationFolder /zfs/sanjanp/fto-admet-envs/opera/mcr
   # the MCR_ROOT below is the versioned subdir it creates, e.g. .../mcr/v97
   ```
2. **Java.** OPERA shells out to PaDEL/CDK (Java). A system `java` (OpenJDK 8+) on the box is sufficient;
   the OPERA package bundles the PaDEL/CDK jars.
3. **OPERA itself.** Download the NIEHS/OPERA command-line release (github.com/NIEHS/OPERA, "Releases")
   and unpack it, e.g. to `/zfs/sanjanp/fto-admet-envs/opera/OPERA`. It contains `run_OPERA.sh` and the
   compiled `OPERA` binary.
4. **Point the adapter at both** via environment (or the CLI flags below):
   ```
   export OPERA_HOME=/zfs/sanjanp/fto-admet-envs/opera/OPERA   # dir holding run_OPERA.sh
   export MCR_ROOT=/zfs/sanjanp/fto-admet-envs/opera/mcr/v97   # versioned MCR dir
   ```

> The exact MCR version string and the `preds.txt` header of a real run are the only residues that require
> the runtime physically installed. Until then this task is `needs_aaran`: the parser is complete and
> tested against a format-faithful sample; the MCR install is the remaining step. Once installed, capture a
> real `preds.txt` and drop it in `fixtures/` to replace the synthetic sample, then flip the box smoke on.

## The out-of-band command

`run.py` (or you, by hand) invokes:

```
$OPERA_HOME/run_OPERA.sh  $MCR_ROOT  -s in.smi  -o preds.txt  -e LogP LogD pKa FuB Clint Caco2  -v 1
```

- `<MCR_path>` (first positional) - the MCR root, so the compiled binary finds its runtime libraries.
- `-s <file>` - structure input (`.smi` / `.sdf` / `.mol`). We feed a `.smi` of `SMILES<TAB>MoleculeID`.
  (`-d <file>` would instead feed pre-computed PaDEL descriptor CSV.)
- `-o <file>` - output predictions file (CSV/TXT). This is the `preds.txt` the parser reads.
- `-e <endpoints...>` - endpoints to compute (case-insensitive). `pKa` expands to acidic + basic outputs.
- `-v 1` - verbosity (0 silent, 1 minimal, 2 full: 2 adds nearest-neighbour / descriptor columns).

`run.py` in the box path builds this command for you (`build_opera_command`) and then parses the result;
in the offline path you pass an already-computed file with `--preds`.

## Uniform CLI

```
python run.py --input <in> --output <out.json> [--gpu N]            # box path: needs $OPERA_HOME/$MCR_ROOT
python run.py --input <in> --output <out.json> --preds <preds.txt>  # offline path: parse an existing file (no MCR)
```

- `--input` - InputRecord JSON (object or array) or a `.smi`. Used to build the OPERA `.smi` on the box path.
- `--preds` - parse an already-computed OPERA `preds.txt` (transcription path; what the unit test drives).
- `--opera-home` / `--mcr` - override `$OPERA_HOME` / `$MCR_ROOT`.
- `--endpoints` - override the default `LogP LogD pKa FuB Clint Caco2`.
- `--gpu` - accepted and ignored (OPERA is CPU + MCR).

## Output contract (VERIFIED column mapping)

OPERA writes a comma-delimited CSV: first column `MoleculeID`, then **four columns per endpoint X**
(IO_SPEC §1 #21, verified from `OPERA_Source_code/OPERA.m` + `output_options.txt`):

| Column          | Meaning                                                    | Maps to                     |
|-----------------|------------------------------------------------------------|-----------------------------|
| `<X>_pred`      | predicted value (endpoint units)                           | `endpoint_values[X]`        |
| `AD_<X>`        | applicability-domain flag, 0/1 (1 = inside domain)         | `uncertainty.ad_in_domain`  |
| `AD_index_<X>`  | continuous AD / similarity index, 0-1                      | `uncertainty.ad_index`      |
| `Conf_index_<X>`| confidence index, 0-1, **UP = more reliable**              | `uncertainty.conf_index`    |

`Conf_index` is a **DIRECT uncertainty** and is populated on every record, never discarded (CLAUDE.md §4).
There is **NO `_predRange` column** in the verified source version - the interval is carried by
`AD_index` / `Conf_index`, not a separate range column. The parser is nonetheless header-driven: if a
different OPERA build emits a `<X>_predRange` column it is preserved in `uncertainty.extra['pred_range']`
(never silently dropped), and verbose nearest-neighbour / descriptor columns land in `raw['extra_columns']`.

Because OPERA is genuinely multi-endpoint and each endpoint carries its own AD/confidence, `run.py` emits
**one OutputRecord per (molecule, endpoint)** - so each record's single `uncertainty` envelope maps
cleanly to that endpoint's `AD_ / AD_index_ / Conf_index_`.

### Endpoint units + direction (VERIFIED)

| Endpoint      | Units                        | Direction                    |
|---------------|------------------------------|------------------------------|
| `LogP`        | log Kow                      | UP = more lipophilic         |
| `LogD`        | log                          | UP = more lipophilic         |
| `pKa_a`       | acidic pKa                   | -                            |
| `pKa_b`       | basic pKa                    | -                            |
| `FuB`         | fraction unbound (0-1)       | consumed as `1 - FuB` for PPB|
| `Clint`       | uL/min/10^6 cells            | keep DECOMPOSED (F-3)        |
| `Caco2`       | logPapp                      | UP = more permeable          |

**Clint stays decomposed** (F-3, CLAUDE.md §4): never combine OPERA `Clint` (uL/min/10^6 cells) numerically
with PKSmart CL (mL/min/kg), ADMET-AI `Clearance_*_AZ`, or DruMAP CLint - different units/matrices. That
harmonization is the clearance aggregator's job.

Example record:

```json
{
  "model": "opera",
  "endpoint_values": {"LogP": 3.42},
  "uncertainty": {"ad_in_domain": true, "ad_index": 0.88, "conf_index": 0.79, "extra": {}},
  "raw": {"molecule_id": "FTO-43", "endpoint": "LogP", "units": "log Kow (UP = more lipophilic)",
          "pred_raw": "3.42", "header": "MoleculeID", "extra_columns": {}},
  "provenance": {"model": "opera", "runtime": "OUT-OF-BAND: MATLAB Compiler Runtime + Java (PaDEL/CDK)", ...}
}
```

## Raw-output caching (in scope now, CLAUDE.md §4a)

OPERA is transcribed by hand, so keep the raw `preds.txt` next to the ledger record on `/zfs` (the full
CSV, including any `_predRange` / neighbour columns) so a result is reconstructible if a later OPERA
release changes its output.

## F-16 / F-13 boundaries (DEFERRED - do not decide here)

- **F-16 input standardization** (the FTO di-cation): OPERA does its own internal QSAR-ready
  standardization on the SMILES it is fed. Feed it the single canonical `core` input; do not pre-pick a
  protonation state. Flag, do not decide.
- **F-13 single pKa source**: OPERA `pKa_pred` (`pKa_a` / `pKa_b`) is the documented placeholder pKa source
  for BBB Score / CNS MPO / SFI-cLogD, wired as a single injectable source. The final choice is DEFERRED.

## Provenance

- **Upstream:** github.com/NIEHS/OPERA (command-line + GUI release).
- **Citation:** Mansouri K, et al. *OPERA models for predicting physicochemical properties and
  environmental fate endpoints.* J Cheminform 2018, 10:10. doi:10.1186/s13321-018-0263-1.
- **Access tag:** CODE-STANDALONE (out-of-band MCR + Java; not a pixi env).
- **License:** OPERA source is MIT (NIEHS/OPERA); the MATLAB Compiler Runtime is redistributed free under
  the MathWorks MCR license.
- **Quirks:** compiled MATLAB (MCR-pinned version), Java descriptor backend, `pKa` expands to two output
  endpoints, `AD`/`AD_index`/`Conf_index` per endpoint, no `_predRange` column in the verified build.

## Status: needs_aaran

The parser is complete and green on the laptop (`tests/test_model_opera.py`, fast tier - no MCR). The
remaining step is installing the MCR/Java runtime on the box (recipe above) and capturing a real FTO-43
`preds.txt`; until then the box smoke skips and the task is `needs_aaran`, not blocked.
