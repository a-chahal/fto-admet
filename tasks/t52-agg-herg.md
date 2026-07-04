# t52-agg-herg - hERG gate (MATH DEFERRED - scaffold + marker ONLY)

**Kind:** aggregator-deferred · **Autonomy:** human · **Runs:** laptop, core env
**Touch only:** `endpoints/herg/aggregate.py`, `endpoints/herg/test_aggregate.py`
**Deps:** t29-model-bayesherg, t30-model-cardiotox_net, t23-model-ctoxpred2, t24-model-cardiogenai, t21-model-admet_ai

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §2 (hERG map) + §3 F-1.
- `CLAUDE.md` §4a (**hERG gate math is DEFERRED - do NOT invent weights/thresholds**).

## Build - SCAFFOLD ONLY (this is the deferred decision)
The gate is the primary go/no-go, and its **harmonize-then-weight-toward-sensitivity math is a DEFERRED
decision** (thresholds, the weighting function, what counts as "split", the pIC50→P(block) mapping F-1). You
**must not invent it.** Build only the scaffold:
1. A harmonization layer that maps each contributing read to the **common P(block) shape** without deciding
   weights: BayeshERG `score` (identity) + `alea`/`epis`; CardioTox net array (identity); ADMET-AI `hERG`
   (identity); **CToxPred2 as a 0/1 confidence-weighted VOTE, not a probability**; CardioGenAI `"hERG pIC50"`
   (carry as pIC50 - the pIC50→P mapping is F-1, DEFERRED).
2. A clearly-marked `aggregate()` that assembles these into an `EndpointResult` **and raises / returns a
   `DEFERRED` sentinel** for the actual go/no-go decision. The file **must contain an explicit `DEFERRED`
   marker** (docstring + a `raise NotImplementedError("hERG gate math DEFERRED - see CLAUDE.md §4a")` or a
   `status="DEFERRED"` return) so the gate can verify it.
3. `test_aggregate.py` asserts the **harmonization shape** is correct (each read mapped to the common shape;
   CToxPred2 stays a vote) and that the decision path returns/raises DEFERRED - **not** a fabricated verdict.

## Landmines
- **No weights, no thresholds, no pIC50→P mapping.** Any of those is inventing the deferred decision - refuse.
- CToxPred2 is a **vote**, never averaged into the probability pool.

## Done (gate: aggregator-deferred - status=needs_aaran + `aggregate.py` contains `DEFERRED`)
- `aggregate.py` harmonizes the reads to the common shape and explicitly marks the decision DEFERRED;
  `test_aggregate.py` green on the shape + DEFERRED behavior. `.result.json` status = `needs_aaran`.

## Blocked if
- N/A - this is a deliberate deferral. If harmonization can't be scaffolded from the schemas → BLOCK with the
  gap (should not happen; all contributing schemas exist).
