# t27-model-swissadme - SwissADME lipophilicity (reconstructed in code)

**Kind:** model-code · **Autonomy:** review · **Runs:** author laptop; env + smoke on box
**Touch only:** `endpoints/lipophilicity/swissadme/**`, `tests/test_model_swissadme.py`
**Deps:** t12-gate-phase1 · **Template:** follow t11 (endpoints/lipophilicity/__init__.py made by t10)

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §1 #22 (SwissADME lipophilicity block; reproducible vs proprietary).

## Build
- SwissADME is **web-only (no API)** but its lipophilicity role is **reconstructible in code**. Build the
  in-code consensus; do **not** call the website in the bulk loop.
- Five lenses; reproduce the three that are open, drop the two proprietary:
  - `WLOGP` - **= RDKit Crippen `MolLogP`** (reuse the t10 lens).
  - `MLOGP` - Moriguchi formula (implement).
  - `XLOGP3` - external CLI (v3.2.2). **If the XLOGP3 binary is obtainable on the box, use it (3-lens);
    if not, fall back to WLOGP+MLOGP (2-lens) and record the reduction in the README** - do not fabricate an
    XLOGP3 value.
  - `iLOGP`, `Silicos-IT` - **not reproducible** (proprietary / defunct); omit.
- `Consensus_logP` = mean of the reproduced lenses. Optionally include OPERA logD later as a 4th input.
- Emit `endpoint_values = {"WLOGP":…, "MLOGP":…, "XLOGP3":… (if available), "Consensus_logP":…}`;
  **spread across lenses → `uncertainty`** (INDIRECT; convergence = trust, scatter = lean on measured logD ≈ 1).

## Landmines
- These are **logP** lenses, not logD (F-12) - for the di-basic FTO series compare logD-to-logD downstream;
  note it. Do not silently apply a pKa here.
- Do not hit the SwissADME website in the bulk loop (web only if the exact 5-way consensus is ever needed on
  the shortlist).

## Done (gate: model kind - box-solved lock + smoke ok)
- Box smoke on FTO-43 returns the reproduced lenses + consensus + a spread-based `uncertainty`; if XLOGP3 is
  unavailable, it's a clean 2-lens result with the README noting the reduction.
- README: 3-lens (or 2-lens) reconstruction, lost proprietary methods, spread=flag, F-12 note. Access WEB-SUBSTITUTABLE.

## Blocked if
- RDKit won't resolve on the box after 3 attempts → BLOCK. (Missing XLOGP3 is **not** a block - degrade to
  2-lens and note it.)
