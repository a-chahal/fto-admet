# watanabe_pgp_brain - Brain P-gp efflux / Kp,uu,brain / fu,brain via DruMAP (WEB-ONLY SOP)

DruMAP (Drug Metabolism And Pharmacokinetics predictor, NIBIOHN) is a **form-based web app with no
public API and no downloadable package**. There is no bulk path, so this endpoint is **manual /
shortlist only**: a human runs the final shortlist through the web UI and hand-transcribes the result
into the ledger. There is no `run.py`, no `pixi.toml`, and no environment here.

- `in_bulk_loop = False`, `env_manifest = None`, `entrypoint = None` (registry entry, when added, is a
  pure SOP record with no code path).
- This is a **passive/efflux score only**; the real CNS answer is the experimental **Kp,uu**. A
  favorable BBB / P-gp read is **desirable, not a gate** - this endpoint is a triage read into the
  distribution/CNS-penetration signal, not a promotion criterion on its own.
- Source: Watanabe 2021 (*J. Med. Chem.*); DruMAP, *J. Med. Chem.* 2023 (10.1021/acs.jmedchem.3c00481).

## URL

`https://drumap.nibiohn.go.jp/prediction` - the DruMAP prediction web app. No API, no CSV/REST
endpoint, no installable package. If the URL or flow has changed at run time, note the new path in this
section and still transcribe whatever the live page yields (this is a documentation SOP; it does not
block on a moved page).

## INPUTS

- **SMILES** of the shortlist molecule, entered (or drawn) into the DruMAP prediction form. Feed the
  single canonical input from `core` (the documented placeholder standardizer, F-16). DruMAP has no
  documented desalt/protonation contract, so **flag any divergence** from the shared standardized parent
  rather than silently re-protonating for this tool (do NOT invent a per-model protonation state; the
  F-16 standardization decision is DEFERRED - CLAUDE.md §4a).
- **organism = human** (select the human model for the P-gp / CNS heads). Note that `Kp,uu,brain` and
  `fu,brain` are **rat**-derived heads (record them as-is; do not re-scale to human).

## SELECT

Select the **brain-P-gp / CNS-penetration endpoints**: the brain P-gp efflux class (**NER class**),
**`Kp,uu,brain`** (unbound brain-to-plasma ratio), and **`fu,brain`** (fraction unbound in brain
homogenate).

**Run this in the SAME DruMAP session as t37** (F-14, the DruMAP one-session rule). A single web
session captures every DruMAP endpoint at once, so run these P-gp/brain fields together with:

- **t37 renal** - `fe`, `CLr`, `fu,p` (`endpoints/clearance/watanabe_renal/`), and
- the remaining DruMAP fields **`CLint`, `Fa`**.

Capture them all in the same run and transcribe each to its own endpoint's ledger shape. Do not open a
separate DruMAP session per field.

## OUTPUT FIELDS

Transcribe in this fixed shape (units + direction fixed; **confirm the live labels/classes on the page
before recording**):

| Field              | Type          | Unit / classes                                                      | Direction                                          |
| ------------------ | ------------- | ------------------------------------------------------------------- | -------------------------------------------------- |
| `pgp_brain_efflux` | class         | NER class (net efflux ratio class, e.g. "Low")                      | ↑ efflux = ↓ brain penetration                     |
| `Kp_uu_brain`      | float         | unbound brain-to-plasma ratio (rat)                                 | ↑ = more brain penetration (≥ 0.5 ≈ penetrant)     |
| `fu_brain`         | float         | fraction unbound in brain homogenate (0-1)                          | ↑ = more free in CNS                               |

- `pgp_brain_efflux` is a **class** (net efflux ratio class, e.g. "Low"); record the class exactly as
  displayed (and the underlying value/probability if the page shows one) - do not threshold or
  re-bin it here. **Higher efflux means lower brain penetration** (the direction is inverted relative to
  the other two fields - do not flip it).
- `Kp_uu_brain` is the rat unbound brain-to-plasma ratio; `≥ 0.5` is the rough penetrant heuristic, but
  record the raw value and do not threshold it in the ledger.
- `fu_brain` is on 0-1.
- If the live page shows different labels or units than above, record the page's wording verbatim and do
  not silently convert or rename (no-fabricate rule, CLAUDE.md §5).

Uncertainty / applicability-domain: DruMAP does not emit a native per-prediction confidence for these
heads. Leave the schema's first-class `Uncertainty` fields null (the operational AD / calibration policy
is DEFERRED, CLAUDE.md §4a); if the live page shows any AD / confidence flag, stash it verbatim under
`uncertainty.extra`.

## LEDGER TRANSCRIPTION SHAPE

Hand-enter one JSON record per molecule, matching `core.ledger` (the required keys `model`,
`input_hash`, `output_path`, `env_lock_hash`, `cuda_device`, `timestamp`, `status`), with the DruMAP
provenance and the three predicted fields carried in the payload. For a web/manual run there is no env
lock and no GPU, so `env_lock_hash` and `cuda_device` are `null`; `output_path` points at the cached raw
DruMAP response saved to `/zfs` (raw-output caching is in scope, CLAUDE.md §4a), and `run_by` records the
human operator.

```json
{
  "model": "watanabe_pgp_brain",
  "input_hash": "<sha256 of the standardized SMILES fed to DruMAP>",
  "output_path": "/zfs/sanjanp/fto-admet/raw_cache/drumap/<molecule>_<timestamp>.html",
  "env_lock_hash": null,
  "cuda_device": null,
  "timestamp": "<ISO-8601 UTC of the web run>",
  "status": "ok",
  "source": "DruMAP",
  "run_by": "<operator name/initials>",
  "predictions": {
    "pgp_brain_efflux": { "value": "<NER class>", "unit": "NER class (net efflux ratio, e.g. \"Low\")", "direction": "up efflux = down brain penetration" },
    "Kp_uu_brain":      { "value": null, "unit": "unbound brain-to-plasma ratio (rat)", "direction": "up = more brain penetration (>=0.5 ~ penetrant)" },
    "fu_brain":         { "value": null, "unit": "fraction unbound in brain homogenate (0-1)", "direction": "up = more free in CNS" }
  },
  "note": "manual DruMAP web run (organism=human); batched in one session with watanabe_renal (F-14); passive/efflux triage read only, real CNS answer is experimental Kp,uu; BBB desirable, not a gate"
}
```

The `source=DruMAP`, `run_by`, and `predictions` keys sit alongside the seven `core.ledger` required
columns; the ledger writer keeps the required columns and preserves the extra keys. Save the DruMAP page
(HTML/screenshot) to the `/zfs` raw cache at `output_path` so the record stays reconstructible if the
service changes. This is the **same cached DruMAP session** as `watanabe_renal` (F-14): one raw capture
backs both endpoints' records.
