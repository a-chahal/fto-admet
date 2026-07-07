"""Run exactly ONE model in its isolated env: the only place in the pipeline that shells out.

Because each model lives in its own pixi env with mutually incompatible deps (CLAUDE.md §0/§2), core
cannot import a model - it builds a command string and runs a subprocess. :func:`run_model` is generic
and *singular*: it does not grow with the number of models. Adding a model is a registry entry plus a
folder, never an edit here (SETTLED §6).

The pipeline it implements, per model, is fixed:

    validate input  ->  resolve env  ->  (gpu?)  ->  subprocess  ->  collect + validate output  ->  ledger

Two rules from the box's execution model are honored directly (CLAUDE.md §1, SETTLED §7):

- The GPU pick and the job that uses it ride the **same** invocation. ``CUDA_VISIBLE_DEVICES=N`` is set
  in the subprocess's own environment (its own process, atomically), never in a prior separate step that
  a fresh shell would forget, and the device is also passed as ``--gpu N`` on the uniform adapter CLI.
- The ledger record is written here, at completion, with the real ``input_hash`` and ``env_lock_hash``.
  Every terminal outcome (ok **or** fail) is recorded; a failure is never swallowed - it is both
  recorded as ``status=fail`` and re-raised as :class:`DispatchError`.

Web-only and out-of-band-runtime models (``env_manifest is None``: OPERA/MATLAB, PBPK/R+.NET, the
WEB-ONLY tools) are refused here: they run via their README SOP and are transcribed to the ledger by
hand, not driven through ``pixi run``.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from core import gpu, ledger
from core.config import Config, _parse_dotenv, get_config
from core.models import ModelName
from core.registry import REGISTRY, ModelSpec
from core.schemas import OutputRecord, validate_input, validate_output

# The uniform adapter CLI (CLAUDE.md §2): every model's run.py reads --input, writes --output, and
# optionally honors --gpu. dispatch builds this one command for every model.
_PIXI = "pixi"

# Repo root, used to find the .env whose machine config (e.g. OPERA_HOME / MCR_ROOT for the out-of-band
# OPERA runtime) is passed through to model subprocesses.
_REPO_ROOT = Path(__file__).resolve().parent.parent


class DispatchError(RuntimeError):
    """A model run could not be dispatched or completed.

    Raised for a refused web-only model, an unavailable GPU, a non-zero (or un-launchable) subprocess,
    or a missing / schema-invalid output. For the run-time failures (the last two, plus an unavailable
    GPU) a ``status=fail`` ledger record is written *before* this is raised, so the failure is recorded
    on the box regardless of whether the caller catches it.
    """


def build_command(spec: ModelSpec, in_path: Path, out_path: Path, gpu_index: int | None) -> list[str]:
    """Build the ``pixi run`` argv for one model. Pure and singular, so the command is unit-assertable.

    ``pixi run --manifest-path <env_manifest> python <entrypoint> --input <in> --output <out>`` plus
    ``--gpu <N>`` when a device was picked. ``spec.env_manifest`` / ``spec.entrypoint`` must be set;
    callers refuse the ``None`` (web-only) case before reaching here.
    """
    if spec.env_manifest is None or spec.entrypoint is None:
        raise DispatchError(f"{spec.name}: env_manifest/entrypoint is None; cannot build a run command")
    cmd = [
        _PIXI, "run", "--manifest-path", str(spec.env_manifest),
        "python", str(spec.entrypoint),
        "--input", str(in_path),
        "--output", str(out_path),
    ]
    if gpu_index is not None:
        cmd += ["--gpu", str(gpu_index)]
    return cmd


def _lock_hash(spec: ModelSpec) -> str | None:
    """sha256 of the model's committed ``pixi.lock`` (next to its ``pixi.toml``), or ``None`` if absent.

    The lock is solved on the box and committed (CLAUDE.md §0); when present its hash is the exact env
    fingerprint. ``None`` (not a fabricated digest) is recorded when it is not yet on disk, honoring the
    no-fabricate rule rather than inventing an env identity.
    """
    assert spec.env_manifest is not None  # guarded by build_command / caller
    lock = spec.env_manifest.parent / "pixi.lock"
    return ledger.hash_env_lock(lock) if lock.exists() else None


def run_model(
    name: ModelName,
    input: Any,
    output_dir: str | os.PathLike[str],
    *,
    config: Config | None = None,
) -> OutputRecord:
    """Run one model end to end and return its validated :class:`OutputRecord`.

    Steps (SETTLED §6): resolve ``spec = REGISTRY[name]``; validate ``input`` against
    ``spec.input_schema`` **before** launching; refuse web-only models (``env_manifest is None``); pick
    and claim a GPU when ``spec.requires_gpu``; shell out the uniform ``pixi run`` command with the
    device set in that same call; collect and validate the output against ``spec.output_schema``; append
    an ``ok`` ledger record. Any run-time failure writes a ``fail`` ledger record and raises
    :class:`DispatchError` - it is never swallowed.

    Args:
        name: registry key of the model to run.
        input: input payload (dict or ``InputRecord``); validated before any subprocess launches.
        output_dir: directory for this model's ``--input`` / ``--output`` files (created if missing).
        config: injected machine paths (ledger + locks); defaults to the process ``Config``.

    Raises:
        DispatchError: web-only model, no GPU available, subprocess non-zero / un-launchable, or a
            missing / schema-invalid output.
    """
    cfg = config if config is not None else get_config()
    spec = REGISTRY[name]

    # env_manifest is None => web-only / out-of-band. It runs via its README SOP, not this bulk loop.
    if spec.env_manifest is None:
        raise DispatchError(
            f"{name} is web-only / out-of-band ({spec.provenance.access_tag}); it has no pixi env and "
            f"is run via its README SOP and transcribed to the ledger by hand, not through run_model."
        )

    # Validate input BEFORE spawning anything (a bad input never reaches a subprocess).
    record = validate_input(input)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    in_path = out_dir / f"{name.value}.input.json"
    out_path = out_dir / f"{name.value}.output.json"
    in_path.write_text(record.model_dump_json(), encoding="utf-8")

    input_hash = ledger.hash_input(record.smiles)
    env_lock_hash = _lock_hash(spec)

    def _fail(cuda_device: int | None, reason: str) -> None:
        ledger.append(
            ledger.new_record(
                model=name.value,
                input_hash=input_hash,
                output_path=str(out_path),
                env_lock_hash=env_lock_hash,
                cuda_device=cuda_device,
                status="fail",
                note=reason,
            ),
            path=cfg.ledger,
        )

    # GPU models: pick fresh + hold the soft lock for the run (CLAUDE.md §1); CPU models skip the path.
    if spec.requires_gpu:
        gpu_index = gpu.pick_free_gpu(config=cfg)
        if gpu_index is None:
            reason = f"no free GPU available for {name} (all devices busy or locked)"
            _fail(None, reason)
            raise DispatchError(reason)
        gpu_ctx: Any = gpu.claim(gpu_index, config=cfg)
    else:
        gpu_index = None
        gpu_ctx = contextlib.nullcontext()

    cmd = build_command(spec, in_path, out_path, gpu_index)
    run_env = dict(os.environ)
    # Machine config from the repo .env (e.g. OPERA_HOME / MCR_ROOT for the out-of-band OPERA runtime) is
    # made available to the model subprocess; the real environment always wins over the file.
    for _k, _v in _parse_dotenv(_REPO_ROOT / ".env").items():
        run_env.setdefault(_k, _v)
    if gpu_index is not None:
        # Same invocation as the pick (mirrors the one-ssh-connection rule): the env var lives in the
        # subprocess's own process, so no fresh shell can forget it.
        run_env["CUDA_VISIBLE_DEVICES"] = str(gpu_index)

    with gpu_ctx:
        try:
            proc = subprocess.run(cmd, env=run_env, capture_output=True, text=True)
        except FileNotFoundError as exc:
            # pixi missing / env won't resolve at the binary level.
            reason = f"failed to launch {name}: {exc}"
            _fail(gpu_index, reason)
            raise DispatchError(reason) from exc

        if proc.returncode != 0:
            reason = f"{name} exited {proc.returncode}: {(proc.stderr or '').strip()[:500]}"
            _fail(gpu_index, reason)
            raise DispatchError(reason)

        if not out_path.exists():
            reason = f"{name} exited 0 but wrote no output at {out_path}"
            _fail(gpu_index, reason)
            raise DispatchError(reason)

        try:
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            output = spec.output_schema.model_validate(payload)
        except Exception as exc:
            # A malformed or wrong-shape/wrong-unit output must fail here, not silently propagate.
            reason = f"{name} output failed {spec.output_schema.__name__} validation: {exc}"
            _fail(gpu_index, reason)
            raise DispatchError(reason) from exc

    ledger.append(
        ledger.new_record(
            model=name.value,
            input_hash=input_hash,
            output_path=str(out_path),
            env_lock_hash=env_lock_hash,
            cuda_device=gpu_index,
            status="ok",
        ),
        path=cfg.ledger,
    )
    return output


def run_model_batch(
    name: ModelName,
    inputs: list[Any],
    output_dir: str | os.PathLike[str],
    *,
    config: Config | None = None,
) -> list[OutputRecord]:
    """Dispatch ONE model over a batch of molecules in a SINGLE subprocess (the model loads once).

    The speed path for screening many molecules: instead of dispatching a model once per molecule (which
    reloads its weights every time), the whole batch is written as a JSON array and the adapter runs once
    (every adapter accepts an array and emits one record per input, in order). Returns the validated records
    aligned positionally to ``inputs``. Web-only / out-of-band models are refused like :func:`run_model`;
    a GPU is claimed once for the batch; any run-time failure writes one ``fail`` ledger record and raises.
    """
    cfg = config if config is not None else get_config()
    spec = REGISTRY[name]
    if spec.env_manifest is None:
        raise DispatchError(
            f"{name} is web-only / out-of-band ({spec.provenance.access_tag}); it has no pixi env and is "
            f"run via its README SOP, not through run_model_batch."
        )
    if not inputs:
        return []

    records = [validate_input(x) for x in inputs]
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    in_path = out_dir / f"{name.value}.batch.input.json"
    out_path = out_dir / f"{name.value}.batch.output.json"
    in_path.write_text(json.dumps([r.model_dump(mode="json") for r in records]), encoding="utf-8")

    input_hash = ledger.hash_input("|".join(r.smiles for r in records))
    env_lock_hash = _lock_hash(spec)

    def _fail(cuda_device: int | None, reason: str) -> None:
        ledger.append(
            ledger.new_record(model=name.value, input_hash=input_hash, output_path=str(out_path),
                              env_lock_hash=env_lock_hash, cuda_device=cuda_device, status="fail", note=reason),
            path=cfg.ledger,
        )

    if spec.requires_gpu:
        gpu_index = gpu.pick_free_gpu(config=cfg)
        if gpu_index is None:
            reason = f"no free GPU available for {name} (all devices busy or locked)"
            _fail(None, reason)
            raise DispatchError(reason)
        gpu_ctx: Any = gpu.claim(gpu_index, config=cfg)
    else:
        gpu_index = None
        gpu_ctx = contextlib.nullcontext()

    cmd = build_command(spec, in_path, out_path, gpu_index)
    run_env = dict(os.environ)
    for _k, _v in _parse_dotenv(_REPO_ROOT / ".env").items():
        run_env.setdefault(_k, _v)
    if gpu_index is not None:
        run_env["CUDA_VISIBLE_DEVICES"] = str(gpu_index)

    with gpu_ctx:
        try:
            proc = subprocess.run(cmd, env=run_env, capture_output=True, text=True)
        except FileNotFoundError as exc:
            reason = f"failed to launch {name}: {exc}"
            _fail(gpu_index, reason)
            raise DispatchError(reason) from exc
        if proc.returncode != 0:
            reason = f"{name} exited {proc.returncode}: {(proc.stderr or '').strip()[:500]}"
            _fail(gpu_index, reason)
            raise DispatchError(reason)
        if not out_path.exists():
            reason = f"{name} exited 0 but wrote no output at {out_path}"
            _fail(gpu_index, reason)
            raise DispatchError(reason)
        try:
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload = [payload]
            outputs = [spec.output_schema.model_validate(item) for item in payload]
        except Exception as exc:
            reason = f"{name} batch output failed {spec.output_schema.__name__} validation: {exc}"
            _fail(gpu_index, reason)
            raise DispatchError(reason) from exc

    if len(outputs) != len(records):
        reason = f"{name} returned {len(outputs)} records for {len(records)} inputs (adapter did not batch 1:1)"
        _fail(gpu_index, reason)
        raise DispatchError(reason)

    ledger.append(
        ledger.new_record(model=name.value, input_hash=input_hash, output_path=str(out_path),
                          env_lock_hash=env_lock_hash, cuda_device=gpu_index, status="ok"),
        path=cfg.ledger,
    )
    return outputs
