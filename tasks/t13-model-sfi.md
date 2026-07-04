# t13-model-sfi - Solubility Forecast Index (rule)

**Kind:** model-rule · **Autonomy:** review · **Runs:** author laptop; env + smoke on box
**Touch only:** `endpoints/solubility/sfi/**`, `endpoints/solubility/__init__.py`, `tests/test_model_sfi.py`
**Deps:** t12-gate-phase1 · **Template:** follow t10 (folder, uniform CLI, box-solved lock, schema-shaped JSON)

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §19 (SFI) + §3 F-12/F-13 (logD vs logP; single pKa source).
- `CLAUDE.md` §4a (F-13 pKa source is DEFERRED - inject a placeholder, do not decide).

## Build
- Formula: **`SFI = cLogD(7.4) + (#aromatic rings)`** → single float. **LOWER = better (more soluble).**
- `#aromatic rings` = `rdkit.Chem.rdMolDescriptors.CalcNumAromaticRings`.
- `cLogD(7.4)`: compute from Crippen cLogP (the t10 WLOGP lens) + a **pKa via Henderson-Hasselbalch**
  (for a base: `cLogD = cLogP - log10(1 + 10^(pKa - 7.4))`). The **pKa source is injectable** with a
  documented placeholder (F-13) - do **not** hard-depend on OPERA (t33); leave a TODO to swap the real
  source when F-13 is decided. Anchor sanity: measured series logD ≈ 1.
- `endpoint_values = {"SFI": <float>, "cLogD_7.4": <float>, "n_aromatic_rings": <int>}`; `uncertainty=None`.

## Landmines
- **LOWER = better** - this inverts vs generalist solubility (higher logS = better). The t41 aggregator
  reconciles it; here just emit SFI faithfully and state the direction in the README.
- Uses **cLogD, not cLogP** (F-12). Do not skip the pKa correction.
- pKa is a **placeholder** pending F-13 - flag it; don't silently pick a value as if decided.

## Done (gate: model kind - box-solved lock + smoke ok)
- Folder complete per t10; smoke on FTO-43 returns finite `SFI` + `cLogD_7.4` + integer ring count.
- README states LOWER=better, the F-12/F-13 caveats, and the placeholder pKa source. Access CODE-ALGO.

## Blocked if
- RDKit won't resolve on box after 3 attempts → BLOCK with the solver error.
