# t03-core-schemas - `core/schemas.py` (pydantic I/O contracts; reserve uncertainty/AD)

**Kind:** core · **Autonomy:** review · **Runs:** laptop, core env, no GPU
**Touch only:** `core/schemas.py`, `tests/test_schemas.py`
**Deps:** t02-core-models

## Read first
- `CLAUDE.md` §3 (schema rule - **reserve uncertainty/AD fields from day one**) and §4/§4a (native signals; deferred F-16).
- `docs/FTO_ADMET_Model_IO_SPEC.md` §1 (per-model output shapes) and §3 (flags F-1…F-17, esp. F-16, F-17).

## Build
pydantic v2 models validated **before** any subprocess launches. The point of this task is the shared
envelope, not per-model exhaustiveness - per-model output subclasses are added with each model.

1. **`InputRecord`** - `smiles: str` (canonical), `mol_id: str | None`, and standardization metadata:
   `standardized: bool = False`, `standardizer: str | None`. F-16 (the FTO di-cation protonation/tautomer
   decision) is **DEFERRED** - do not implement a standardizer here; just carry the fields so the pipeline
   can record which canonical form was fed. Reject empty/whitespace SMILES.
2. **`Uncertainty`** - a reusable envelope with **all-optional** fields covering the native signals present
   in the set (so no adapter needs retrofitting later): `aleatoric`, `epistemic`, `fold_error_low`,
   `fold_error_high`, `confidence` (0-1), `ad_in_domain: bool | None`, `ad_index` (0-1),
   `extra: dict = {}` (model-specific). Nothing here is required.
3. **`ADStatus`** (optional, or fold into `Uncertainty`) - carry OPERA-style `AD` flag + `AD_index` +
   `Conf_index` cleanly. Your call whether separate or merged; document it.
4. **`OutputRecord`** (base) - `model: ModelName`, `endpoint_values: dict[str, float | int | str | bool | None]`
   (or a typed payload), `uncertainty: Uncertainty | None = None`, `raw: dict = {}` (verbatim upstream
   output, for the cache/audit trail), `provenance: dict` (upstream commit, env-lock hash placeholder).
5. Provide a `validate_input`/`validate_output` entry the dispatcher calls.

## Landmines
- **Reserve, don't decide.** The operational AD rule + calibration are DEFERRED (`CLAUDE.md` §4a). Build the
  fields; do not implement a policy that consumes them.
- Per-atom outputs (SMARTCyp/FAME3R site-of-metabolism) need a table shape - allow `raw` to hold a
  per-atom list; don't force them into the scalar `endpoint_values`.
- Direction/units live in the per-model schema notes, not here - but leave room to annotate them.

## Done (gate: `pixi run pytest tests/test_schemas.py -q` green)
- `InputRecord` rejects empty SMILES; accepts a canonical one with optional id/standardization fields.
- `Uncertainty` instantiates with **zero** fields set, and with a fold-error interval, and with
  aleatoric+epistemic - all valid; `OutputRecord` embeds an optional `Uncertainty`.
- An `OutputRecord` with a native fold-error round-trips (serialize→parse) unchanged; `raw` preserves a
  per-atom list without loss.

## Blocked if
- Laptop-only; should not block. Record any error and BLOCK.
