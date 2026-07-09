"""Append-only run ledger: the pipeline's reproducibility trail (CLAUDE.md §0/§6, SETTLED §7).

One JSON object per line on ``/zfs``, written **by the job itself, on the box, at completion**. JSONL,
not SQLite: the ledger lives on NFS and SQLite's file locking is unreliable there, whereas an
``O_APPEND`` write of a single line is atomic. With no scheduler and long jobs living in detached tmux,
a dropped laptop connection must never lose the record, so the box-side job appends its own line and
``fsync``s it before exiting.

Record shape (one line):
    {model, input_hash, output_path, env_lock_hash, cuda_device, timestamp, status[, note]}
``status`` is ``ok`` or ``fail``; ``timestamp`` is ISO-8601 UTC; ``note`` is an optional free-text
reason (e.g. a failure message). ``cuda_device`` is ``None`` for the CPU/rule-based models that never
touch the GPU path.

Also here: the two provenance hash helpers (deterministic sha256 over the input and the env lock, so
identical inputs/envs collide for matching) and the raw-output cache (CLAUDE.md §4a) that keeps every
verbatim upstream/web response so a result stays reconstructible after a service silently changes.

Pure stdlib on purpose: the ledger has to be writable from the box-side job before any heavy import,
and reads have to survive a truncated final line (a crash mid-append) without a parser dependency.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import Config, get_config

# The columns every ledger line must carry (SETTLED §7). ``note`` is optional and not in this set.
REQUIRED_KEYS = ("model", "input_hash", "output_path", "env_lock_hash", "cuda_device", "timestamp", "status")
VALID_STATUS = ("ok", "fail")

_CHUNK = 1 << 20  # 1 MiB, for streaming file hashes without loading the whole lock into memory


# --------------------------------------------------------------------------- record construction
def new_record(
    *,
    model: str,
    input_hash: str,
    output_path: str | os.PathLike[str] | None,
    env_lock_hash: str | None,
    cuda_device: int | None,
    status: str,
    note: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Build a validated ledger record with a fresh ISO-8601 UTC ``timestamp`` (overridable for tests).

    Kept separate from :func:`append` so a caller can assemble the record, decide ``ok``/``fail`` from
    the run outcome, and hand a plain dict to ``append``. ``cuda_device`` stays ``None`` for CPU models.
    """
    if status not in VALID_STATUS:
        raise ValueError(f"status must be one of {VALID_STATUS}, got {status!r}")
    rec: dict[str, Any] = {
        "model": str(model),
        "input_hash": input_hash,
        "output_path": None if output_path is None else str(output_path),
        "env_lock_hash": env_lock_hash,
        "cuda_device": cuda_device,
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "status": status,
    }
    if note is not None:
        rec["note"] = note
    return rec


# --------------------------------------------------------------------------- append (box-side write)
def append(record: dict[str, Any], path: str | os.PathLike[str] | None = None) -> None:
    """Append one record as a single JSON line, then ``flush`` + ``fsync`` so the box-side write is durable.

    Opens in append mode (never a read-modify-write of the whole file: that is the exact operation that
    is unsafe over NFS and would lose concurrent lines). Creates the parent dir if missing. ``path``
    defaults to ``config.ledger`` (``$FTO_ADMET_ROOT/ledger/runs.jsonl``); tests pass a tmp path.
    """
    missing = [k for k in REQUIRED_KEYS if k not in record]
    if missing:
        raise ValueError(f"ledger record missing required key(s): {missing}")
    if record["status"] not in VALID_STATUS:
        raise ValueError(f"status must be one of {VALID_STATUS}, got {record['status']!r}")

    target = Path(path) if path is not None else get_config().ledger
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    with open(target, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def load(path: str | os.PathLike[str] | None = None) -> list[dict[str, Any]]:
    """Read the whole ledger into a list of dicts (oldest first), tolerating a truncated final line.

    A crash or a dropped connection mid-append can leave the last line half-written; that is expected on
    NFS, so a JSON parse error on the *final* non-empty line is dropped rather than raised. A malformed
    line anywhere earlier is a real corruption and is surfaced. Load into pandas in-memory for querying
    if needed (SETTLED §7); the ledger itself stays plain JSONL.
    """
    target = Path(path) if path is not None else get_config().ledger
    if not target.exists():
        return []
    lines = target.read_text(encoding="utf-8").splitlines()
    # Index of the last non-empty physical line; only that one is allowed to be a partial write.
    last_nonempty = max((i for i, ln in enumerate(lines) if ln.strip()), default=-1)
    records: list[dict[str, Any]] = []
    for i, ln in enumerate(lines):
        if not ln.strip():
            continue
        try:
            records.append(json.loads(ln))
        except json.JSONDecodeError:
            if i == last_nonempty:
                break  # truncated tail from an interrupted append; safe to drop
            raise
    return records


# --------------------------------------------------------------------------- provenance hashes
def hash_input(value: str | os.PathLike[str], *, is_file: bool = False) -> str:
    """Deterministic sha256 hex for provenance matching.

    A ``str`` is hashed as literal content (a SMILES / input string), stripped of surrounding
    whitespace so trivially different encodings of the same molecule collide. Pass ``is_file=True`` (or a
    ``Path``) to hash the *bytes of a file* instead - the same input always yields the same digest, and a
    changed input yields a different one.
    """
    if isinstance(value, Path) or is_file:
        return _sha256_file(value)
    return hashlib.sha256(str(value).strip().encode("utf-8")).hexdigest()


def hash_env_lock(path: str | os.PathLike[str]) -> str:
    """Deterministic sha256 hex of a ``pixi.lock`` file's bytes (the exact resolved env fingerprint)."""
    return _sha256_file(path)


def _sha256_file(path: str | os.PathLike[str]) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- raw-output cache (§4a)
def cache_raw(
    model: str,
    input_hash: str,
    payload: bytes | str | dict[str, Any] | list[Any],
    cfg: Config | None = None,
) -> Path:
    """Persist a verbatim upstream/web response under ``root/cache/<model>/<input_hash>.json``.

    In scope now as infra (CLAUDE.md §4a): async/web adapters (``ochem_ppb``, the web
    SOP transcriptions) cache their raw responses so a result stays reconstructible after the service
    silently changes. ``bytes``/``str`` payloads are written verbatim; a dict/list is serialized to JSON.
    Returns the path written. Keyed by (model, input_hash) so a re-run overwrites its own cache entry.
    """
    cfg = cfg if cfg is not None else get_config()
    dest = cfg.root / "cache" / model / f"{input_hash}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, (bytes, bytearray)):
        dest.write_bytes(bytes(payload))
    elif isinstance(payload, str):
        dest.write_text(payload, encoding="utf-8")
    else:
        dest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return dest


def read_raw(model: str, input_hash: str, cfg: Config | None = None) -> str:
    """Return the cached raw payload for (model, input_hash) as text; raises if it was never cached."""
    cfg = cfg if cfg is not None else get_config()
    return (cfg.root / "cache" / model / f"{input_hash}.json").read_text(encoding="utf-8")


def raw_cache_path(model: str, input_hash: str, cfg: Config | None = None) -> Path:
    """The path :func:`cache_raw` uses for (model, input_hash), without reading it (existence check hook)."""
    cfg = cfg if cfg is not None else get_config()
    return cfg.root / "cache" / model / f"{input_hash}.json"
