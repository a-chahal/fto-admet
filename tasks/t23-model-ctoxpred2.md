# t23-model-ctoxpred2 - CToxPred2 (hERG secondary; 0/1 vote + %-string)

**Kind:** model-code · **Autonomy:** review · **Runs:** author laptop; env + smoke on box
**Touch only:** `endpoints/herg/ctoxpred2/**`, `endpoints/herg/__init__.py`, `tests/test_model_ctoxpred2.py`
**Deps:** t12-gate-phase1 · **Template:** follow t11 · **in_bulk_loop = False** (secondary)

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §1 #6 (CToxPred2 - VERIFIED 16-col export + parsing gotchas).
- `CLAUDE.md` §4 (CToxPred2 landmine).

## Build
- Repo `issararab/CToxPred2`; conda/pixi env **py3.9**; **models must be decompressed under
  `CToxPred2/models`** (vendor the repo; unpack weights during install). GPU optional.
- **Headless path:** the repo ships a GUI (`app.py`) - do **not** use it. Drive prediction through the
  notebook's underlying functions (`notebooks/make_predictions.ipynb` / `notebooks/nutils.py`,
  `components/menu.py`) adapted into `run.py`. Model choice: **DNN** (MC-dropout → confidence) or RF.
- Output: three channels **hERG, NaV1.5, CaV1.2**. VERIFIED export columns (order):
  `InChI, SMILES, MW, AlogP, HBA, HBD, MPSA, ROTB, AROMS, ALERTS, hERG, hERG_confidence, Nav1.5,
  Nav1.5_confidence, Cav1.2, Cav1.2_confidence`.
- **Parsing (LANDMINE):** each channel call (`hERG`/`Nav1.5`/`Cav1.2`) is a **binary 0/1 int via argmax**
  (1 = blocker), **not** a probability. Each `*_confidence` is a **percent STRING** `"{:.1%}"`
  (e.g. `"87.3%"`) → strip `%`, ÷100 → float in [0,1].
- Emit `endpoint_values = {"hERG_vote": 0|1, "NaV1.5_vote": 0|1, "CaV1.2_vote": 0|1}` and put the parsed
  confidences into `uncertainty` (e.g. `uncertainty.confidence` for hERG; others in `extra`). The hERG gate
  (t52) consumes hERG as a **confidence-weighted VOTE, not a P(block)** in the probability average.

## Landmines
- **0/1 vote, not a probability.** Do not coerce it into the P(block) pool. Confidence is a **%-string** - parse it.
- Secondary (`in_bulk_loop=False`); NaV1.5/CaV1.2 are context, hERG feeds the gate.

## Done (gate: model kind - box-solved lock + smoke ok)
- Box smoke on FTO-43 returns three 0/1 votes + three confidences parsed from `%`-strings to floats.
- README: vote-not-probability, %-string parsing, DNN-vs-RF choice, secondary role. Access CODE-PKG.

## Blocked if
- The py3.9 env or the decompressed weights won't load on the box after 3 attempts → BLOCK with the error.
