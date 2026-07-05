"""Unit tests for core.gpu (GPU pick + soft lock). Fully mocked - no real GPU, no nvidia-smi.

Every case feeds sample ``nvidia-smi`` text into the pure parser/picker and points the locks dir at a
``tmp_path`` :class:`Config`, so the suite runs on the laptop. Gate: ``pytest tests/test_gpu.py``.
"""

import os
from datetime import datetime, timezone

import pytest

from core.config import Config
from core.gpu import (
    FREE_THRESHOLD_MIB,
    GpuError,
    acquire,
    claim,
    free_indices,
    is_locked,
    lock_path,
    parse_nvidia_smi,
    pick_free_gpu,
    release,
)

# Sample output of: nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits
# GPU 0 is the 144-day-idle tmux holder from the landmine (busy); 1 and 3 are free; 2 is busy.
SMI_MIXED = "0, 812\n1, 3\n2, 24567\n3, 0\n"
SMI_ALL_FREE = "0, 0\n1, 2\n2, 5\n3, 14\n"
SMI_ALL_BUSY = "0, 900\n1, 1024\n2, 24567\n3, 16\n"


def _config(tmp_path) -> Config:
    """A Config whose locks dir is under tmp_path; other paths are unused by these tests."""
    root = tmp_path / "fto-admet"
    return Config(
        root=root,
        env_cache=tmp_path / "envs",
        ledger=root / "ledger" / "runs.jsonl",
        locks=tmp_path / ".locks",
        outputs=root / "outputs",
    )


# --------------------------------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------------------------------

def test_parse_maps_index_to_used_mib():
    assert parse_nvidia_smi(SMI_MIXED) == {0: 812, 1: 3, 2: 24567, 3: 0}


def test_parse_skips_blank_lines_and_trailing_newline():
    assert parse_nvidia_smi("\n0, 5\n\n1, 6\n") == {0: 5, 1: 6}


def test_parse_rejects_malformed_row():
    with pytest.raises(GpuError):
        parse_nvidia_smi("0, 5\n1\n")  # missing the memory field


def test_parse_rejects_non_integer():
    with pytest.raises(GpuError):
        parse_nvidia_smi("0, N/A\n")


def test_free_indices_respects_threshold():
    used = parse_nvidia_smi(SMI_MIXED)
    assert free_indices(used) == [1, 3]
    # Boundary: threshold is strict (< threshold). 14 is free at 15, busy at 14.
    assert free_indices({0: 14}, threshold=FREE_THRESHOLD_MIB) == [0]
    assert free_indices({0: 14}, threshold=14) == []


# --------------------------------------------------------------------------------------------------
# pick_free_gpu
# --------------------------------------------------------------------------------------------------

def test_pick_returns_lowest_free_unlocked(tmp_path):
    cfg = _config(tmp_path)
    assert pick_free_gpu(smi_text=SMI_MIXED, config=cfg) == 1


def test_pick_skips_locked_even_when_free(tmp_path):
    cfg = _config(tmp_path)
    acquire(1, config=cfg)  # 1 is free by nvidia-smi but now locked -> fall through to 3
    assert pick_free_gpu(smi_text=SMI_MIXED, config=cfg) == 3


def test_pick_returns_none_when_all_busy(tmp_path):
    cfg = _config(tmp_path)
    assert pick_free_gpu(smi_text=SMI_ALL_BUSY, config=cfg) is None


def test_pick_returns_none_when_all_free_but_locked(tmp_path):
    cfg = _config(tmp_path)
    for n in range(4):
        acquire(n, config=cfg)
    assert pick_free_gpu(smi_text=SMI_ALL_FREE, config=cfg) is None


def test_pick_never_shells_out_when_text_supplied(tmp_path, monkeypatch):
    # Landmine guard: with smi_text given, query_used_mib (the nvidia-smi call) must not run.
    import core.gpu as gpu

    def boom():
        raise AssertionError("pick_free_gpu queried nvidia-smi despite smi_text being supplied")

    monkeypatch.setattr(gpu, "query_used_mib", boom)
    assert pick_free_gpu(smi_text=SMI_ALL_FREE, config=_config(tmp_path)) == 0


# --------------------------------------------------------------------------------------------------
# acquire / release / is_locked
# --------------------------------------------------------------------------------------------------

def test_acquire_creates_lock_with_pid_and_timestamp(tmp_path):
    cfg = _config(tmp_path)
    path = acquire(2, config=cfg)
    assert path == lock_path(2, config=cfg)
    assert path.is_file()
    body = path.read_text()
    assert f"pid={os.getpid()}" in body
    assert "at=" in body
    assert is_locked(2, config=cfg)


def test_release_removes_lock_and_is_idempotent(tmp_path):
    cfg = _config(tmp_path)
    acquire(2, config=cfg)
    release(2, config=cfg)
    assert not lock_path(2, config=cfg).exists()
    assert not is_locked(2, config=cfg)
    release(2, config=cfg)  # idempotent: no raise on an already-released GPU


def test_acquire_twice_raises(tmp_path):
    cfg = _config(tmp_path)
    acquire(0, config=cfg)
    with pytest.raises(GpuError):
        acquire(0, config=cfg)


def test_stale_lock_reads_as_unlocked_and_is_reclaimed(tmp_path):
    cfg = _config(tmp_path)
    path = acquire(0, config=cfg)
    # Backdate the lock well past the TTL to simulate a crashed run that never released.
    old = datetime(2000, 1, 1, tzinfo=timezone.utc).timestamp()
    os.utime(path, (old, old))
    assert not is_locked(0, config=cfg)  # stale -> not locked
    # A stale lock is reclaimable: acquire succeeds and rewrites it with our pid.
    acquire(0, config=cfg)
    assert f"pid={os.getpid()}" in path.read_text()


def test_stale_lock_is_pickable(tmp_path):
    cfg = _config(tmp_path)
    path = acquire(1, config=cfg)  # 1 is otherwise the lowest free index in SMI_MIXED
    old = datetime(2000, 1, 1, tzinfo=timezone.utc).timestamp()
    os.utime(path, (old, old))
    assert pick_free_gpu(smi_text=SMI_MIXED, config=cfg) == 1  # stale lock does not block


# --------------------------------------------------------------------------------------------------
# claim context manager
# --------------------------------------------------------------------------------------------------

def test_claim_holds_then_releases(tmp_path):
    cfg = _config(tmp_path)
    with claim(3, config=cfg) as dev:
        assert dev == 3
        assert is_locked(3, config=cfg)
    assert not is_locked(3, config=cfg)


def test_claim_releases_on_exception(tmp_path):
    cfg = _config(tmp_path)
    with pytest.raises(ValueError):
        with claim(3, config=cfg):
            assert is_locked(3, config=cfg)
            raise ValueError("job blew up mid-run")
    assert not is_locked(3, config=cfg)  # released despite the exception


def test_claimed_gpu_is_not_picked(tmp_path):
    cfg = _config(tmp_path)
    with claim(1, config=cfg):
        assert pick_free_gpu(smi_text=SMI_MIXED, config=cfg) == 3
    assert pick_free_gpu(smi_text=SMI_MIXED, config=cfg) == 1  # freed after the block
