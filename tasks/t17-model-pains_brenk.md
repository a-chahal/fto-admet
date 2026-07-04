# t17-model-pains_brenk - PAINS / BRENK structural alerts (rule)

**Kind:** model-rule · **Autonomy:** high · **Runs:** author laptop; env + smoke on box
**Touch only:** `endpoints/structural_alerts/pains_brenk/**`, `endpoints/structural_alerts/__init__.py`, `tests/test_model_pains_brenk.py`
**Deps:** t12-gate-phase1 · **Template:** follow t10

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §24 (PAINS/BRENK).

## Build
- `rdkit.Chem.FilterCatalog` with `FilterCatalogParams.FilterCatalogs.PAINS` (A/B/C) and `BRENK`.
- Output per catalog: **match/no-match bool**, **list of matched entries** (name/description),
  **matched-atom substructure**, and a **count**.
- `endpoint_values = {"PAINS_hit": <bool>, "PAINS_count": <int>, "BRENK_hit": <bool>, "BRENK_count": <int>}`;
  matched names/atoms → `raw`.

## Landmines
- **Soft filter - look-closer, not auto-kill**; PAINS over-flags. State this in README. Matters here because
  the FTO assay is **fluorescence-based** (PAINS can flag assay-interfering scaffolds).
- Direction: more alerts = more flagged.

## Done (gate: model kind - box-solved lock + smoke ok)
- Smoke on FTO-43 returns the four fields + matched lists; counts are consistent with the boolean flags.
- README: soft-filter framing, fluorescence-assay relevance. Access CODE-PKG.

## Blocked if
- RDKit won't resolve on box after 3 attempts → BLOCK with the error.
