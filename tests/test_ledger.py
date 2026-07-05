"""Unit tests for core.ledger (append-only JSONL run ledger + provenance hashes + raw cache).

Hermetic and laptop-only: every case writes to a pytest ``tmp_path`` (standing in for ``/zfs``) and
passes an explicit ``path``/``cfg`` so nothing touches the developer's real environment or ledger.
Gate: ``pixi run pytest tests/test_ledger.py -q``.
"""

import json

import pytest

from core.config import load_config
from core import ledger


def _rec(**over):
    base = dict(
        model="admet_ai",
        input_hash="deadbeef",
        output_path="/zfs/out/x.json",
        env_lock_hash="cafef00d",
        cuda_device=0,
        status="ok",
    )
    base.update(over)
    return ledger.new_record(**base)


def _cfg(tmp_path):
    return load_config(
        env={"FTO_ADMET_ROOT": str(tmp_path / "fto"), "FTO_ADMET_ENV_CACHE": str(tmp_path / "envs")},
        dotenv_path=tmp_path / "nope.env",
    )


# --------------------------------------------------------------------------- append / load
def test_append_n_records_yields_n_ordered_json_lines(tmp_path):
    p = tmp_path / "ledger" / "runs.jsonl"
    for i in range(5):
        ledger.append(_rec(input_hash=f"h{i}", status="ok" if i % 2 else "fail"), path=p)

    lines = p.read_text().splitlines()
    assert len(lines) == 5
    parsed = [json.loads(ln) for ln in lines]  # each line parses on its own
    assert [r["input_hash"] for r in parsed] == [f"h{i}" for i in range(5)]  # order preserved
    for r in parsed:
        for k in ledger.REQUIRED_KEYS:
            assert k in r


def test_append_creates_missing_parent_dir(tmp_path):
    p = tmp_path / "deep" / "nested" / "runs.jsonl"
    ledger.append(_rec(), path=p)
    assert p.is_file()


def test_append_rejects_bad_status_and_missing_keys(tmp_path):
    p = tmp_path / "runs.jsonl"
    with pytest.raises(ValueError):
        ledger.append({"model": "x", "status": "ok"}, path=p)  # missing required keys
    with pytest.raises(ValueError):
        ledger.append({k: "x" for k in ledger.REQUIRED_KEYS} | {"status": "maybe"}, path=p)
    assert not p.exists()  # nothing written on rejection


def test_new_record_validates_status_and_defaults_timestamp():
    with pytest.raises(ValueError):
        ledger.new_record(
            model="m", input_hash="h", output_path=None, env_lock_hash=None,
            cuda_device=None, status="bogus",
        )
    r = _rec(cuda_device=None)  # CPU model: null device is allowed
    assert r["cuda_device"] is None
    assert r["timestamp"].endswith("+00:00")  # ISO-8601 UTC


def test_load_round_trips_records(tmp_path):
    p = tmp_path / "runs.jsonl"
    written = [_rec(input_hash=f"h{i}") for i in range(3)]
    for r in written:
        ledger.append(r, path=p)
    got = ledger.load(path=p)
    assert got == written


def test_load_missing_file_returns_empty(tmp_path):
    assert ledger.load(path=tmp_path / "absent.jsonl") == []


def test_load_tolerates_truncated_final_line(tmp_path):
    p = tmp_path / "runs.jsonl"
    ledger.append(_rec(input_hash="a"), path=p)
    ledger.append(_rec(input_hash="b"), path=p)
    # simulate a crash mid-append: a half-written final line with no newline
    with open(p, "a") as fh:
        fh.write('{"model": "x", "input_hash": "c", "stat')
    got = ledger.load(path=p)
    assert [r["input_hash"] for r in got] == ["a", "b"]  # partial tail dropped, not crashed


def test_load_raises_on_corruption_before_final_line(tmp_path):
    p = tmp_path / "runs.jsonl"
    p.write_text('{"broken": tru\n' + json.dumps(_rec()) + "\n")
    with pytest.raises(json.JSONDecodeError):
        ledger.load(path=p)


# --------------------------------------------------------------------------- hashes
def test_hash_input_deterministic_and_distinct():
    a = ledger.hash_input("CC(=O)O")
    assert a == ledger.hash_input("CC(=O)O")  # same input -> same hash
    assert a == ledger.hash_input("  CC(=O)O  ")  # whitespace-insensitive
    assert a != ledger.hash_input("c1ccccc1")  # different input -> different hash
    assert len(a) == 64  # sha256 hex


def test_hash_input_file_and_env_lock_deterministic(tmp_path):
    f = tmp_path / "pixi.lock"
    f.write_text("version: 6\npackages: []\n")
    h1 = ledger.hash_env_lock(f)
    h2 = ledger.hash_env_lock(f)
    assert h1 == h2 == ledger.hash_input(f)  # Path routes to file hashing
    f.write_text("version: 6\npackages: [numpy]\n")
    assert ledger.hash_env_lock(f) != h1  # changed lock -> changed hash


# --------------------------------------------------------------------------- raw cache
def test_cache_raw_round_trips_verbatim_string(tmp_path):
    cfg = _cfg(tmp_path)
    payload = "SMILES,pred\nCC(=O)O,0.83\n"  # e.g. a raw ADMETlab CSV response
    dest = ledger.cache_raw("admetlab3", "abc123", payload, cfg=cfg)
    assert dest == cfg.root / "cache" / "admetlab3" / "abc123.json"
    assert ledger.read_raw("admetlab3", "abc123", cfg=cfg) == payload


def test_cache_raw_serializes_dict(tmp_path):
    cfg = _cfg(tmp_path)
    payload = {"taskId": 42, "rows": [{"SMILES": "CC(=O)O", "logP": 0.09}]}
    ledger.cache_raw("ochem_ppb", "hh", payload, cfg=cfg)
    assert json.loads(ledger.read_raw("ochem_ppb", "hh", cfg=cfg)) == payload


def test_cache_raw_bytes_written_verbatim(tmp_path):
    cfg = _cfg(tmp_path)
    dest = ledger.cache_raw("admetlab3", "bin", b"\x00rawbytes\xff", cfg=cfg)
    assert dest.read_bytes() == b"\x00rawbytes\xff"


def test_cache_raw_keyed_by_model_and_hash(tmp_path):
    cfg = _cfg(tmp_path)
    ledger.cache_raw("m1", "same", "one", cfg=cfg)
    ledger.cache_raw("m2", "same", "two", cfg=cfg)  # same hash, different model -> separate file
    assert ledger.read_raw("m1", "same", cfg=cfg) == "one"
    assert ledger.read_raw("m2", "same", cfg=cfg) == "two"


def test_read_raw_missing_raises(tmp_path):
    cfg = _cfg(tmp_path)
    with pytest.raises(FileNotFoundError):
        ledger.read_raw("nope", "nope", cfg=cfg)
