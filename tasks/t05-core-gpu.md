# t05-core-gpu - `core/gpu.py` (the scheduler Rosenbluth doesn't have)

**Kind:** core · **Autonomy:** high · **Runs:** laptop to author + test (mocked); real use is on the box
**Touch only:** `core/gpu.py`, `tests/test_gpu.py`
**Deps:** t01-core-config

## Read first
- `docs/FTO_ADMET_Codebase_And_Environment_SETTLED.md` §7 (`core/gpu.py`), §2 (GPU claiming), §8a (fresh-shell caveat).
- `CLAUDE.md` §1 (each ssh call is a fresh shell - the durable claim is the lock file, not the env var).

## Build
Rosenbluth has 4 GPUs, no scheduler, convention-based claiming. `core/gpu.py` picks a free device and
holds a soft lock so your own concurrent runs don't collide.

1. **Query fresh at claim time - never cache.** Parse `nvidia-smi` (e.g.
   `nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits`) → per-GPU used MiB.
   A GPU is *free* if `used < FREE_THRESHOLD_MIB` (default 15, per the box MOTD). Make the parser take
   `nvidia-smi` text as input so it is unit-testable without a GPU.
2. **Soft lock files** at `config.locks / f"gpu{N}.lock"` (write pid + ISO timestamp). `acquire(n)` /
   `release(n)`; provide a context manager. A GPU is claimable only if free by `nvidia-smi` **and** not
   locked. Stale-lock handling: document the policy (e.g. lock older than a TTL may be reclaimed) but keep
   it simple; do not auto-kill processes.
3. `pick_free_gpu()` → an index or `None` if none available. Return the index; **the caller** sets
   `CUDA_VISIBLE_DEVICES=N` in the *same* ssh connection as the job (the env var cannot span connections).
4. Models with `requires_gpu=False` never call this path.

## Landmines
- **Never cache "free."** A 144-day-idle tmux currently holds GPU 0; only a fresh query is truthful.
- The soft lock is the cross-connection claim; `CUDA_VISIBLE_DEVICES` alone does not survive a new ssh.

## Done (gate: `pixi run pytest tests/test_gpu.py -q` green, fully mocked - no real GPU)
- Parser turns sample `nvidia-smi` text into correct per-GPU free/busy states.
- `pick_free_gpu()` returns a free, unlocked index; returns `None` when all are busy or locked.
- `acquire`/`release` create and remove the lock file; a locked GPU is not picked; context manager
  releases on exit (including on exception).

## Blocked if
- Laptop-only for authoring+tests; should not block. Record any error and BLOCK.
