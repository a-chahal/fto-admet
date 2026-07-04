# t21-model-admet_ai - ADMET-AI v2 (cross-cutting generalist)

**Kind:** model-code · **Autonomy:** review · **Runs:** author laptop; env + smoke on box
**Touch only:** `endpoints/triage/admet_ai/**`, `endpoints/triage/__init__.py`, `tests/test_model_admet_ai.py`
**Deps:** t12-gate-phase1 · **Template:** follow t10/t11

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §1 #1 (full ADMET-AI v2 column list + units + F-17).
- `docs/FTO_ADMET_Model_Provenance_VERIFIED.md` §B#1 (v2, deps, health).
- `CLAUDE.md` §4 (ADMET-AI landmine), §3 (uncertainty is INDIRECT here).

## Why it matters
This is the busiest cross-cutting model - its output feeds **10 endpoints'** aggregators (its `endpoints`
set: triage, herg, metabolism, clearance, ppb, solubility, lipophilicity, permeability, distribution,
toxicity). Emit **all** heads so each aggregator can pick its fields.

## Build
- `pip install admet_ai` (**v2**; Chemprop v2; latest release v2.0.1 "Fixing models on Linux/CUDA", Feb 2026
   - relevant to Rosenbluth). Deps modern: `torch>=2.8`, `rdkit>=2025.9`. GPU optional (`requires_gpu=False`,
  but honor `--gpu` if given). `pixi install` **on box**; commit lock.
- `run.py`: `ADMETModel().predict(smiles)` (dict/DataFrame) or CLI `admet_predict --data_path … --save_path …
  --smiles_column smiles`. Emit every column to `raw` (physchem 8, alert counts 3, classification heads incl.
  `hERG`/`BBB_Martins`/`Pgp_Broccatelli`/CYP heads/12 Tox21, regression heads, and each
  `<property>_drugbank_approved_percentile`).
- **Promote to `endpoint_values`** only the usable heads. **EXCLUDE `VDss_Lombardo` (R²=-1.21) and
  `Half_Life_Obach` (R²=-2.39) from `endpoint_values` entirely** (F-17) - keep them in `raw` tagged
  `excluded_r2_negative` so nothing downstream consumes them. Tag `Clearance_Hepatocyte_AZ` /
  `Clearance_Microsome_AZ` as **low-weight/qualitative** (note in `uncertainty.extra`).
- Units are baked per the IO spec: `PPBR_AZ`=%, `Clearance_Hepatocyte_AZ`=µL/min/10⁶ cells,
  `Clearance_Microsome_AZ`=µL/min/mg, `LD50_Zhu`=log(1/(mol/kg)) (**↑=more toxic**, NOT comparable to ProTox mg/kg).
- `uncertainty = None` per record (ADMET-AI has no native per-prediction uncertainty → the signal is
  **INDIRECT** cross-model spread, computed at aggregation).

## Landmines
- **Never let VDss or half-life reach `endpoint_values`.** Clearance heads low-weight only. Classification
  heads are strong (HIA 0.99, Pgp 0.95, CYP 0.89-0.94, BBB 0.90, hERG 0.84) → normal.
- **v2 ≠ v1** - predictions differ from the paper/web server; state it in README.
- Feed a **single canonical neutralized parent** (F-16 deferred); confirm behavior on the FTO di-cation at
  build time and note it - do not silently pick a protonation state.

## Done (gate: model kind - box-solved lock + smoke ok)
- Box smoke on FTO-43 returns the full column set in `raw`; `endpoint_values` **omits** VDss + half-life;
  clearance heads flagged low-weight; units correct.
- README: v2 pin, F-17 exclusions, INDIRECT-uncertainty note, LD50 non-comparability, F-16 note. Access CODE-PKG.

## Blocked if
- `admet_ai` v2 won't resolve/run on the box (CUDA/torch) after 3 attempts → BLOCK with the exact error.
