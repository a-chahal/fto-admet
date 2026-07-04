# t51-agg-triage - cross-cutting generalist summary (funnel entry; flags only)

**Kind:** aggregator · **Autonomy:** review · **Runs:** laptop, core env
**Touch only:** `endpoints/triage/aggregate.py`, `endpoints/triage/test_aggregate.py`
**Deps:** t21-model-admet_ai, t35-model-admetlab3, t22-model-openadmet

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §2 (triage) + §1 #1-#3.
- `docs/FTO_ADMET_Pipeline_Skeleton_SETTLED.md` §7 (Phase 1 - flags only, no kills at triage).

## Build
- Summarize the generalist reads (ADMET-AI v2, ADMETlab 3.0, OpenADMET) into the **funnel-entry triage
  view** - a compact per-property flag table. **Flags only - no kills at this stage.**
- **Uncertainty = cross-model spread** (INDIRECT): where the generalists diverge, raise the flag. OpenADMET's
  native σ and ADMETlab's confidence flag feed the confidence read.
- Respect the exclusions: ADMET-AI VDss/half-life are already absent from `endpoint_values` (t21) - do not
  resurrect them here.

## Landmines
- **Flags, not kills** - triage never terminates a compound; it routes.
- Cross-model spread is the uncertainty signal; a single generalist is never authority.

## Done (gate: `pixi run pytest endpoints/triage/test_aggregate.py -q` green)
- Synthetic generalist records → a flag table + cross-model-spread confidence; divergent generalists raise
  the flag; no kill logic; excluded heads stay absent.

## Blocked if
- Laptop-only; should not block. Record any error and BLOCK.
