# t37-sop-watanabe_renal - Watanabe renal fe/CLr via DruMAP (WEB-ONLY SOP)

**Kind:** sop · **Autonomy:** high (README only) · **Runs:** author laptop; the web run is manual (shortlist)
**Touch only:** `endpoints/clearance/watanabe_renal/**` (README only - no code, no env)
**Deps:** t12-gate-phase1

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §1 #10 + §3 F-14 (DruMAP one-session batching).

## Build - `README.md` with these exact section headers (the gate checks them)
- **URL** - `https://drumap.nibiohn.go.jp/prediction` (DruMAP web app; no API/download).
- **INPUTS** - SMILES; select **organism = human**.
- **SELECT** - the renal endpoints (fe, CLr) - and note this is run in **ONE DruMAP session batched with
  t38** (P-gp brain) plus CLint / Fa / fu,brain / Kp,uu,brain (F-14) - capture them all together.
- **OUTPUT FIELDS** (transcribe in this fixed shape):
  - `fe` - fraction excreted unchanged in urine (binary classifier); ↑ = more renal (unchanged) route.
  - `CLr` - renal clearance (mL/min/kg - **confirm the unit on the live page**); ↑ = faster renal clearance.
  - `fu_p` - fraction unbound in plasma (0-1); ↑ = more free drug.
- **LEDGER TRANSCRIPTION SHAPE** - the JSON record shape to hand-enter into the ledger (model=`watanabe_renal`,
  the three fields with units, timestamp, source=DruMAP, `run_by`), matching `core.ledger`.

## Notes
- **Web-only, shortlist/manual - never in the bulk loop** (`in_bulk_loop=False`, `env_manifest=None`).
- The renal-vs-hepatic fork is resolved by experiment, not this model - triage read only.

## Done (gate: sop kind - README has URL / INPUTS / OUTPUT FIELDS / LEDGER sections)
- README complete with the sections above, the fixed output shape, and the one-session-with-t38 note.

## Blocked if
- N/A (documentation task). If the DruMAP URL/flow has changed, note it in the README and still deliver.
