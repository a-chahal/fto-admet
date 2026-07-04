# t25-model-smartcyp - SMARTCyp 3.0 (site of metabolism; Python/RDKit, NO JVM)

**Kind:** model-code · **Autonomy:** review · **Runs:** author laptop; env + smoke on box
**Touch only:** `endpoints/metabolism/smartcyp/**`, `endpoints/metabolism/__init__.py`, `tests/test_model_smartcyp.py`
**Deps:** t12-gate-phase1 · **Template:** follow t11

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §1 #8 (SMARTCyp - **CORRECTION block**: Python/RDKit; legacy header is a TEMPLATE).
- `docs/FTO_ADMET_Model_Provenance_VERIFIED.md` §E.8 (install path: ku.dk source or MDStudio_SMARTCyp).
- `CLAUDE.md` §4 (SMARTCyp landmine).

## Build
- **SMARTCyp 3.0 is Python 3 + RDKit - the env has NO `openjdk`.** (Only legacy 1.x/2.x were Java/CDK; the
  `cdk/smartcyp` repo is that legacy line - do **not** use it.) Install the 3.0 Python source from
  `smartcyp.sund.ku.dk` (vendor it) **or** the `MDStudio_SMARTCyp` wrapper (pip/Docker/REST) - **confirm at
  build time whether that wrapper is pure-Python** (it doesn't change that 3.0 is Python). No official PyPI.
- Output: a **per-atom ranking table** (general 3A4 model + 2D6/2C9 isoform columns). **Lower `Score` /
  `Ranking` = 1 ⇒ most likely site of metabolism.**
- **HEADER LANDMINE:** the column header in the IO spec
  (`Molecule,Atom,Ranking,Score,Energy,Relative Span,2D6ranking,2D6score,…,2DSASA`) is the **legacy Java (CDK)
  port** - a **template only**. **Re-verify the exact SMARTCyp 3.0 (Python) output header against a real run**
  and map from *that*, not the template. Do **not** hardcode the legacy header.
- Emit the **per-atom table into `raw`** (atom index + rank + score per isoform); do not force it into scalar
  `endpoint_values`. `uncertainty` = INDIRECT (agreement with generalist stability, computed at t42).
- **FTO-43 note:** the pyrrolidine tertiary amine N carries the **+N-oxidation penalty** (folded into `Score`)
  → SMARTCyp down-ranks N-oxidation there; interpret accordingly.

## Landmines
- **NO `openjdk` in the env.** If you find yourself adding a JVM, you're reading the legacy repo - stop.
- **Re-verify the 3.0 header**; the doc's header is legacy-Java template.
- Co-ranking with FAME3R is **ordinal**, never averaging `Score` with FAME3R probability (F-2) - that's t42.

## Done (gate: model kind - box-solved lock + smoke ok)
- `pixi.lock` box-solved and **contains no `openjdk`**; smoke on FTO-43 returns a per-atom SoM table with the
  **real 3.0 header** (documented in README, with a note if it differs from the legacy template).
- README: Python/RDKit (no JVM), lower=SoM direction, N-oxidation penalty note, install path used. Access CODE-PKG.

## Blocked if
- The 3.0 Python source / MDStudio wrapper won't install or run on the box after 3 attempts → BLOCK with the
  error (do **not** fall back to the legacy Java line to "make it work").
