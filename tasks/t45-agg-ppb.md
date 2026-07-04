# t45-agg-ppb - fraction bound (0-1)

**Kind:** aggregator · **Autonomy:** review · **Runs:** laptop, core env
**Touch only:** `endpoints/ppb/aggregate.py`, `endpoints/ppb/test_aggregate.py`
**Deps:** t36-model-ochem_ppb, t21-model-admet_ai, t33-model-opera

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §2 (ppb map) + §3 F-7.

## Build
- Common quantity = **fraction bound (0-1); ↑ = more bound (less free).**
- Consume: OCHEM PPB (primary; **% → /100** to fraction), ADMET-AI `PPBR_AZ` (% → /100),
  OPERA `FuB_pred` (fraction **unbound** → **1 - FuB**).
- Not a gate (modulator); single tool acceptable, cross-checks optional. OCHEM's accuracy/AD → carry as the
  confidence.

## Landmines
- **Unit normalization:** OCHEM + ADMET-AI are **%** → divide by 100; OPERA is **fraction unbound** →
  invert (`1 - FuB`). A missed inversion or a %/fraction mixup silently corrupts the consensus.

## Done (gate: `pixi run pytest endpoints/ppb/test_aggregate.py -q` green)
- Synthetic records (OCHEM 90%, ADMET-AI 90%, OPERA FuB 0.1) all resolve to fraction bound ≈ 0.90; the
  OPERA inversion is applied; direction ↑ = more bound.

## Blocked if
- Laptop-only; should not block. Record any error and BLOCK.
