# t24-model-cardiogenai - CardioGenAI (discriminative hERG; generative GATED)

**Kind:** model-code · **Autonomy:** review · **Runs:** author laptop; env + smoke on box
**Touch only:** `endpoints/herg/cardiogenai/**`, `tests/test_model_cardiogenai.py`
**Deps:** t12-gate-phase1 · **Template:** follow t11 · **in_bulk_loop = False** · GPU yes

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §1 #7 (CardioGenAI - two entry points, VERIFIED keys) + §3 F-1.
- `CLAUDE.md` §4 (CardioGenAI landmine; generative gated on Kunhuan).

## Build - two paths, only one is fully built now
1. **Discriminative (BUILD):** `predict_cardiac_ion_channel_activity(input_data, prediction_type,
   predict_hERG, predict_Nav, predict_Cav, device)`. Regression → **pIC50** per channel; classification →
   class (non-blocker cutoff **pIC50 ≥ 5.0**). **VERIFIED keys contain a literal space:** `"hERG pIC50"`,
   `"NaV1.5 pIC50"`, `"CaV1.2 pIC50"` - quote them **exactly**. Emit
   `endpoint_values = {"hERG pIC50": <float>, "NaV1.5 pIC50": <float>, "CaV1.2 pIC50": <float>}`
   (direction: pIC50 ↑ = stronger blocker = ↑tox).
   **Do NOT map pIC50 → P(block) here** - that mapping is F-1 and lives in the DEFERRED hERG gate math (t52).
2. **Generative (SCAFFOLD ONLY):** `optimize_cardiotoxic_drug(...)` → candidate SMILES. Its output is
   **GATED** on Kunhuan's FTO-binding + FTO-vs-ALKBH5 selectivity, and that cross-arm interface **does not
   exist yet**. Build a stub `run.py --mode generative` that refuses with a clear
   `GATED: needs Kunhuan binding/selectivity interface (not built)` message + a TODO. Do not wire it live.

- Repo `gregory-kyro/CardioGenAI`; `pixi install` on box; commit lock. GPU yes (honor `--gpu`).

## Landmines
- **Keys have spaces** - `"hERG pIC50"` etc. A key without the space silently misses.
- **pIC50 → P(block) is DEFERRED (F-1)** - emit pIC50, do not convert.
- **Generative output is GATED** on Kunhuan - scaffold only; never emit generative candidates as usable.

## Done (gate: model kind - box-solved lock + smoke ok)
- Box smoke on FTO-43 (discriminative) returns the three space-keyed pIC50 values.
- The generative mode stub refuses cleanly with the GATED message; README documents both paths, the F-1
  deferral, and the Kunhuan gating. Access CODE-PKG.

## Blocked if
- The env won't resolve on the box (GPU/torch) after 3 attempts → BLOCK with the error.
