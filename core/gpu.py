"""The scheduler Rosenbluth doesn't have: pick a free GPU and hold a soft lock on it.

Rosenbluth is a single 4-GPU host with **no scheduler** (no SLURM/k8s/queue). Claiming a device is
manual and convention-based: read ``nvidia-smi``, find a device under the free-memory threshold, and
``export CUDA_VISIBLE_DEVICES=N`` in the *same* ssh connection as the job (CLAUDE.md §1, SETTLED §2/§7).

Two facts drive every design choice here:

1. **Never cache "free."** A 144-day-idle tmux session currently holds GPU 0; only a *fresh*
   ``nvidia-smi`` at claim time is truthful. So we never memoize device state.
2. **The durable claim is the lock file, not the env var.** ``CUDA_VISIBLE_DEVICES=N`` set in one ssh
   call is gone by the next fresh-shell call, so it cannot coordinate our own concurrent runs across
   connections. A soft lock file on shared ``/zfs`` storage (``$FTO_ADMET_ROOT/.locks/gpu{N}.lock``)
   is what survives, and it is checked alongside ``nvidia-smi``.

This module does **not** set ``CUDA_VISIBLE_DEVICES`` and does **not** launch jobs: :func:`pick_free_gpu`
returns an index (or ``None``) and the caller rides it into the job's ssh connection. Models with
``requires_gpu=False`` never touch this path.

The lock is a *soft* lock, held by convention: we never kill another process's job. A lock older than
:data:`LOCK_TTL_SECONDS` is considered stale and may be reclaimed by :func:`acquire` (a crashed run can
leave a lock behind); a live-but-old lock on shared storage stays advisory only.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from core.config import Config, get_config

# A GPU with less than this many MiB in use counts as free (per the box MOTD, SETTLED §2).
FREE_THRESHOLD_MIB = 15

# A lock file older than this is treated as stale (a crashed run that never released) and may be
# reclaimed. This is advisory only: we never inspect or kill the process that wrote it.
LOCK_TTL_SECONDS = 12 * 60 * 60  # 12 hours

# The exact query whose CSV output :func:`parse_nvidia_smi` expects.
_NVIDIA_SMI_CMD = (
    "nvidia-smi",
    "--query-gpu=index,memory.used",
    "--format=csv,noheader,nounits",
)


class GpuError(RuntimeError):
    """A GPU could not be queried, or a lock could not be acquired/released."""


# --------------------------------------------------------------------------------------------------
# nvidia-smi: parse (pure, unit-testable) and query (shells out)
# --------------------------------------------------------------------------------------------------

def parse_nvidia_smi(text: str) -> dict[int, int]:
    """Turn ``nvidia-smi`` CSV output into ``{gpu_index: used_MiB}``.

    Expects the output of ``nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits``
    (each line ``"<index>, <used>"``). Blank lines are skipped. Kept pure and text-in so the picker is
    testable without a real GPU. Raises :class:`GpuError` on a malformed row rather than guessing.
    """
    used: dict[int, int] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 2:
            raise GpuError(
                f"nvidia-smi line {lineno} has {len(parts)} fields, expected 2 "
                f"(index, memory.used): {raw!r}"
            )
        try:
            index = int(parts[0])
            used_mib = int(parts[1])
        except ValueError as exc:
            raise GpuError(f"nvidia-smi line {lineno} is not '<int>, <int>': {raw!r}") from exc
        used[index] = used_mib
    return used


def query_used_mib() -> dict[int, int]:
    """Run ``nvidia-smi`` *now* and return ``{gpu_index: used_MiB}``.

    Always a fresh call: caching "free" is the one thing this module must never do (module docstring,
    landmine). Raises :class:`GpuError` if ``nvidia-smi`` is missing or fails, which is expected off
    the box (this function is never called by the mocked tests).
    """
    try:
        proc = subprocess.run(
            _NVIDIA_SMI_CMD,
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise GpuError("nvidia-smi not found; this must run on the box (SETTLED §2)") from exc
    except subprocess.CalledProcessError as exc:
        raise GpuError(f"nvidia-smi failed (exit {exc.returncode}): {exc.stderr.strip()}") from exc
    return parse_nvidia_smi(proc.stdout)


def free_indices(used: dict[int, int], *, threshold: int = FREE_THRESHOLD_MIB) -> list[int]:
    """Indices whose used memory is below ``threshold``, ascending. Ignores locks (that is a separate
    check in :func:`pick_free_gpu`)."""
    return sorted(i for i, mib in used.items() if mib < threshold)


# --------------------------------------------------------------------------------------------------
# Soft lock files: the cross-connection claim
# --------------------------------------------------------------------------------------------------

def _locks_dir(config: Config | None) -> Path:
    """The directory soft locks live in (``$FTO_ADMET_ROOT/.locks``). Injectable for tests."""
    cfg = config if config is not None else get_config()
    cfg.locks.mkdir(parents=True, exist_ok=True)
    return cfg.locks


def lock_path(n: int, *, config: Config | None = None) -> Path:
    """Path of the soft lock for GPU ``n``."""
    return _locks_dir(config) / f"gpu{n}.lock"


def _is_stale(path: Path, *, ttl: int = LOCK_TTL_SECONDS) -> bool:
    """True if the lock file is older than ``ttl`` seconds (a crashed run that never released)."""
    try:
        age = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
    except FileNotFoundError:
        return False
    return age > ttl


def is_locked(n: int, *, config: Config | None = None, ttl: int = LOCK_TTL_SECONDS) -> bool:
    """True if GPU ``n`` holds a live (non-stale) soft lock. A stale lock reads as *not* locked so it
    can be reclaimed."""
    path = lock_path(n, config=config)
    if not path.exists():
        return False
    return not _is_stale(path, ttl=ttl)


def acquire(n: int, *, config: Config | None = None, ttl: int = LOCK_TTL_SECONDS) -> Path:
    """Claim GPU ``n`` by creating its lock file (pid + ISO-8601 UTC timestamp).

    Uses an exclusive ``O_EXCL`` create so two concurrent claimers cannot both win the same device
    (the real collision risk once we dispatch many models across 4 GPUs). A **stale** lock
    (:data:`LOCK_TTL_SECONDS`) is reclaimed; a live lock raises :class:`GpuError`.

    Note this claims blindly: check :func:`pick_free_gpu` (or ``nvidia-smi`` + :func:`is_locked`) first
    to confirm the device is actually free.
    """
    path = lock_path(n, config=config)
    if path.exists() and _is_stale(path, ttl=ttl):
        path.unlink(missing_ok=True)
    payload = f"pid={os.getpid()} at={datetime.now(timezone.utc).isoformat()}\n"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError as exc:
        raise GpuError(f"GPU {n} is already locked ({path}); another run holds it") from exc
    with os.fdopen(fd, "w") as fh:
        fh.write(payload)
    return path


def release(n: int, *, config: Config | None = None) -> None:
    """Drop the soft lock on GPU ``n``. Idempotent: releasing an unlocked GPU is a no-op."""
    lock_path(n, config=config).unlink(missing_ok=True)


@contextmanager
def claim(n: int, *, config: Config | None = None, ttl: int = LOCK_TTL_SECONDS) -> Iterator[int]:
    """Hold the soft lock on GPU ``n`` for the duration of a ``with`` block, releasing on exit.

    Releases even if the body raises, so a crashing job does not orphan the lock within this process
    (a lock orphaned by a *killed* process is handled by the stale-TTL reclaim in :func:`acquire`)::

        with claim(n) as dev:
            run_job_on(dev)  # caller sets CUDA_VISIBLE_DEVICES=dev in the job's ssh connection
    """
    acquire(n, config=config, ttl=ttl)
    try:
        yield n
    finally:
        release(n, config=config)


# --------------------------------------------------------------------------------------------------
# The pick: free by nvidia-smi AND not locked
# --------------------------------------------------------------------------------------------------

def pick_free_gpu(
    *,
    smi_text: str | None = None,
    config: Config | None = None,
    threshold: int = FREE_THRESHOLD_MIB,
    ttl: int = LOCK_TTL_SECONDS,
) -> int | None:
    """Lowest GPU index that is free by ``nvidia-smi`` **and** not soft-locked, else ``None``.

    Queries ``nvidia-smi`` fresh unless ``smi_text`` is supplied (the tests inject sample output; the
    landmine is that "free" is never cached). Returns only the index: the caller must set
    ``CUDA_VISIBLE_DEVICES=<index>`` in the *same* ssh connection as the job, and typically claim it
    with :func:`claim`/:func:`acquire` so a concurrent run does not race onto the same device.
    """
    used = parse_nvidia_smi(smi_text) if smi_text is not None else query_used_mib()
    for index in free_indices(used, threshold=threshold):
        if not is_locked(index, config=config, ttl=ttl):
            return index
    return None
