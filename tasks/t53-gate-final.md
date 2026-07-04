# t53-gate-final - full non-model suite + project rollup

**Kind:** gate · **Autonomy:** review · **Runs:** laptop, core env
**Touch only:** `tests/test_pipeline_integration.py`, `README.md` (status section) - **not** any `core/`/model/aggregator code
**Deps:** all 12 non-deferred aggregators (t40-t51)

## Read first
- `CLAUDE.md` §5 (gate = independent verification, no fixing others' code).

## Why this task
Final checkpoint. Confirms the whole pipeline hangs together end-to-end at the contract level and emits the
labeled rollup of what's DONE vs. what only Aaran can close. Per-model **box smokes were gated per-model**;
this gate runs the **non-model** suite (core + integration + all aggregator tests).

## Build
1. **`tests/test_pipeline_integration.py`** - end-to-end on the contract (mocked dispatch, no box):
   - `run_endpoint(ep)` works for **every** `Endpoint`, routing to the right models and calling each
     endpoint's `aggregate.py` (or the DEFERRED sentinel for hERG).
   - every endpoint has an `aggregate.py`; every non-web/non-derived model has a built folder; cross-cutting
     models resolve under each of their endpoints.
   - the hERG aggregator returns/raises **DEFERRED** (not a fabricated verdict).
2. **`README.md` status section** - a short table of endpoint → contributing models → status, and the
   **NEEDS_AARAN / DEFERRED queue** (admetlab3 header, ochem_ppb modelId, OPERA/PBPK heavy installs if
   pending, the DruMAP/ProTox web runs, the hERG gate math, F-16 standardization, F-13 pKa source).

## Done (gate: `pixi run pytest tests/ -m "not model" -q` green)
- The full non-model suite passes (core + integration + all 12 aggregator tests + the DEFERRED hERG check).
- `python3 lib/state.py summary` shows the final rollup; the README status section matches it.

## Blocked if
- Any non-model test fails → BLOCK naming the failing test + owning task (fix flows back to that task; do not
  patch it from the final gate).

## After this gate
The autonomous build is complete. What remains is by design, in the NEEDS_AARAN / DEFERRED queue: the two
live API lookups, the manual web runs, the heavy-runtime installs if not yet done, and the deferred decisions
(hERG gate math, F-16 standardization, F-13 pKa source) - each labeled, none half-built.
