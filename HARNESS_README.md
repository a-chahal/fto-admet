# FTO-ADMET autonomous build harness

This drives **Claude Code** to build the FTO-ADMET pipeline unattended, one task at a time, each in a
**fresh memoryless session** so context never bloats and output quality never degrades across the
~54-task build. It builds nothing itself - it spawns Claude Code, which does the work.

## Pieces

| File | Role |
|---|---|
| `CLAUDE.md` | Standing law, auto-loaded into every session: invariants, landmines-as-orders, done-definition, no-fabricate rule. |
| `DRIVER.md` | Per-session prompt template the loop injects into each `claude -p`. |
| `MANIFEST.yaml` | The 54-task DAG (phases, deps, autonomy, test targets). Human-edited source of truth. |
| `tasks/<id>.md` | One distilled build spec per task - *is* the prompt a session executes. (Authored in stages.) |
| `STATE.json` | Durable per-task status ledger. What makes the loop resumable across crashes/restarts. |
| `lib/state.py` | Atomic state ops + readiness (next ready = PENDING with all deps DONE) + `plan`/`validate`. |
| `lib/gate.sh` | Deterministic, **independent** verification of each task's artifacts (anti-fabrication). |
| `run.sh` | The loop: pick ready task → spawn fresh session → gate → update state → repeat. |
| `.harness/` | Runtime: `results/<id>.json` (audit trail, committed), `logs/<id>.<n>.log` (transient). |

These live at the **repo root**, beside `core/` and `endpoints/`, so `CLAUDE.md` auto-loads and the
four settled docs sit in `docs/`.

## Run it

```bash
./run.sh --dry-run # print the build order; spawn nothing, change nothing
./run.sh --once # build exactly one ready task
./run.sh # run until no task is ready, then summarize
./run.sh --include-human # also attempt human/NEEDS_AARAN tasks (when Aaran is present)
python3 lib/state.py summary # status counts + the BLOCKED / NEEDS_AARAN / DEFERRED queues
python3 lib/state.py validate # DAG integrity (unknown deps, cycles)
```

Overnight: `caffeinate ./run.sh` (macOS) or run inside `tmux`; on laptop sleep the loop pauses and
resumes on wake because state is durable. Long box installs run detached in tmux **inside** each
session (over ssh), so a dropped connection doesn't kill a build.

## How a task completes

A session writes `.harness/results/<id>.json` (`status: pass | blocked | needs_aaran`). The gate then
re-verifies independently - it does **not** trust the report:
- **core/aggregator/gate** → the declared pytest target passes in the core env.
- **model** → `pixi.lock` exists and is **box-solved** (has a `linux-64` section + real package hashes;
  a laptop-solved or hand-written lock is rejected as fabrication), the smoke test passed on the box
  against the FTO-43 fixture with correct units/direction, README provenance filled.
- **sop** → README has the required sections (URL, INPUTS, OUTPUT FIELDS, LEDGER shape).
- **api-model** → transport + retry + cache + placeholder schema built; the live literal (ADMETlab CSV
  header / OCHEM `modelId`) is the only residue → filed under **NEEDS_AARAN**, not DONE.

Pass → `DONE`. `needs_aaran` → quarantined for Aaran, loop continues. Fail → retried up to
`ATTEMPT_CAP` (default 3), then `BLOCKED` with the exact error - never an infinite loop, never a
fabricated pass. Blocked/human tasks are skipped so one stuck legacy env can't stall the other 40.

## What the loop will correctly NOT finish autonomously

By design these land in `NEEDS_AARAN` / `DEFERRED`, labeled, not half-built:
- `t00-bootstrap-box` - one-time box setup (pixi config, clone, .env); self-serve, no admin needed.
- `t35-model-admetlab3`, `t36-model-ochem_ppb` - one live/authenticated lookup each.
- `t37/t38/t39` SOPs - the web runs themselves are manual (the READMEs get built).
- `t52-agg-herg` - hERG gate math is a deferred decision; scaffold only.
- F-16 standardization and F-13 pKa source are wired as documented placeholders with TODOs.

"Autonomously completes the project" here means: builds everything decided and code-shaped, and hands
back a clean, labeled queue of exactly what only you can close.
