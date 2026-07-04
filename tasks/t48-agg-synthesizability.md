# t48-agg-synthesizability - escalating tier (the ladder IS the signal)

**Kind:** aggregator · **Autonomy:** review · **Runs:** laptop, core env
**Touch only:** `endpoints/synthesizability/aggregate.py`, `endpoints/synthesizability/test_aggregate.py`
**Deps:** t20-model-sascore, t31-model-rascore, t32-model-aizynthfinder

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §2 (synthesizability map).

## Build
- Escalating rigor ladder = the confidence signal: **SAscore (1-10, LOWER = easier) → RAscore (P route
  findable) → AiZynthFinder (`is_solved` bool + routes, shortlist)**. Report a **tier / flag, not one
  scalar** (the three are on different scales).
- Emit `{tier: "easy|likely|confirmed|hard", SAscore, RAscore, is_solved, top_score}` - the ladder position
  is the answer.

## Landmines
- **Different scales - do NOT collapse into one number.** SAscore lower = easier (inversion). AiZynthFinder
  key is `is_solved` (t32). The ladder progression is the signal.

## Done (gate: `pixi run pytest endpoints/synthesizability/test_aggregate.py -q` green)
- Synthetic records → the tier is assigned correctly (e.g. low SAscore + high RAscore + is_solved → top
  tier); no single fabricated scalar; SAscore inversion handled.

## Blocked if
- Laptop-only; should not block. Record any error and BLOCK.
