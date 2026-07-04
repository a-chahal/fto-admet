# t12-gate-phase1 - prove the pattern holds on two real models

**Kind:** gate · **Autonomy:** review · **Runs:** laptop, core env (integration); box smokes already gated at t10/t11
**Touch only:** `tests/test_phase1_integration.py`
**Deps:** t11-model-pksmart

## Read first
- `CLAUDE.md` §2 (contract), §5 (gate = independent verification, no fixing others' code).
- The t10 and t11 specs (the template this gate certifies).

## Why this task
Checkpoint before Phase 2 fans out ~26 models. It confirms the **subprocess pattern + folder template**
work end-to-end on two genuinely different models - a trivial rule model (rdkit_crippen) and a real
isolated env (pksmart) - so the rest of the swarm can imitate them safely. The per-model **box smokes were
already verified** at t10/t11 (model-kind gates check the box-solved lock + smoke). This gate adds the
**laptop-runnable integration** check; it does not re-run box smokes (set `GATE_RERUN_SMOKE=1` on `run.sh`
if you want that belt-and-suspenders).

## Build - `tests/test_phase1_integration.py`
Assert, using the registry + mocked dispatch (no box needed):
1. Both `rdkit_crippen` and `pksmart` are in `REGISTRY` with correct `endpoints`, `in_bulk_loop=True`,
   and non-`None` `env_manifest` + `entrypoint` paths that **exist on disk**.
2. Each model folder conforms to the **template**: `pixi.toml`, `pixi.lock`, `run.py`, `README.md` present;
   `run.py` exposes the uniform `--input/--output[/--gpu]` CLI (parse its argparse or `--help`).
3. `dispatch.run_model` (subprocess mocked to echo a schema-shaped payload) validates and returns an
   `OutputRecord` for each; a `fail` path writes a `fail` ledger record.
4. `run_endpoint(lipophilicity)` includes `rdkit_crippen`; `run_endpoint(clearance)` includes `pksmart`.
5. PKSmart's output round-trips through `core.schemas` including the `Uncertainty` field (fold-error if the
   model exposed it).

## Done (gate: `pixi run pytest tests/test_phase1_integration.py -q` green)
- All five assertions pass on the laptop.
- `python3 lib/state.py summary` shows t10 and t11 DONE (their box smokes passed at their own gates).

## Blocked if
- An integration assertion fails because a **t10/t11 artifact is wrong** (missing file, bad CLI, schema
  mismatch) → BLOCK naming the offending model + defect so that model's task is revisited. Do not patch the
  model or `core` from this gate.
