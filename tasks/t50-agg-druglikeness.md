# t50-agg-druglikeness - context flags only (no gate)

**Kind:** aggregator · **Autonomy:** high · **Runs:** laptop, core env
**Touch only:** `endpoints/druglikeness/aggregate.py`, `endpoints/druglikeness/test_aggregate.py`
**Deps:** t19-model-lipinski_veber_qed

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §2 (druglikeness).

## Build
- **Context flags only:** surface `Lipinski_violations`, `Veber_pass`, `QED` as-is. **No gate aggregation** - 
  these are read by the lab, never a kill.
- Emit `{Lipinski_violations, Veber_pass, QED}` with a one-line "context, not a gate" note.

## Landmines
- **POINTER / context** - do not convert these into an advance/kill decision.

## Done (gate: `pixi run pytest endpoints/druglikeness/test_aggregate.py -q` green)
- Synthetic record → the three fields pass through unchanged; no gate/kill logic is present.

## Blocked if
- Laptop-only; should not block. Record any error and BLOCK.
