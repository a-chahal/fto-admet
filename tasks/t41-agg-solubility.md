# t41-agg-solubility - relative solubility rank (SFI vs generalist)

**Kind:** aggregator · **Autonomy:** review · **Runs:** laptop, core env
**Touch only:** `endpoints/solubility/aggregate.py`, `endpoints/solubility/test_aggregate.py`
**Deps:** t13-model-sfi, t21-model-admet_ai

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §2 (solubility map).

## Build
- Common quantity = **relative solubility rank.** Consume SFI (`SFI`, **LOWER = better**) as primary and
  ADMET-AI `Solubility_AqSolDB` (log S, **higher = better**) as cross-check.
- **Uncertainty = SFI-vs-generalist discrepancy** (likely a series *strength* for the low-aromatic oxetane).

## Landmines
- **Direction inversion:** SFI lower = better vs logS higher = better. **Reconcile before ranking** - negate
  SFI (or rank ordinally) so both point the same way. A raw average of the two is wrong.

## Done (gate: `pixi run pytest endpoints/solubility/test_aggregate.py -q` green)
- With synthetic records, a low-SFI molecule and a high-logS molecule rank as *more* soluble (inversion
  handled); a large SFI-vs-generalist gap raises the discrepancy flag.

## Blocked if
- Laptop-only; should not block. Record any error and BLOCK.
