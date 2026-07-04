# t31-model-rascore - RAscore (retrosynthetic accessibility; legacy 2021 stack)

**Kind:** model-legacy · **Autonomy:** review · **Runs:** author laptop; env + smoke on box
**Touch only:** `endpoints/synthesizability/rascore/**`, `tests/test_model_rascore.py`
**Deps:** t12-gate-phase1 · **Template:** follow t11 · **LEGACY - health-check the env FIRST**

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §1 #26 (RAscore).
- `docs/FTO_ADMET_Model_Provenance_VERIFIED.md` §B#28 + §E.8 (2021 TF/sklearn pins - health-check first).

## Health-check FIRST
Repo `reymond-group/RAscore`; **2021-era TF/sklearn**. The shipped model must load under matching pinned
versions - **pin them first**, prove the env resolves and the model unpickles on the box, then build. BLOCK
after 3 attempts with the exact error.

## Build
- Input: SMILES. Output: **prob 0-1** that a synthetic route is findable by AiZynthFinder (binary
  retrosynthetic-accessibility classifier); **↑ = more likely synthesizable**.
- `endpoint_values = {"RAscore": <float 0..1>}`; `uncertainty = None`.
- Role: **second rung** of the synthesizability tier ladder (SAscore → **RAscore** → AiZynthFinder). Bulk-ok.

## Landmines
- 2021 TF/sklearn pins - a wrong pin silently fails to unpickle the classifier. Isolate.
- It's a *classifier for route-findability*, not a route search (that's t32) - keep them distinct in the README.

## Done (gate: model kind - box-solved lock + smoke ok)
- Box smoke on FTO-43 returns a finite `RAscore` in [0,1]; lock box-solved with the pinned 2021 stack.
- README: direction, tier-ladder role, pinned versions. Access CODE-PKG.

## Blocked if
- The 2021 TF/sklearn env won't resolve or the model won't unpickle on the box after 3 attempts → BLOCK.
