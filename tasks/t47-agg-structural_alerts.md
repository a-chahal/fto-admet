# t47-agg-structural_alerts - union of PAINS/BRENK matches (soft flag)

**Kind:** aggregator · **Autonomy:** high · **Runs:** laptop, core env
**Touch only:** `endpoints/structural_alerts/aggregate.py`, `endpoints/structural_alerts/test_aggregate.py`
**Deps:** t17-model-pains_brenk

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §2 (structural_alerts).

## Build
- Union of PAINS/BRENK matches → **counts + the matched-alert list** as a **soft flag** (look-closer, not
  auto-kill). Emit `{PAINS_count, BRENK_count, matched: [...], any_hit: bool}`.

## Landmines
- **Soft filter** - over-flags; never a kill. Relevant because the FTO assay is fluorescence-based.

## Done (gate: `pixi run pytest endpoints/structural_alerts/test_aggregate.py -q` green)
- Synthetic records → the union + counts + matched list are correct; the result is a flag, not a pass/fail gate.

## Blocked if
- Laptop-only; should not block. Record any error and BLOCK.
