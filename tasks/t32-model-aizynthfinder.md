# t32-model-aizynthfinder - AiZynthFinder (retrosynthesis route search; shortlist)

**Kind:** model-heavy · **Autonomy:** review · **Runs:** author laptop; env + smoke on box · **in_bulk_loop = False**
**Touch only:** `endpoints/synthesizability/aizynthfinder/**`, `tests/test_model_aizynthfinder.py`
**Deps:** t12-gate-phase1 · **Template:** follow t11

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §1 #27 (AiZynthFinder - VERIFIED statistics keys).
- `docs/FTO_ADMET_Model_Provenance_VERIFIED.md` §B#29.

## Build
- `pip install aizynthfinder` (MIT, actively maintained). RDKit + TF/PyTorch policy. **Requires a configured
  stock set** (ZINC/Enamine/ACD) **+ a downloaded policy model** - the heavy part; cache both under
  `/zfs` and document the config in the README.
- Input: target SMILES + stock + policy. Output (VERIFIED, from `extract_statistics()`):
  `is_solved` (bool - route to purchasable precursors found; **the key is `is_solved`, NOT `solved`**),
  `number_of_nodes`, `number_of_routes`, `number_of_steps`, `number_of_precursors`,
  `number_of_precursors_in_stock`, `top_score` (0-1, ↑=better; default "state score"). Full route trees via
  `RouteCollection.dict_with_scores()`/`.to_dict()` (`reaction_tree`, `route_metadata`, `all_scores`).
- Emit `endpoint_values = {"is_solved": bool, "top_score": float, "number_of_steps": int, ...}`;
  route trees → `raw`. **Shortlist only** (`in_bulk_loop=False`) - top rung of the synthesizability ladder.

## Landmines
- **The key is `is_solved`, not `solved`** (`solved` is an internal per-node key). Reading the wrong key
  silently reports every target as unsolved.
- Requires the **stock set + policy model** configured - without them AiZynthFinder cannot solve anything;
  document the exact config and cache locations.

## Done (gate: model kind - box-solved lock + smoke ok)
- Box smoke on FTO-43 returns `is_solved` + `top_score` + step/route counts; the stock + policy are
  configured and cached under `/zfs`.
- README: `is_solved` key, stock/policy config, shortlist-only role, direction. Access CODE-PKG.

## Blocked if
- The policy model / stock set cannot be obtained or configured on the box, or the env won't resolve, after
  3 attempts → BLOCK with the exact error.
