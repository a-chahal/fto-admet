# t01-core-config - `core/config.py` (machine-path resolution)

**Kind:** core · **Autonomy:** high · **Runs:** laptop, core env, no GPU
**Touch only:** `core/config.py`, `core/__init__.py`, `tests/test_config.py`, `.env.example`
**Deps:** t00-bootstrap-box

## Read first
- `docs/FTO_ADMET_Codebase_And_Environment_SETTLED.md` §2 (storage), §3 (`core/config.py` row), §8b/§9 (`.env` → paths, collaborator-agnostic).
- `CLAUDE.md` §0 (storage discipline).

## Build
Single place that resolves all machine paths from the environment so nothing in the codebase hardcodes
`/zfs/sanjanp`. A labmate clones, sets their own `.env`, and runs unchanged.

1. Read config from environment / `.env` (support a `.env` file at repo root; do not require external
   deps beyond what's in the core env - a tiny manual parser or `python-dotenv` if already present).
2. Required var: `FTO_ADMET_ROOT` (repo root on `/zfs`). Required: `FTO_ADMET_ENV_CACHE`
   (`/zfs/sanjanp/fto-admet-envs`). Missing either → raise a clear, actionable error naming the var.
3. Expose an immutable `Config` object (frozen dataclass or a cached accessor) with resolved `Path`
   fields, at least: `root`, `env_cache`, `ledger` (`root/ledger/runs.jsonl`), `locks` (`root/.locks`),
   `outputs` (`root/outputs`), `env_cache` (from `FTO_ADMET_ENV_CACHE`). Create the dirs that the
   pipeline writes to (`ledger` parent, `locks`, `outputs`) if absent; never create anything under `$HOME`.
4. Write `.env.example` with the two required vars (documented), committed. `.env` itself is gitignored.

## Constraints
- Pure path/config logic - no model imports, no network, no subprocess.
- Deterministic: same env in → same paths out.

## Done (gate: `pixi run pytest tests/test_config.py -q` green)
- With a temp `.env` / monkeypatched env, `Config` resolves every path correctly and relative to `root`.
- Missing `FTO_ADMET_ROOT` (or `FTO_ADMET_ENV_CACHE`) raises a clear error that names the missing var.
- `.env.example` exists and lists both required vars.

## Blocked if
- Nothing external should block this (laptop-only, stdlib). If it can't run, the core env itself is
  broken → record the exact import/env error and BLOCK.
