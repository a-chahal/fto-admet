# t38-sop-watanabe_pgp_brain - Watanabe P-gp brain via DruMAP (WEB-ONLY SOP)

**Kind:** sop · **Autonomy:** high (README only) · **Runs:** author laptop; web run is manual (shortlist)
**Touch only:** `endpoints/distribution/watanabe_pgp_brain/**` (README only - no code, no env)
**Deps:** t12-gate-phase1

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §1 #17 + §3 F-14.

## Build - `README.md` with these exact section headers (the gate checks them)
- **URL** - `https://drumap.nibiohn.go.jp/prediction` (DruMAP).
- **INPUTS** - SMILES; organism = human. **Run in the SAME DruMAP session as t37** (batch all DruMAP
  endpoints once - F-14).
- **SELECT** - the brain-P-gp / CNS endpoints.
- **OUTPUT FIELDS** (transcribe in this fixed shape):
  - `pgp_brain_efflux` - NER class (net efflux ratio class, e.g. "Low"); ↑ efflux = ↓ brain penetration.
  - `Kp_uu_brain` - unbound brain-to-plasma ratio (rat); ↑ = more brain penetration (≥ 0.5 ≈ penetrant).
  - `fu_brain` - fraction unbound in brain homogenate; ↑ = more free in CNS.
- **LEDGER TRANSCRIPTION SHAPE** - JSON record (model=`watanabe_pgp_brain`, the three fields, timestamp,
  source=DruMAP, `run_by`), matching `core.ledger`.

## Notes
- Passive/efflux score only; the real CNS answer is experimental **Kp,uu**. BBB is desirable, not a gate.
- Web-only, shortlist/manual; never in the bulk loop.

## Done (gate: sop kind - README has URL / INPUTS / OUTPUT FIELDS / LEDGER sections)
- README complete with the sections above and the shared-DruMAP-session note (with t37).

## Blocked if
- N/A (documentation task).
