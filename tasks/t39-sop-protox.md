# t39-sop-protox - ProTox 3.0 (WEB-ONLY SOP; shortlist confirmatory)

**Kind:** sop · **Autonomy:** high (README only) · **Runs:** author laptop; web run is manual (shortlist)
**Touch only:** `endpoints/toxicity/protox/**` (README only - no code, no env)
**Deps:** t12-gate-phase1

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §1 #29 + §3 F-15.
- `docs/FTO_ADMET_Model_Provenance_VERIFIED.md` §B#31.

## Build - `README.md` with these exact section headers (the gate checks them)
- **URL** - `https://tox.charite.de` (form-based; no API/package).
- **INPUTS** - shortlist SMILES (or draw).
- **SELECT** - **"ALL models"** (the default is acute tox + targets only - you must select ALL to get the
  organ / AOP / off-target panel).
- **OUTPUT FIELDS** (transcribe in this fixed shape):
  - `LD50` (mg/kg; **LOWER = more toxic**), `tox_class` (1-6; **1 = most toxic**), `prediction_accuracy` (%),
  - per-endpoint `Active`/`Inactive` + probability (organ: hepato/neuro/nephro/cardio/**respiratory**;
    carcinogenicity, mutagenicity, cytotoxicity, immunotoxicity, BBB, clinical, **ecotox**, **nutritional**;
    12 Tox21 pathways; **14 MIE targets**; **15 tox off-targets**; **6 metabolism targets**),
  - toxicity targets (name + fit + similarity).
- **LEDGER TRANSCRIPTION SHAPE** - JSON record (model=`protox`, the fields above, timestamp, source=ProTox 3.0,
  `run_by`), matching `core.ledger`.

## Notes
- **No automatable substitute** for: respiratory tox, ecotox, nutritional tox, the 15 off-targets, the 14 MIE
  targets, most of the 6 metabolism targets - ProTox-web is the **only** source; note this prominently.
- **`LD50` (mg/kg) is NOT comparable to ADMET-AI `LD50_Zhu` (log(1/(mol/kg)))** - F-5. Keep them as separate
  reads (this = shortlist confirmatory; ADMET-AI = bulk triage).
- Web-only, shortlist confirmatory; bulk is substituted via ADMET-AI + ADMETlab (coverage, not equivalence).

## Done (gate: sop kind - README has URL / INPUTS / OUTPUT FIELDS / LEDGER sections)
- README complete with the sections above, the "select ALL models" instruction, the no-substitute list, and
  the LD50 non-comparability note.

## Blocked if
- N/A (documentation task).
