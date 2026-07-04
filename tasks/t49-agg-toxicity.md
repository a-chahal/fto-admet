# t49-agg-toxicity - bulk-substitute panel + ProTox confirmatory (kept separate)

**Kind:** aggregator · **Autonomy:** review · **Runs:** laptop, core env
**Touch only:** `endpoints/toxicity/aggregate.py`, `endpoints/toxicity/test_aggregate.py`
**Deps:** t21-model-admet_ai, t35-model-admetlab3, t18-model-toxicophores, t39-sop-protox

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §2 (toxicity map) + §3 F-5.

## Build - two tiers, kept separate
- **Bulk (automatable):** ADMET-AI `LD50_Zhu`, `DILI`, `hERG`, `AMES`, `Carcinogens_Lagunin`, `ClinTox`,
  `Skin_Reaction` + ADMETlab organ-tox heads (nephro/neuro/cyto/immuno/genotox) + toxicophores alerts →
  per-endpoint P(toxic).
- **Shortlist (confirmatory):** ProTox [t39 SOP ledger] LD50 (mg/kg), class (1-6), Active/Inactive + prob.
- Emit the bulk panel and the shortlist read as **separate blocks**.

## Landmines (F-5)
- **`LD50_Zhu` (log(1/(mol/kg)), ↑ = more toxic) is NOT comparable to ProTox `LD50` (mg/kg, LOWER = more
  toxic).** **Keep them as separate reads** - never merge or convert one into the other. Different scales AND
  opposite directions.
- Bulk is a coverage/throughput substitute, not a quality-equivalence claim; the off-target/MIE/respiratory/
  eco/nutritional ProTox endpoints have no automatable counterpart (shortlist only).

## Done (gate: `pixi run pytest endpoints/toxicity/test_aggregate.py -q` green)
- Synthetic records → the bulk per-endpoint P(toxic) panel and the ProTox shortlist block are produced
  separately; there is **no path that combines `LD50_Zhu` with ProTox LD50** (assert they stay distinct).

## Blocked if
- Laptop-only; should not block. Record any error and BLOCK.
