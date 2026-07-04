# t46-agg-permeability - aggregate-only (permeability flag + absorption flag)

**Kind:** aggregator · **Autonomy:** high · **Runs:** laptop, core env
**Touch only:** `endpoints/permeability/aggregate.py`, `endpoints/permeability/__init__.py`, `endpoints/permeability/test_aggregate.py`
**Deps:** t21-model-admet_ai, t16-model-boiled_egg

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §2 (permeability map).

## Build
- **No own models** - consume generalist fields + BOILED-Egg. Fields: `Caco2_Wang` (log Papp, cm/s),
  `HIA_Hou` (P), `PAMPA_NCATS` (P), `Bioavailability_Ma` / %F (P - **weak, treat with suspicion**),
  `Pgp_Broccatelli` (P efflux), BOILED-Egg `HIA_boiled_egg` (bool).
- Emit a **permeability flag + an absorption flag** (no single scalar). Note this endpoint may be partly moot
  given possible intratumoral / osmotic-pump delivery - keep it as an aggregate read.

## Landmines
- `%F` / `Bioavailability_Ma` is **weak - flag with suspicion**, don't let it dominate.
- Aggregate-only: this endpoint has no `ModelName`; it reads other endpoints' cross-cutting models.

## Done (gate: `pixi run pytest endpoints/permeability/test_aggregate.py -q` green)
- Synthetic generalist + BOILED-Egg records → permeability and absorption flags are produced; %F is
  down-weighted/flagged; no single fabricated scalar.

## Blocked if
- Laptop-only; should not block. Record any error and BLOCK.
