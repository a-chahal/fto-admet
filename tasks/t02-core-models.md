# t02-core-models - `core/models.py` (`ModelName` + `Endpoint` StrEnums)

**Kind:** core · **Autonomy:** high · **Runs:** laptop, core env, no GPU
**Touch only:** `core/models.py`, `tests/test_models.py`
**Deps:** t00-bootstrap-box

## Read first
- `docs/FTO_ADMET_Codebase_And_Environment_SETTLED.md` §3 (`core/models.py`), §5 (full model×endpoint table).
- `CLAUDE.md` §2 (these enums are the primary keys of the whole system).

## Build
Two `StrEnum`s (Python 3.11+); members equal their string value; these are the primary keys used by
`registry`, `dispatch`, and every aggregator.

1. **`Endpoint(StrEnum)`** - exactly these 13 members (value = lowercase name):
   `triage, herg, metabolism, clearance, distribution, ppb, solubility, lipophilicity, permeability,
   structural_alerts, synthesizability, toxicity, druglikeness`.
2. **`ModelName(StrEnum)`** - exactly these 29 members (value = lowercase name):
   `admet_ai, admetlab3, openadmet, bayesherg, cardiotox_net, ctoxpred2, cardiogenai, smartcyp, fame3r,
   watanabe_renal, pksmart, pbpk, bbb_score, boiled_egg, cns_mpo, pgp, watanabe_pgp_brain, ochem_ppb,
   sfi, rdkit_crippen, opera, swissadme, pains_brenk, sascore, rascore, aizynthfinder, toxicophores,
   protox, lipinski_veber_qed`.
   (Permeability is aggregate-only - it has **no** `ModelName`. Do not add one.)

## Landmines
- **Do NOT add** `deephit`, `spielvogel`, `cardiodpi`, or `fame3` - dropped/replaced (`CLAUDE.md` §4).
- The count is exactly 13 endpoints and 29 model names. A wrong count means a later registry/aggregator
  mismatch.

## Done (gate: `pixi run pytest tests/test_models.py -q` green)
- Both enums import; `len(Endpoint) == 13`, `len(ModelName) == 29`; no duplicates.
- Each member's `.value` equals its lowercased name; membership checks by string work
  (`ModelName("pksmart") is ModelName.pksmart`).
- The dropped names are absent.

## Blocked if
- Laptop-only; should not block. Record any core-env import error and BLOCK.
