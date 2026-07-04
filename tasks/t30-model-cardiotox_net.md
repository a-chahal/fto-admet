# t30-model-cardiotox_net - CardioTox net (hERG ensemble; legacy TF)

**Kind:** model-legacy · **Autonomy:** review · **Runs:** author laptop; env + smoke on box
**Touch only:** `endpoints/herg/cardiotox_net/**`, `tests/test_model_cardiotox_net.py`
**Deps:** t12-gate-phase1 · **Template:** follow t11 · **LEGACY - health-check the env FIRST**

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §1 #5 (CardioTox net - VERIFIED bare-array output + applicability limit).
- `docs/FTO_ADMET_Model_Provenance_VERIFIED.md` §B#5 (py3.7.7 + old TF; repo exists).
- `CLAUDE.md` §4 (CardioTox landmine).

## Health-check FIRST
Stack is **Python 3.7.7 + old TensorFlow** (repo `Abdulk084/CardioTox` - it **exists**; an earlier "404" was
a rate-limited API query). Clean API offsets the age, but pin the TF version explicitly. Prove the env
resolves on the box before building the adapter; **BLOCK** after 3 attempts with the exact error.

## Build
- `import cardiotox; m = cardiotox.load_ensemble(); m.predict(smiles, probabilities=False)`.
- Output (VERIFIED): a **bare NumPy array of hERG-blocker probabilities in (0,1)**, one per input SMILES
  (**↑ = more likely blocker**). **No named field - align POSITIONALLY to the input list.** With
  `probabilities=True` → two columns `[P(non-blocker), P(blocker)]` → take **column 1**.
- Map → `endpoint_values["P_block"]` (identity; feeds the gate core average). `uncertainty = None` (native
  uncertainty is INDIRECT = ensemble-vs-ensemble agreement, computed at t52).
- **Applicability limit (flag, don't drop):** only valid for SMILES with **Morgan-fingerprint on-bits ≤ 93**.
  Compute the on-bit count; if a molecule exceeds it, set a flag in `raw`/`uncertainty.extra` so the gate can
  down-weight rather than trust it.

## Landmines
- **Bare array, positional alignment** - a misalignment silently mislabels molecules. Assert length + order
  in the smoke test.
- **Morgan on-bits ≤ 93** applicability limit - flag out-of-range molecules.
- Legacy TF: isolate.

## Done (gate: model kind - box-solved lock + smoke ok)
- Box smoke on FTO-43 returns a P(block) aligned to the input; the on-bit applicability flag is computed;
  lock box-solved.
- README: bare-array/positional note, Morgan ≤93 limit, direction, TF pin. Access CODE-PKG.

## Blocked if
- The py3.7.7 + old-TF env won't resolve on the box after 3 attempts → BLOCK with the exact error.
