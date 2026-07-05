# watanabe_renal - Renal fe / CLr / fu,p via DruMAP (WEB-ONLY SOP)

DruMAP (Drug Metabolism And Pharmacokinetics predictor, NIBIOHN) is a **form-based web app with no
public API and no downloadable package**. There is no bulk path, so this endpoint is **manual /
shortlist only**: a human runs the final shortlist through the web UI and hand-transcribes the result
into the ledger. There is no `run.py`, no `pixi.toml`, and no environment here.

- `in_bulk_loop = False`, `env_manifest = None`, `entrypoint = None` (registry entry, when added, is a
  pure SOP record with no code path).
- The renal-vs-hepatic clearance fork is **resolved by experiment, not this model** - these numbers are
  a **triage read only** (CLAUDE.md §4: never combine the four clearance numbers numerically; keep
  renal / hepatic / aggregate decomposed).
- Source: DruMAP, *J. Med. Chem.* 2023 (10.1021/acs.jmedchem.3c00481); renal model per Watanabe et al.,
  *Sci. Rep.* 2019, 9:18782.

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
- **organism = human** (select the human model, not rat, for fe / CLr / fu,p).

## SELECT

Select the **renal endpoints: `fe` (fraction excreted unchanged) and `CLr` (renal clearance)**, and the
plasma-unbound descriptor **`fu,p`** that the renal model also reports.

**Run this in ONE DruMAP session, batched with t38** (F-14, the DruMAP one-session rule). A single web
session captures every DruMAP endpoint at once, so run these renal fields together with:

- **t38 P-gp brain** - `pgp_brain_efflux` (NER class), `Kp,uu,brain`, `fu,brain`
  (`endpoints/distribution/watanabe_pgp_brain/`), and
- the remaining DruMAP fields **`CLint`, `Fa`** (and the `fu,brain` / `Kp,uu,brain` above).

Capture them all in the same run and transcribe each to its own endpoint's ledger shape. Do not open a
separate DruMAP session per field.

## OUTPUT FIELDS

Transcribe in this fixed shape (units + direction fixed; **confirm the live CLr unit before recording**):

| Field  | Type          | Unit / classes                                         | Direction                                     |
| ------ | ------------- | ------------------------------------------------------ | --------------------------------------------- |
| `fe`   | class / value | fraction excreted unchanged in urine (binary classifier) | ↑ = more renal (unchanged) route            |
| `CLr`  | float         | renal clearance (**mL/min/kg - confirm the unit on the live page**) | ↑ = faster renal clearance      |
| `fu_p` | float         | fraction unbound in plasma (0-1; also a descriptor into the renal model) | ↑ = more free drug          |

- `fe` is a **binary classifier** output; record the class (and the probability/value if the page shows
  one) exactly as displayed - do not threshold it here.
- `CLr` units are stated as **mL/min/kg** but this **must be confirmed against the live DruMAP page** at
  run time; if the page shows different units (e.g. L/h/kg), record the page's unit verbatim and do not
  silently convert (no-fabricate rule, CLAUDE.md §5). Never numerically combine `CLr` with the other
  clearance numbers (PKSmart CL, ADMET-AI hepatocyte/microsome CL, OPERA `Clint`, DruMAP `CLint`) -
  different units and matrices (CLAUDE.md §4).
- `fu_p` is on 0-1.

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
  "model": "watanabe_renal",
  "input_hash": "<sha256 of the standardized SMILES fed to DruMAP>",
  "output_path": "/zfs/sanjanp/fto-admet/raw_cache/drumap/<molecule>_<timestamp>.html",
  "env_lock_hash": null,
  "cuda_device": null,
  "timestamp": "<ISO-8601 UTC of the web run>",
  "status": "ok",
  "source": "DruMAP",
  "run_by": "<operator name/initials>",
  "predictions": {
    "fe":   { "value": "<class or probability>", "unit": "fraction excreted unchanged (binary classifier)", "direction": "up = more renal (unchanged) route" },
    "CLr":  { "value": null, "unit": "mL/min/kg (CONFIRM on live page)", "direction": "up = faster renal clearance" },
    "fu_p": { "value": null, "unit": "fraction unbound in plasma (0-1)", "direction": "up = more free drug" }
  },
  "note": "manual DruMAP web run (organism=human); batched in one session with watanabe_pgp_brain (F-14); triage read only, renal-vs-hepatic fork resolved by experiment"
}
```

The `source=DruMAP`, `run_by`, and `predictions` keys sit alongside the seven `core.ledger` required
columns; the ledger writer keeps the required columns and preserves the extra keys. Save the DruMAP page
(HTML/screenshot) to the `/zfs` raw cache at `output_path` so the record stays reconstructible if the
service changes.
