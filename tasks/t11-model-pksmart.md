# t11-model-pksmart - first real isolated env (proves subprocess + box lock + uncertainty)

**Kind:** model-code · **Autonomy:** review · **Runs:** author on laptop; env + smoke on the box
**Touch only:** `endpoints/clearance/pksmart/**`, `endpoints/clearance/__init__.py`,
`tests/test_model_pksmart.py`
**Deps:** t10-model-rdkit_crippen

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §11 (PKSmart I/O - verified column names, units, fold-error).
- `docs/FTO_ADMET_Model_Provenance_VERIFIED.md` §B#12 (PKSmart deps: `mordredcommunity`, sklearn pins).
- `CLAUDE.md` §0 (lock-on-box), §3 (uncertainty envelope), §4 (never combine clearance units downstream).

## Why this task is special
It is the **first real isolated env** and the second template: it proves the subprocess dispatch pattern,
the box lockfile round-trip on a real package with real transitive deps, **and** the reserved uncertainty
fields (PKSmart emits a fold-error). Deliberately chosen before the legacy CUDA envs because its stack is
modern and low-risk - prove the machinery on something that won't fight you. Follow the **t10 folder/adapter
template**; this task adds a genuine env + uncertainty population.

## Build
1. `pixi.toml`: `python >=3.10,<3.12`, `pksmart` (`pip install pksmart`, PyPI v3.0.1), and its deps - 
   **`mordredcommunity` NOT upstream `mordred`** (upstream is unmaintained on modern Python), `rdkit`,
   and **sklearn pinned to the versions that load the shipped pickles** (read the pin at build time; a
   wrong sklearn silently fails to unpickle the model). `pixi install` **on the box**; commit `pixi.lock`.
2. `run.py` (uniform CLI): for each SMILES → `import pksmart; pksmart.predict_pk_params(smiles)` (or CLI
   `pksmart -f <file>`). Map the **verified** human columns into `endpoint_values` with units baked in:
   - `human_CL_mL_min_kg` → `CL_mL_min_kg` (**↑ = faster clearance**; the FTO liability, anchor ≈ 89.6)
   - `human_VDss_L_kg` → `VDss_L_kg`; `human_thalf` → `t_half_h`; `human_fup` → `fu`; `human_MRT` → `MRT_h`.
3. **Fold-error → `Uncertainty`.** PKSmart documents a per-parameter fold-error/prediction interval, but its
   field name was not in the example CSVs - **read it from the installed package at build time**. If present,
   populate `uncertainty.fold_error_low`/`fold_error_high` for CL; if genuinely absent, set `uncertainty=None`
   and record in the README that the interval field was not exposed (do **not** fabricate one).
4. `tests/test_model_pksmart.py` (`@pytest.mark.model`): on the box, run FTO-43 → assert the five human
   params are finite with correct units; if fold-error present, assert it populates `Uncertainty`.
5. `README.md`: PyPI v3.0.1; citation *J. Cheminform.* 2025 (10.1186/s13321-025-01066-5). **Weak-CL
   caveat:** R²=0.31, GMFE ≈2.43 → **coarse binning + within-series ranking only; surface the fold-error,
   never the bare CL number.** Direction/units per field; access CODE-PKG.

## Landmines
- **`mordredcommunity`, not `mordred`.** Pin sklearn to the pickle versions. A wrong pin = silent unpickle
  failure.
- **Lock solved on the box** (`CLAUDE.md` §0). `run.py` cannot import `core` - emit schema-shaped JSON.
- CL is ranking-only; the aggregator (t43) must **never** combine PKSmart CL with the other clearance
  units (F-3) - but that's t43's job; here just emit CL + its fold-error faithfully.

## Done (gate: model kind - folder complete, lock box-solved, smoke ok)
- Folder complete; `pixi.lock` box-solved (linux-64 + hashes) and contains `mordredcommunity` + a pinned
  sklearn.
- Box smoke on FTO-43 returns the five human params with correct units; `.result.json` `smoke.ok=true`.
- Fold-error either populates `Uncertainty` **or** is documented absent in the README (no fabrication).

## Blocked if
- The shipped model pickles won't load under any resolvable sklearn pin, or `pksmart`/`mordredcommunity`
  won't co-resolve on the box, after 3 attempts → BLOCK with the exact error. This is the first genuine
  env-resolution test; a clean BLOCK here is a real signal.
