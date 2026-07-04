# t00b-core-env - create and install the root/core environment

**Kind:** core · **Autonomy:** high · **Runs:** laptop (this env is where `core`, aggregators, and the fast test tier live)
**Touch only:** `pixi.toml`, `pyproject.toml`, `tests/test_env.py`, `.gitignore`
**Deps:** t00-bootstrap-box

## Why this task exists
Every core/aggregator/gate runs `pixi run pytest …` in the **root/core env**. That env must exist before
`t01` can be gated. This task creates + installs it. It is the **one exception** to the lock-on-box rule
(`CLAUDE.md` §0.1): the core env has no CUDA/model deps, so it is **cross-platform** and solved once for both
laptop and box.

## Read first
- `docs/FTO_ADMET_Codebase_And_Environment_SETTLED.md` §3/§8 (core package + test tiers).
- `CLAUDE.md` §0.1 (core-env exception), §2 (what `core` is).

## Build
1. `pixi.toml` + `pyproject.toml` may already be present in the repo (pre-generated). **Verify** them:
   - `pixi.toml`: channel conda-forge; `platforms = ["osx-arm64", "linux-64"]` (**switch the mac entry to
     `osx-64` if the laptop is Intel**); deps python 3.11, rdkit, pytest, pydantic≥2, pandas, pyyaml,
     python-dotenv; `[pypi-dependencies] fto-admet-core = { path = ".", editable = true }`.
   - `pyproject.toml`: package `fto-admet-core`, `packages = ["core"]`, the `model` pytest marker registered.
   - If they're absent, create them to that spec.
2. Create a minimal `core/__init__.py` if needed so the editable install has a package to point at (later
   core tasks fill it in).
3. **On the laptop:** `pixi install` (solves **both** platforms into one `pixi.lock`), then confirm the
   editable core install resolves. Commit `pixi.toml`, `pyproject.toml`, `pixi.lock`.
4. Ensure `tests/test_env.py` exists (toolchain smoke: imports pytest/pydantic/pandas/yaml + rdkit).

## Landmines
- **Core-env lock is multi-platform, laptop-solved - this is the ONLY env that isn't box-solved.** Do not
  apply the per-model "solve on box" rule here; do commit the multi-platform lock so the box reuses it on pull.
- Set the correct mac platform for the actual laptop (`osx-arm64` vs `osx-64`).

## Done (gate: `pixi run pytest tests/test_env.py -q` green)
- `pixi install` succeeds; the multi-platform `pixi.lock` is committed; `pixi run pytest tests/test_env.py`
  passes (toolchain + rdkit import OK); `import core` works under the env.

## Blocked if
- `pixi install` cannot resolve the core toolchain for both platforms after 3 attempts → BLOCK with the exact
  solver error (e.g. an rdkit/python pin conflict on one platform - drop that platform or adjust the pin).
