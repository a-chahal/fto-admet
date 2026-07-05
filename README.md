# FTO-ADMET

ADMET / DMPK screening pipeline for the Gilson lab x Rana lab pediatric CNS tumor FTO-inhibitor
program (lead **FTO-43**, PubChem CID 164886650). `core` is a thin, model-agnostic layer: a curated
**registry** of models, a **dispatcher** that runs each one in its own isolated env, and an endpoint
**runner** that enumerates the models for an endpoint and hands their outputs to an aggregator. Every
model adapter hides its upstream mess behind one uniform CLI (`run.py --input <path> --output <path>
[--gpu N]`); `core` never imports a model, it shells out.

The full design is in `docs/` and the standing build rules are in `CLAUDE.md`.

## Setup

1. **Machine paths.** Copy the template and set your two `/zfs` paths (nothing project-related lives in
   `$HOME`; see `CLAUDE.md` §0):

   ```bash
   cp .env.example .env
   # edit FTO_ADMET_ROOT and FTO_ADMET_ENV_CACHE
   ```

   `FTO_ADMET_ROOT` holds code + run ledger + outputs; `FTO_ADMET_ENV_CACHE` holds envs + caches +
   weights. Everything else derives from `FTO_ADMET_ROOT` (`core/config.py`).

2. **Core env (pixi).** The root/core env has no CUDA/model deps, so it solves cross-platform:

   ```bash
   pixi install
   ```

3. **Make `core` importable.** Install the package in editable mode (also runs inside the pixi env):

   ```bash
   pip install -e .
   ```

   After this, `import core` works and `python -c "from core.registry import registry_validate;
   registry_validate()"` exits clean.

Per-model envs are **not** installed here: each is one pixi env of its own, solved on the box
(Rosenbluth, Linux + CUDA) and driven over SSH. Never synthesize a per-model lockfile locally
(`CLAUDE.md` §0).

## Running an endpoint

`python -m core.run` enumerates an endpoint's bulk-loop models, dispatches each in its own env, and
aggregates:

```bash
# run a whole endpoint (enumerate -> dispatch each -> aggregate)
python -m core.run --endpoint herg --input path/to/input.json --out path/to/outdir

# or run a single model directly (bypasses endpoint enumeration)
python -m core.run --model admet_ai --input path/to/input.json --out path/to/outdir
```

`--input` is an `InputRecord` JSON payload (`{"smiles": "...", "mol_id": "..."}`). Results are printed
as JSON to stdout; per-model input/output files land under `--out` and every run is appended to the
ledger on `/zfs`.

## Tests: two tiers

Fast unit + integration tests run in the core env with no box and no GPU; per-model smoke tests
(`@pytest.mark.model`) shell into each model's isolated env on the box and are opt-in (`SETTLED` §8).

```bash
# fast tier (default gate: registry / schema / dispatch / run + cross-cutting integration)
pixi run pytest tests/ -m "not model" -q

# opt-in model smoke tier (on the box only)
pixi run pytest tests/ -m "model" -q
```

The canonical **FTO-43 fixture** (`tests/fixtures/fto43.smi`, exposed as the `fto43` / `fto43_input`
pytest fixtures in `tests/conftest.py`) is the single lead-compound input reused across the suite and
by each model's smoke test.

> **NEEDS_AARAN:** the SMILES in `tests/fixtures/fto43.smi` is a documented **placeholder**. The
> canonical structure for CID 164886650 is a live PubChem lookup that could not be run in the headless
> build session, and the no-fabricate rule forbids guessing it. Drop in the real canonical SMILES and
> rename the title from `FTO-43-PLACEHOLDER` to `FTO-43`: a one-line data swap, no code changes. The
> value is only load-bearing for the opt-in model smoke tier; the fast tier is green either way.
