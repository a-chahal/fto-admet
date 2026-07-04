# t16-model-boiled_egg - BOILED-Egg (rule; serves distribution + permeability)

**Kind:** model-rule · **Autonomy:** high · **Runs:** author laptop; env + smoke on box
**Touch only:** `endpoints/distribution/boiled_egg/**`, `tests/test_model_boiled_egg.py`
**Deps:** t12-gate-phase1 · **Template:** follow t10

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §14 (BOILED-Egg - VERIFIED point-in-polygon mechanism).
- Implementation reference: `bfmilne/pyBOILEDegg` (ships the polygon vertex lists).

## Build
- Output = **two booleans**: `HIA` (white region → passive GI absorption; True=absorbed) and
  `BBB` (yolk region → passive brain penetration; True=permeant).
- Inputs: **WLOGP** (RDKit `Chem.Crippen.MolLogP`, the t10 lens) + **TPSA** (RDKit `CalcTPSA`).
- Mechanism: **point-in-polygon** in **(x = TPSA, y = WLOGP)** space - white = HIA (extends to TPSA ≈ 142),
  yolk = BBB (inner, more restrictive). Embed the `pyBOILEDegg` vertex lists (`gia_coords`, `bbb_coords`)
  or reconstruct the Daina & Zoete analytic ellipses; either gives the two booleans.
- `endpoint_values = {"HIA_boiled_egg": <bool>, "BBB_boiled_egg": <bool>}`; `raw = {"WLOGP":…, "TPSA":…}`.
- **Register on both endpoints:** `ModelSpec.endpoints = {distribution, permeability}` (already set in t04);
  this one impl feeds BBB (distribution) and HIA (permeability).

## Landmines
- **Coordinate convention: TPSA on x, WLOGP on y.** Swapping the axes silently inverts every call - assert
  it in the unit test (a known point inside the yolk must return `BBB=True`).
- Reuse the same WLOGP as t10 (RDKit Crippen `MolLogP`), not a different logP.

## Done (gate: model kind - box-solved lock + smoke ok)
- Smoke on FTO-43 returns two booleans; a unit test with a known in-yolk and an out-of-yolk point confirms
  the axis convention (no inversion).
- README: axis convention, dual-endpoint role, direction (True=permeant/absorbed). Access CODE-ALGO.

## Blocked if
- RDKit won't resolve on box after 3 attempts → BLOCK with the error.
