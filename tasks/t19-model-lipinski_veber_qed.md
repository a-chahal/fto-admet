# t19-model-lipinski_veber_qed - drug-likeness context (rule; POINTER)

**Kind:** model-rule · **Autonomy:** high · **Runs:** author laptop; env + smoke on box
**Touch only:** `endpoints/druglikeness/lipinski_veber_qed/**`, `endpoints/druglikeness/__init__.py`, `tests/test_model_lipinski_veber_qed.py`
**Deps:** t12-gate-phase1 · **Template:** follow t10

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §30 (Lipinski / Veber / QED).

## Build
- RDKit only: `Descriptors`/`Lipinski` (MW, HBD, HBA, RotB, TPSA, MolLogP) + `rdkit.Chem.QED.qed(mol)`.
- Output:
  - `Lipinski_violations` (int 0-4; MW≤500, HBD≤5, HBA≤10, logP≤5; **fewer = more drug-like**),
  - `Veber_pass` (bool; RotB ≤10 **and** TPSA ≤140),
  - `QED` (float 0-1; **↑ = more drug-like**).
- `endpoint_values = {"Lipinski_violations": int, "Veber_pass": bool, "QED": float}`.

## Landmines
- **Context / POINTER only - not a gate.** Run for the lab's sanity check; the aggregator (t50) reports
  these as flags, never a kill. Note in README.

## Done (gate: model kind - box-solved lock + smoke ok)
- Smoke on FTO-43 returns the three fields with correct types/ranges.
- README: POINTER framing, directions. Access CODE-PKG.

## Blocked if
- RDKit won't resolve on box after 3 attempts → BLOCK with the error.
