# protox - ProTox 3.0 toxicity panel (WEB-ONLY SOP; shortlist confirmatory)

ProTox 3.0 (Charite Berlin) is a **form-based toxicity webserver with no public API and no
downloadable package**. There is no bulk path, so this endpoint is **manual / shortlist only**: a human
runs the final shortlist through the web UI and hand-transcribes the result into the ledger. There is no
`run.py`, no `pixi.toml`, and no environment here.

- `in_bulk_loop = False`, `env_manifest = None`, `entrypoint = None` (registry entry, when added, is a
  pure SOP record with no code path).
- This is the **shortlist confirmatory** toxicity read. Bulk triage is substituted by ADMET-AI +
  ADMETlab (LD50_Zhu, DILI, hERG, AMES, carcinogenicity, ClinTox, skin) - that is a **coverage /
  throughput** substitution, **not** a quality-equivalence one.
- Source: ProTox 3.0, Banerjee et al., *Nucleic Acids Research* 52(W1):W513-W520 (2024),
  `https://doi.org/10.1093/nar/gkae303` (Oxford/PMC11223834). Free, no login.

## No automatable substitute (run this on every shortlist molecule)

ProTox-web is the **only** source for these fields - nothing in the bulk panel covers them, so they are
**lost entirely if this SOP is skipped**:

- **respiratory toxicity** (organ panel),
- **ecotoxicity**, **nutritional toxicity**,
- the **15 tox off-targets**,
- the **14 MIE (molecular initiating event) targets**,
- **most of the 6 metabolism targets**.

Everything else ProTox emits (acute LD50/class, hepato/neuro/nephro/cardio tox, carcinogenicity,
mutagenicity, cytotoxicity, immunotoxicity, BBB, clinical tox, the 12 Tox21 pathways) has a bulk
substitute, but ProTox remains the richer, confirmatory read on the shortlist.

## URL

`https://tox.charite.de` - the ProTox 3.0 prediction webserver (form-based; **no API, no REST/CSV
endpoint, no installable package**). If the URL or flow has changed at run time, note the new path in
this section and still transcribe whatever the live page yields (this is a documentation SOP; it does not
block on a moved page).

## INPUTS

- **SMILES** of the shortlist molecule, pasted (or drawn) into the ProTox input form. Feed the single
  canonical input from `core` (the documented placeholder standardizer, F-16). ProTox has no documented
  desalt/protonation contract, so **flag any divergence** from the shared standardized parent rather than
  silently re-protonating for this tool (do NOT invent a per-model protonation state; the F-16
  standardization decision is DEFERRED - CLAUDE.md §4a).

## SELECT

**Select "ALL models".** This is the load-bearing step: the ProTox **default is acute toxicity + targets
only**, which silently omits the organ / AOP / off-target panel. You MUST tick **ALL models** to get the
full endpoint set (respiratory + eco + nutritional organ/tox endpoints, the Tox21 pathways, the 15 tox
off-targets, the 14 MIE targets, and the 6 metabolism targets). If only the default is run, the
no-substitute fields above are missing and the run is incomplete.

Run each shortlist molecule as its own submission; there is no batch upload. Save the results page
(radar/network plots included) to the `/zfs` raw cache (see LEDGER TRANSCRIPTION SHAPE).

## OUTPUT FIELDS

Transcribe in this fixed shape (units + direction fixed):

| Field                    | Type            | Unit / classes                                              | Direction                                   |
| ------------------------ | --------------- | ----------------------------------------------------------- | ------------------------------------------- |
| `LD50`                   | float           | mg/kg (predicted median lethal dose)                        | **LOWER = more toxic**                      |
| `tox_class`              | enum 1-6        | acute oral toxicity class                                   | **1 = most toxic, 6 = least**               |
| `prediction_accuracy`    | percent         | reported per acute-tox prediction                           | ↑ = more confident                          |
| per-endpoint prediction  | class + prob    | `"Active"` / `"Inactive"` + probability [0-1]               | Active = toxic; prob → 1 = more confident   |
| toxicity targets         | name + fit + similarity | off-target hits (target name, fit score, similarity) | -                                           |

**Per-endpoint predictions** (each an `Active`/`Inactive` call + probability) span the full ProTox panel
- transcribe every one that the "ALL models" run returns:

