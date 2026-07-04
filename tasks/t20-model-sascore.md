# t20-model-sascore - synthetic accessibility (rule; RDKit Contrib, vendored)

**Kind:** model-rule · **Autonomy:** high · **Runs:** author laptop; env + smoke on box
**Touch only:** `endpoints/synthesizability/sascore/**`, `endpoints/synthesizability/__init__.py`, `tests/test_model_sascore.py`
**Deps:** t12-gate-phase1 · **Template:** follow t10 - **this is the first task that actually uses `vendor/`**

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §25 (SAscore) + `..._Provenance_VERIFIED` §B#27.

## Build
- `sascorer.calculateScore(mol)` → **float on 1-10**; **LOWER = easier to synthesize** (Ertl & Schuffenhauer 2009).
- `sascorer.py` + `fpscores.pkl.gz` are **RDKit Contrib, not core** - **vendor both** into
  `endpoints/synthesizability/sascore/vendor/` (from `$RDBASE/Contrib/SA_Score`) and add that dir to the
  path in `run.py`. Record the RDKit version the files came from in the README.
- `endpoint_values = {"SAscore": <float 1..10>}`; `uncertainty=None`.

## Landmines
- **LOWER = easier** - inverts vs "higher = better" intuition; the t48 synthesizability aggregator uses this
  as the first rung of the tier ladder (SAscore → RAscore → AiZynthFinder). State direction in README.
- The files are **vendored**, not pip-installed - this exercises the `vendor/` slot of the template.

## Done (gate: model kind - box-solved lock + smoke ok)
- `vendor/sascorer.py` + `vendor/fpscores.pkl.gz` present; smoke on FTO-43 returns a finite `SAscore` in [1,10].
- README: LOWER=easier, vendored-from RDKit-Contrib provenance + version. Access CODE-PKG (RDKit Contrib).

## Blocked if
- RDKit won't resolve on box, or the Contrib files can't be located for the pinned RDKit, after 3 attempts
  → BLOCK with the error.
