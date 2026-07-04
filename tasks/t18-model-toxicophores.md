# t18-model-toxicophores - toxicity structural alerts (rule)

**Kind:** model-rule · **Autonomy:** high · **Runs:** author laptop; env + smoke on box
**Touch only:** `endpoints/toxicity/toxicophores/**`, `endpoints/toxicity/__init__.py`, `tests/test_model_toxicophores.py`
**Deps:** t12-gate-phase1 · **Template:** follow t10

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §28 (Toxicophores) + `..._Provenance_VERIFIED` §B#30.

## Build
- `rdkit.Chem.FilterCatalog` over a toxicity alert catalog. **"toxicophores" is not one canonical RDKit
  catalog - pick and DOCUMENT exactly one** (BRENK as default; optionally a ToxAlerts SMARTS export).
- Output: per chosen catalog **match/no-match bool** + **matched alert names** + **count**.
- `endpoint_values = {"tox_alert_hit": <bool>, "tox_alert_count": <int>, "catalog": "<name>"}`; names → `raw`.

## Landmines
- **Distinct from t17 (PAINS/BRENK) by INTENT** (toxicity vs assay-interference), not mechanism - even if
  BRENK is reused, the framing and endpoint differ. Document the chosen catalog and the intent.
- More alerts = more flagged (soft).

## Done (gate: model kind - box-solved lock + smoke ok)
- Smoke on FTO-43 returns the fields + the documented catalog name; counts consistent with the flag.
- README names the single chosen catalog and the toxicity intent. Access CODE-PKG.

## Blocked if
- RDKit won't resolve on box after 3 attempts → BLOCK with the error.
