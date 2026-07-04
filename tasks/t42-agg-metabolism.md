# t42-agg-metabolism - TWO quantities, not three votes (ordinal SoM co-rank)

**Kind:** aggregator · **Autonomy:** review · **Runs:** laptop, core env
**Touch only:** `endpoints/metabolism/aggregate.py`, `endpoints/metabolism/test_aggregate.py`
**Deps:** t25-model-smartcyp, t26-model-fame3r, t21-model-admet_ai

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §2 (metabolism map) + §3 F-2.
- `CLAUDE.md` §4 (metabolism direction inversion).

## Build - two distinct quantities
1. **Stability (whole-molecule):** ADMET-AI `Clearance_Hepatocyte_AZ` / `Clearance_Microsome_AZ`
   (low-weight, µL/min/… - do NOT combine units) + ADMETlab metabolic-stability head → a CLint-like read
   (**↑ = less stable**). Qualitative only.
2. **Site of metabolism (per-atom):** SMARTCyp per-atom `Ranking`/`Score` (**lower Score = SoM**) and FAME3R
   per-atom SoM **probability** (**higher = SoM**).
- **Common SoM quantity = a per-atom ORDINAL soft-spot ranking aligned on atom index** - rank each model's
  atoms, then compare the top atoms. **Confidence = agreement between the generalist stability read and the
  SoM finding.**

## Landmines (F-2)
- **Opposite directions:** SMARTCyp Score lower = SoM; FAME3R prob higher = SoM. **Co-rank ORDINALLY per
  atom - never average the raw Score with the probability** (different scales, inverted). Align on RDKit atom
  index (FAME3R's indices attached in t26; SMARTCyp's from its table).
- Two questions, not three votes: stability answers *is it stable*; SoM answers *where the soft spot is*.
- FTO-43: SMARTCyp down-ranks N-oxidation on the pyrrolidine N (penalty) - reflect, don't "correct".

## Done (gate: `pixi run pytest endpoints/metabolism/test_aggregate.py -q` green)
- Synthetic SMARTCyp (low Score on atom k) + FAME3R (high prob on atom k) → the aggregator's ordinal
  co-rank puts atom k top for both (no averaging of raw values); disagreement raises the confidence flag.

## Blocked if
- Laptop-only; should not block. Record any error and BLOCK.
