"""Unit tests for core.dispatch (run ONE model, generically; the only place core shells out).

Hermetic and laptop-only: ``subprocess.run`` and ``gpu.pick_free_gpu`` are mocked, so no real model,
env, box, or GPU is touched. Every case injects a tmp ``Config`` (standing in for ``/zfs``) so the
ledger and lock files land under ``tmp_path``, never the developer's real environment.
Gate: ``pixi run pytest tests/test_dispatch.py -q``.
"""

import json
import types
from pathlib import Path

import pytest

from core import dispatch, ledger
from core.config import load_config
from core.dispatch import DispatchError, build_command
from core.models import ModelName
from core.registry import REGISTRY
from core.schemas import OutputRecord

CPU_MODEL = ModelName.admet_ai        # requires_gpu=False, has an env
GPU_MODEL = ModelName.bayesherg       # requires_gpu=True, has an env
WEB_MODEL = ModelName.watanabe_renal  # env_manifest is None (web-only SOP)


def _cfg(tmp_path):
    return load_config(
        env={"FTO_ADMET_ROOT": str(tmp_path / "fto"), "FTO_ADMET_ENV_CACHE": str(tmp_path / "envs")},
        dotenv_path=tmp_path / "nope.env",
    )


def _ok_subprocess(record_seen):
    """A fake ``subprocess.run`` that writes a minimal valid OutputRecord and returns exit 0.

    Captures the argv and env it was called with into ``record_seen`` so a test can assert both. The
    model name is recovered from the ``--output`` filename (``<name>.output.json``), so the same fake
    serves any model.
    """
    def fake_run(cmd, env=None, **kwargs):
        record_seen["cmd"] = cmd
        record_seen["env"] = env
        out = Path(cmd[cmd.index("--output") + 1])
        model = out.name.split(".")[0]
        out.write_text(json.dumps({"model": model, "provenance": {"ok": True}}))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")
    return fake_run


def _fail_subprocess(returncode=1, stderr="boom", write_output=False):
    def fake_run(cmd, env=None, **kwargs):
        if write_output:
            out = Path(cmd[cmd.index("--output") + 1])
            out.write_text(json.dumps({"model": out.name.split(".")[0], "provenance": {}}))
        return types.SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)
    return fake_run


# --------------------------------------------------------------------------- command construction
def test_build_command_cpu_shape():
    spec = REGISTRY[CPU_MODEL]
    cmd = build_command(spec, Path("/t/in.json"), Path("/t/out.json"), None)
    assert cmd == [
        "pixi", "run", "--manifest-path", str(spec.env_manifest),
        "python", str(spec.entrypoint),
        "--input", "/t/in.json", "--output", "/t/out.json",
    ]
    assert "--gpu" not in cmd


def test_build_command_appends_gpu_flag():
    spec = REGISTRY[GPU_MODEL]
    cmd = build_command(spec, Path("/t/in.json"), Path("/t/out.json"), 3)
    assert cmd[-2:] == ["--gpu", "3"]


def test_build_command_refuses_none_manifest():
    spec = REGISTRY[WEB_MODEL]
    with pytest.raises(DispatchError):
        build_command(spec, Path("/t/in.json"), Path("/t/out.json"), None)


