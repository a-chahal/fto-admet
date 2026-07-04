# t09-gate-core - lock the `core` contract before the model swarm

**Kind:** gate · **Autonomy:** review · **Runs:** laptop, core env, no GPU
**Touch only:** `tests/test_integration.py`, `tests/conftest.py` (fixtures), `README.md` (core usage) - **not** `core/` modules
**Deps:** t01-t08 (all core)

## Read first
- `CLAUDE.md` §2 (the whole contract), §5 (gate = independent verification).
- `docs/FTO_ADMET_Codebase_And_Environment_SETTLED.md` §8 (testing: fast tier vs `@pytest.mark.model`).

## Why this task
This is the checkpoint that **freezes the `core` API** before ~40 model/aggregator tasks build against it.
A wrong schema or registry gap caught here costs one fix; caught later it poisons every downstream smoke
test. This task adds the cross-cutting integration tests and confirms the whole non-model suite is green.
It does **not** modify `core/` - if an integration test reveals a bug, report it (BLOCK with the failing
test) so the owning core task is revisited; do not patch `core` from the gate.

## Build
1. **`tests/conftest.py`** - the canonical **FTO-43 fixture** (`smiles`, `mol_id`) reused everywhere; a
   `tests/fixtures/fto43.smi` file; tmp-dir fixtures for ledger/outputs. Mark the two test tiers:
   fast unit tests (default) vs `@pytest.mark.model` (opt-in, shells into model envs - registered here so
   `-m "not model"` works).
2. **`tests/test_integration.py`** - contract coherence across `models`/`schemas`/`registry`/`dispatch`/`run`:
   - every `ModelName` has exactly one `ModelSpec`; every spec `endpoints ⊆ Endpoint`, non-empty.
   - the 5 cross-cutting endpoint sets (admet_ai, admetlab3, boiled_egg, opera, pgp) are present.
   - every non-web / non-out-of-band model has an `env_manifest` **and** `entrypoint` path;
     web-only + OPERA + PBPK have `None`.
   - `input_schema`/`output_schema` instantiate; `run_endpoint` enumerates the right models per endpoint
     (mocked dispatch); `pip install -e .` makes `core` importable.
3. **`README.md`** - short human onboarding: setup (`.env`, `pixi install`, `pip install -e .`), the two
   test tiers, and the `python -m core.run` entry.

## Done (gate: `pixi run pytest tests/ -m "not model" -q` green)
- The full non-model suite passes, including `test_integration.py`.
- `import core` works after `pip install -e .`; `registry_validate()` is green.
- `conftest.py` exposes the FTO-43 fixture and registers the `model` marker.

## Blocked if
- Any core module test fails → BLOCK with the exact failing test named (the owning t01-t08 task must fix
  it). Do not edit `core/` here.
