# t44-agg-distribution - passive penetration flag SEPARATE from efflux flag

**Kind:** aggregator · **Autonomy:** review · **Runs:** laptop, core env
**Touch only:** `endpoints/distribution/aggregate.py`, `endpoints/distribution/test_aggregate.py`
**Deps:** t14-model-bbb_score, t15-model-cns_mpo, t16-model-boiled_egg, t28-model-pgp, t38-sop-watanabe_pgp_brain

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §2 (distribution map) + §3 F-4.
- `CLAUDE.md` §4 (incompatible scales).

## Build - two independent flags
- **Passive penetration:** BBB Score (0-6), CNS MPO (0-6), ADMET-AI `BBB_Martins` (probability),
  BOILED-Egg `BBB_boiled_egg` (bool). **Map each to penetrant / borderline / non and VOTE** - do not average.
- **Efflux:** ADMET-AI `Pgp_Broccatelli` (probability, via the t28 derived pgp helper), Watanabe P-gp
  `NER.class` [t38 SOP], `Kp_uu_brain` [t38 SOP].
- Emit the two flags **separately**; note the real answer is experimental **Kp,uu**. Triage only (BBB is
  desirable, not a gate).

## Landmines (F-4)
- **Incompatible scales** (0-6 desirability vs probability vs bool) - **map each to a flag and vote; never
  average across scales.**
- Keep passive and efflux **separate** - they answer different questions.

## Done (gate: `pixi run pytest endpoints/distribution/test_aggregate.py -q` green)
- Synthetic records on mixed scales → each maps to penetrant/borderline/non and the vote resolves correctly;
  passive and efflux flags come out as separate fields; no cross-scale averaging.

## Blocked if
- Laptop-only; should not block. Record any error and BLOCK.
