# t08-core-run - `core/run.py` (`run_endpoint` + CLI)

**Kind:** core · **Autonomy:** high · **Runs:** laptop to author + test (mocked dispatch)
**Touch only:** `core/run.py`, `tests/test_run.py`
**Deps:** t07-core-dispatch, t04-core-registry

## Read first
- `CLAUDE.md` §2 (`run_endpoint` = registry query → dispatch each → aggregate; generic + singular).
- `docs/FTO_ADMET_Codebase_And_Environment_SETTLED.md` §6 (`run.run_endpoint`), §3 (aggregator lives in `endpoints/<ep>/aggregate.py`, runs in the **core** env).

## Build
1. **`run_endpoint(endpoint: Endpoint, input) -> EndpointResult`:**
   - Select models: `[spec for spec in REGISTRY.values() if endpoint in spec.endpoints and spec.in_bulk_loop]`.
   - `dispatch.run_model(spec.name, input, out)` for each; collect the `OutputRecord`s.
   - Load that endpoint's aggregator dynamically (`import endpoints.<endpoint>.aggregate`) and call its
     known entry (define the convention now, e.g. `aggregate(records: list[OutputRecord]) -> EndpointResult`).
     Aggregators run in the **core** env on collected outputs (not on models' conflicting deps).
   - Tolerate a missing aggregator gracefully (endpoint not built yet) → return raw records with a clear note.
2. **CLI** (`python -m core.run …`): `--endpoint <name> --input <path> [--out <dir>] [--model <name>]`
   (`--model` runs a single model via `dispatch.run_model`). Print/persist results; exit non-zero on failure.
3. Keep it **generic** - no per-endpoint branches. Adding an endpoint = a folder + an aggregator, never an
   edit here.

## Landmines
- Respect `in_bulk_loop`: web-only/shortlist models (`watanabe_*`, `protox`, `ctoxpred2`, `cardiogenai`,
  `aizynthfinder`, `pbpk`) must be **excluded** from the bulk enumeration.
- Cross-cutting models appear under several endpoints (their `endpoints` set) - `run_endpoint(triage)` and
  `run_endpoint(toxicity)` may both dispatch `admet_ai`; that's correct.

## Done (gate: `pixi run pytest tests/test_run.py -q` green - dispatch + aggregator mocked)
- `run_endpoint(herg)` enumerates exactly the bulk-loop hERG models (mock the registry/dispatch) and
  excludes non-bulk ones (`ctoxpred2`, `cardiogenai`).
- A cross-cutting model is picked up under each of its endpoints.
- Missing aggregator is handled (returns records + note, no crash).
- CLI parses `--endpoint`/`--input`/`--model` and dispatches accordingly.

## Blocked if
- Laptop-only with mocks; should not block. Record any error and BLOCK.
