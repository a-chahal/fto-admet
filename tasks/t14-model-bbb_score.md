# t14-model-bbb_score - BBB Score (rule)

**Kind:** model-rule · **Autonomy:** review · **Runs:** author laptop; env + smoke on box
**Touch only:** `endpoints/distribution/bbb_score/**`, `endpoints/distribution/__init__.py`, `tests/test_model_bbb_score.py`
**Deps:** t12-gate-phase1 · **Template:** follow t10

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §13 (BBB Score) + §3 F-13 (shared pKa).
- `docs/FTO_ADMET_Model_Provenance_VERIFIED.md` §B#14 (deterministic; port + reference).

## Build
- `BBB_Score` = single **float on 0-6**; **↑ = more likely passive BBB penetrant** (Gupta 2019, AUC 0.86).
- Inputs from RDKit: #aromatic rings, heavy-atom count, an **MWHBN** term, **TPSA**, plus a **pKa** (same
  injectable placeholder source as t13/t15 - F-13). Reimplement the Gupta formula from the paper.
- `endpoint_values = {"BBB_Score": <float 0..6>}` (optionally the component terms in `raw`); `uncertainty=None`.
- **Unit-test the formula against the reference** port `gkxiao/BBB-score` on a couple of molecules.

## Landmines
- Passive filter only - **not** brain-exposure prediction; BBB is desirable, not a gate (note in README).
- pKa is the **shared placeholder** (F-13) - same source key as t13/t15; do not diverge per model.

## Done (gate: model kind - box-solved lock + smoke ok)
- Smoke on FTO-43 returns a finite `BBB_Score` in [0, 6]; formula matches the `gkxiao/BBB-score` reference
  within tolerance on the unit-test molecules.
- README: direction (↑=more penetrant), passive-only caveat, shared-pKa note. Access CODE-ALGO.

## Blocked if
- RDKit won't resolve on box after 3 attempts → BLOCK with the error.
