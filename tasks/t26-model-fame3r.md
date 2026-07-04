# t26-model-fame3r - FAME3R (site of metabolism; sklearn predict_proba)

**Kind:** model-code · **Autonomy:** review · **Runs:** author laptop; env + smoke on box
**Touch only:** `endpoints/metabolism/fame3r/**`, `tests/test_model_fame3r.py`
**Deps:** t12-gate-phase1 · **Template:** follow t11 (endpoints/metabolism/__init__.py made by t25)

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §1 #9 (FAME3R - VERIFIED sklearn scheme; no fixed CSV).
- `CLAUDE.md` §4 (metabolism direction inversion vs SMARTCyp).

## Build
- `pip install fame3r` (or conda-forge; MIT). Repo `molinfo-vienna/FAME3R`. `pixi install` on box; commit lock.
- Packaged as **scikit-learn components - NO fixed output CSV**; the adapter builds the DataFrame:
  - Per-atom SoM = `sklearn` pipeline `predict_proba(...)[:, 1]` = probability an atom is a site of metabolism
    (0-1, **↑ = more likely SoM**). Atoms are fed as **atom-marked SMILES** (`atom_to_marked_smiles`), so
    **the adapter must attach the RDKit atom indices itself** - there is no shipped `atom_id` column.
  - AD/reliability = a **separate** estimator `FAME3RScoreEstimator(n_neighbors=3)` → feature **`FAME3RScore`**
    (mean Tanimoto to k nearest reference atoms; ↑ = more in-domain).
- Emit the **per-atom probability table into `raw`** (atom index + SoM prob); put **`FAME3RScore` into
  `uncertainty`** (AD). Do not force per-atom into scalar `endpoint_values`.

## Landmines
- **No hard-coded 0.3 threshold** - that was the *old Java FAME 3*. FAME3R emits a **raw probability**;
  pick/justify a threshold yourself, or (preferred) co-rank ordinally with SMARTCyp at t42 (F-2).
- **Direction:** higher prob = more likely SoM - **opposite** to SMARTCyp (lower Score = SoM). The t42
  aggregator reconciles by **ordinal co-ranking**, never averaging the raw values.
- No "Shannon-entropy reliability" column - reliability = `FAME3RScore`.

## Done (gate: model kind - box-solved lock + smoke ok)
- Box smoke on FTO-43 returns a per-atom SoM-probability table with RDKit atom indices attached, plus
  `FAME3RScore` in `uncertainty`.
- README: predict_proba[:,1] scheme, no-0.3-threshold, direction (↑=SoM), atom-index handling. Access CODE-PKG.

## Blocked if
- `fame3r` won't resolve/run on the box after 3 attempts → BLOCK with the error.
