# t15-model-cns_mpo - CNS MPO (rule)

**Kind:** model-rule · **Autonomy:** review · **Runs:** author laptop; env + smoke on box
**Touch only:** `endpoints/distribution/cns_mpo/**`, `tests/test_model_cns_mpo.py`
**Deps:** t12-gate-phase1 · **Template:** follow t10 (endpoints/distribution/__init__.py already made by t14)

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §15 (CNS MPO) + §3 F-13 (shared pKa).

## Build
- `CNS_MPO` = **float on 0-6** (sum of six desirability transforms; monotonic on MW/cLogP/cLogD/HBD/most-basic
  pKa, **hump-shaped on TPSA**); **↑ = more CNS-desirable** (Wager 2010/2016).
- Inputs: MW, cLogP (Crippen), cLogD (via the shared pKa - F-13 placeholder), HBD, **most-basic pKa**, TPSA
  (Ertl). Same pKa source as t13/t14. Port reference: `Adam-maz/CNS_MPO_calculator`.
- `endpoint_values = {"CNS_MPO": <float 0..6>}`; optionally the six component desirabilities (0-1) in `raw`.

## Landmines
- **Same pKa source** as t13/t14 (F-13) - internally comparable only if identical.
- Rough filter only (weak on the PET-tracer set, AUC 0.53) - note in README; not a gate.

## Done (gate: model kind - box-solved lock + smoke ok)
- Smoke on FTO-43 returns a finite `CNS_MPO` in [0, 6]; the six-component sum is consistent.
- README: direction, shared-pKa note, rough-filter caveat. Access CODE-ALGO.

## Blocked if
- RDKit won't resolve on box after 3 attempts → BLOCK with the error.
