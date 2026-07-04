# t43-agg-clearance - DECOMPOSED (renal / hepatic / aggregate; never one number)

**Kind:** aggregator · **Autonomy:** review · **Runs:** laptop, core env
**Touch only:** `endpoints/clearance/aggregate.py`, `endpoints/clearance/test_aggregate.py`
**Deps:** t11-model-pksmart, t21-model-admet_ai, t33-model-opera, t37-sop-watanabe_renal

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §2 (clearance map) + §3 F-3.
- `CLAUDE.md` §4 (NEVER combine the four clearance units).

## Build - three separate decomposed reads (never merged)
- **Renal:** Watanabe `fe`, `CLr` (+ `fu_p`) [from the t37 SOP ledger transcription]. mL/min/kg.
- **Hepatic:** metabolism SoM (t42) + ADMET-AI `Clearance_Hepatocyte_AZ` (µL/min/10⁶ cells) /
  `Clearance_Microsome_AZ` (µL/min/mg) + OPERA `Clint_pred` (µL/min/10⁶ cells). This is the CLint
  conditional-specialist candidate.
- **Aggregate/total:** PKSmart `CL_mL_min_kg` **+ its fold-error** - **ranking only** (R²=0.31); surface the
  fold-error, never the bare CL number. Anchor ≈ 89.6 mL/min/kg (the FTO liability).
- (Integrator: PBPK C(t)→Cmax/AUC is shortlist, out of this aggregator.)
- Emit an `EndpointResult` that keeps renal / hepatic / aggregate as **separate labeled reads**, each with
  its own unit string, plus the PKSmart fold-error.

## Landmines (F-3)
- **NEVER combine the four numbers numerically** - different units and matrices. No mean, no sum. Keep them
  decomposed; the renal-vs-hepatic fork is resolved by experiment, not by the models.
- PKSmart CL is **ranking-only** + must carry its fold-error; never present the bare CL.

## Done (gate: `pixi run pytest endpoints/clearance/test_aggregate.py -q` green)
- Synthetic records across all four sources → the aggregator returns three labeled reads with distinct units
  and the fold-error, and there is **no code path that averages/sums across units** (assert the outputs stay
  separated).

## Blocked if
- Laptop-only; should not block. Record any error and BLOCK.