# --------------------------------------------------------------------------- happy path (CPU model)
def test_run_model_cpu_success_builds_command_and_appends_ok_ledger(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    seen: dict = {}
    monkeypatch.setattr(dispatch.subprocess, "run", _ok_subprocess(seen))

    out = dispatch.run_model(CPU_MODEL, {"smiles": "CC(=O)O"}, tmp_path / "out", config=cfg)

    assert isinstance(out, OutputRecord)
    spec = REGISTRY[CPU_MODEL]
    in_path = tmp_path / "out" / f"{CPU_MODEL.value}.input.json"
    out_path = tmp_path / "out" / f"{CPU_MODEL.value}.output.json"
    # exact pixi command, no --gpu for a CPU model
    assert seen["cmd"] == [
        "pixi", "run", "--manifest-path", str(spec.env_manifest),
        "python", str(spec.entrypoint),
        "--input", str(in_path), "--output", str(out_path),
    ]
    assert "CUDA_VISIBLE_DEVICES" not in seen["env"]  # CPU model never sets a device
    # the validated input was serialized for the adapter to read
    assert json.loads(in_path.read_text())["smiles"] == "CC(=O)O"

    recs = ledger.load(path=cfg.ledger)
    assert len(recs) == 1
    r = recs[0]
    assert r["status"] == "ok"
    assert r["model"] == CPU_MODEL.value
    assert r["cuda_device"] is None
    assert r["input_hash"] == ledger.hash_input("CC(=O)O")
    assert r["output_path"] == str(out_path)


# --------------------------------------------------------------------------- GPU model
def test_run_model_gpu_includes_device_in_command_and_env(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    seen: dict = {}
    monkeypatch.setattr(dispatch.subprocess, "run", _ok_subprocess(seen))
    monkeypatch.setattr(dispatch.gpu, "pick_free_gpu", lambda **kw: 2)

    dispatch.run_model(GPU_MODEL, {"smiles": "c1ccccc1"}, tmp_path / "out", config=cfg)

    assert seen["cmd"][-2:] == ["--gpu", "2"]              # device on the CLI
    assert seen["env"]["CUDA_VISIBLE_DEVICES"] == "2"      # and in the same invocation's env
    r = ledger.load(path=cfg.ledger)[0]
    assert r["status"] == "ok"
    assert r["cuda_device"] == 2


def test_run_model_gpu_none_available_fails_and_records(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    ran = {"called": False}

    def guard(*a, **k):
        ran["called"] = True
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(dispatch.subprocess, "run", guard)
    monkeypatch.setattr(dispatch.gpu, "pick_free_gpu", lambda **kw: None)

    with pytest.raises(DispatchError, match="no free GPU"):
        dispatch.run_model(GPU_MODEL, {"smiles": "c1ccccc1"}, tmp_path / "out", config=cfg)

    assert ran["called"] is False  # never launched without a device
    recs = ledger.load(path=cfg.ledger)
    assert len(recs) == 1 and recs[0]["status"] == "fail"


# --------------------------------------------------------------------------- web-only refusal
def test_run_model_refuses_web_only_model(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(dispatch.subprocess, "run", _ok_subprocess({}))
    with pytest.raises(DispatchError, match="SOP"):
        dispatch.run_model(WEB_MODEL, {"smiles": "CC(=O)O"}, tmp_path / "out", config=cfg)
    # nothing dispatched => no ledger line
    assert ledger.load(path=cfg.ledger) == []


# --------------------------------------------------------------------------- failure handling
def test_run_model_nonzero_subprocess_raises_and_records_fail(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(dispatch.subprocess, "run", _fail_subprocess(returncode=2, stderr="env broke"))

    with pytest.raises(DispatchError, match="exited 2"):
        dispatch.run_model(CPU_MODEL, {"smiles": "CC(=O)O"}, tmp_path / "out", config=cfg)

    recs = ledger.load(path=cfg.ledger)
    assert len(recs) == 1
    assert recs[0]["status"] == "fail"
    assert "env broke" in recs[0]["note"]


def test_run_model_missing_output_raises_and_records_fail(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    # exit 0 but writes no --output file
    monkeypatch.setattr(dispatch.subprocess, "run", _fail_subprocess(returncode=0, write_output=False))

    with pytest.raises(DispatchError, match="no output"):
        dispatch.run_model(CPU_MODEL, {"smiles": "CC(=O)O"}, tmp_path / "out", config=cfg)
    assert ledger.load(path=cfg.ledger)[0]["status"] == "fail"


def test_run_model_invalid_output_schema_raises_and_records_fail(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)

    def bad_output(cmd, env=None, **kwargs):
        out = Path(cmd[cmd.index("--output") + 1])
        out.write_text(json.dumps({"not": "an OutputRecord", "extra": 1}))  # missing model/provenance
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(dispatch.subprocess, "run", bad_output)

    with pytest.raises(DispatchError, match="validation"):
        dispatch.run_model(CPU_MODEL, {"smiles": "CC(=O)O"}, tmp_path / "out", config=cfg)
    assert ledger.load(path=cfg.ledger)[0]["status"] == "fail"


def test_run_model_launch_failure_raises_and_records_fail(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)

    def missing_pixi(*a, **k):
        raise FileNotFoundError("pixi")

    monkeypatch.setattr(dispatch.subprocess, "run", missing_pixi)
    with pytest.raises(DispatchError, match="failed to launch"):
        dispatch.run_model(CPU_MODEL, {"smiles": "CC(=O)O"}, tmp_path / "out", config=cfg)
    assert ledger.load(path=cfg.ledger)[0]["status"] == "fail"


# --------------------------------------------------------------------------- input validation
def test_run_model_rejects_bad_input_before_launch(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    ran = {"called": False}

    def guard(*a, **k):
        ran["called"] = True
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(dispatch.subprocess, "run", guard)
    with pytest.raises(Exception):  # pydantic ValidationError: empty smiles
        dispatch.run_model(CPU_MODEL, {"smiles": "   "}, tmp_path / "out", config=cfg)
    assert ran["called"] is False  # never launched a subprocess on bad input
    assert ledger.load(path=cfg.ledger) == []
