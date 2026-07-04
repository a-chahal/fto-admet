# t40-agg-lipophilicity - logD consensus (anchor to measured logD ≈ 1)

**Kind:** aggregator · **Autonomy:** review · **Runs:** laptop, core env (consumes collected OutputRecords)
**Touch only:** `endpoints/lipophilicity/aggregate.py`, `endpoints/lipophilicity/test_aggregate.py`
**Deps:** t10-model-rdkit_crippen, t33-model-opera, t27-model-swissadme

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §2 (lipophilicity map) + §3 F-12.
- `CLAUDE.md` §2 (aggregate() convention: `aggregate(records: list[OutputRecord]) -> EndpointResult`, core env).

## Build
- Common quantity = **logD consensus (log units), anchored to measured series logD ≈ 1.**
- Consume: RDKit Crippen `logP_crippen` (WLOGP lens; convert logP→logD via the shared pKa, or keep as a
  lens), OPERA `LogD_pred` (+ `Conf_index_LogD` → confidence), SwissADME reproduced 3-lens mean.
- **Spread across lenses = the uncertainty flag** (convergence = trust; scatter → lean on measured logD ≈ 1).
- Emit an `EndpointResult` with the consensus logD, the per-lens values, and the spread-based flag.

## Landmines (F-12)
- **logP ≠ logD** for the di-basic FTO series at pH 7.4 - **compare logD-to-logD**; do not mix a raw logP lens
  into a logD consensus without the pKa conversion. Document which lenses are logP vs logD.
- Anchor to measured logD ≈ 1; a consensus far from it should raise the flag, not be trusted.

## Done (gate: `pixi run pytest endpoints/lipophilicity/test_aggregate.py -q` green)
- With synthetic records (a tight cluster vs a scattered set), the aggregator returns the right consensus and
  a low/high spread flag respectively; logP lenses are converted before entering the logD consensus.

## Blocked if
- Laptop-only, synthetic inputs; should not block. Record any error and BLOCK.