- **organ toxicity:** hepatotoxicity, neurotoxicity, nephrotoxicity, cardiotoxicity, **respiratory
  toxicity**;
- **toxicological endpoints:** carcinogenicity, mutagenicity, cytotoxicity, immunotoxicity, BBB-barrier,
  clinical toxicity, **ecotoxicity**, **nutritional toxicity**;
- **12 Tox21 stress-response / nuclear-receptor pathways**;
- **14 MIE targets** (molecular initiating events);
- **15 tox off-targets**;
- **6 metabolism targets**.

**Toxicity targets** are the off-target hit list: record each as `name` + `fit` (fit/activity score) +
`similarity` exactly as the page shows them.

Direction summary: `Active` = predicted toxic; probability closer to 1 = higher confidence; **LD50 lower
and class lower (1) = more dangerous.**

### LD50 non-comparability (F-5) - do not merge with ADMET-AI

**`LD50` (mg/kg) is NOT comparable to ADMET-AI's `LD50_Zhu` (log(1/(mol/kg)))** - different scale and
different direction convention. Keep them as **separate reads**: this ProTox `LD50` is the shortlist
confirmatory value; `LD50_Zhu` is the bulk triage value. Never convert one into the other or average
them (F-5; CLAUDE.md §4 harmonize-before-ranking / no-fabricate).

Uncertainty / applicability-domain: `prediction_accuracy` (%) is ProTox's reported per-acute-tox
confidence and the per-endpoint probabilities are its confidence signal; carry `prediction_accuracy` and
each probability verbatim. Leave the schema's first-class `Uncertainty` fields for the calibrated policy
(operational AD / calibration is DEFERRED, CLAUDE.md §4a); stash any extra ProTox confidence marker
verbatim under `uncertainty.extra`.

## LEDGER TRANSCRIPTION SHAPE

Hand-enter one JSON record per molecule, matching `core.ledger` (the required keys `model`,
`input_hash`, `output_path`, `env_lock_hash`, `cuda_device`, `timestamp`, `status`), with the ProTox
provenance and the fields above carried in the payload. For a web/manual run there is no env lock and no
GPU, so `env_lock_hash` and `cuda_device` are `null`; `output_path` points at the cached raw ProTox
results page saved to `/zfs` (raw-output caching is in scope, CLAUDE.md §4a), and `run_by` records the
human operator.

```json
{
  "model": "protox",
  "input_hash": "<sha256 of the standardized SMILES fed to ProTox>",
  "output_path": "/zfs/sanjanp/fto-admet/raw_cache/protox/<molecule>_<timestamp>.html",
  "env_lock_hash": null,
  "cuda_device": null,
  "timestamp": "<ISO-8601 UTC of the web run>",
  "status": "ok",
  "source": "ProTox 3.0",
  "run_by": "<operator name/initials>",
  "predictions": {
    "LD50":                { "value": null, "unit": "mg/kg", "direction": "lower = more toxic" },
    "tox_class":           { "value": null, "unit": "acute oral tox class 1-6", "direction": "1 = most toxic, 6 = least" },
    "prediction_accuracy": { "value": null, "unit": "percent", "direction": "up = more confident" },
    "endpoints": {
      "<endpoint name>": { "call": "Active|Inactive", "probability": null }
    },
    "toxicity_targets": [
      { "name": "<target>", "fit": null, "similarity": null }
    ]
  },
  "note": "manual ProTox 3.0 web run; SELECT=ALL models (default omits organ/AOP/off-target panel); shortlist confirmatory; LD50 (mg/kg) NOT comparable to ADMET-AI LD50_Zhu (F-5); only source for respiratory/eco/nutritional tox + 15 off-targets + 14 MIE + 6 metabolism targets"
}
```

`endpoints` holds one entry per per-endpoint prediction (organ / tox / Tox21 / MIE / off-target /
metabolism), keyed by the endpoint name exactly as ProTox labels it, each with its `Active`/`Inactive`
`call` and `probability`. The `source="ProTox 3.0"`, `run_by`, and `predictions` keys sit alongside the
seven `core.ledger` required columns; the ledger writer keeps the required columns and preserves the
extra keys. Save the ProTox results page (HTML/screenshot, including the radar/network plots) to the
`/zfs` raw cache at `output_path` so the record stays reconstructible if the service changes.
