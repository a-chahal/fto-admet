"""Phase-1 gate: prove the subprocess pattern + folder template hold on two real models (t12).

This is the checkpoint before Phase 2 fans out ~26 models. It certifies, on the **laptop / core env**
(no box, no GPU), that the two models already built - a trivial rule model (``rdkit_crippen``, t10) and
the first genuinely isolated env (``pksmart``, t11) - are wired into the frozen ``core`` contract the
same way, so the rest of the swarm can copy them safely. The per-model **box smokes were already
verified at t10/t11** (their model-kind gates checked the box-solved lock + smoke against FTO-43);
this file adds only the laptop-runnable integration layer and deliberately does NOT re-run box smokes.

What is asserted here (the five checks of the t12 brief), against the registry + a mocked dispatch:
1. Both models are in ``REGISTRY`` with the right ``endpoints``, ``in_bulk_loop=True``, and non-``None``
   ``env_manifest`` / ``entrypoint`` paths that **exist on disk**.
2. Each model folder conforms to the template: ``pixi.toml`` / ``pixi.lock`` / ``run.py`` / ``README.md``
   present, and ``run.py`` exposes the uniform ``--input`` / ``--output`` / ``--gpu`` CLI (parsed from the
   adapter's own argparse via ``ast`` - no box env is imported).
3. ``dispatch.run_model`` (subprocess mocked to echo a schema-shaped payload) validates and returns an
   ``OutputRecord`` for each, and a failing subprocess writes a ``status=fail`` ledger record.
4. ``run_endpoint(lipophilicity)`` includes ``rdkit_crippen`` and ``run_endpoint(clearance)`` includes
   ``pksmart`` (the exact ``select_models`` contract, and the model actually dispatched).
5. PKSmart's output round-trips through ``core.schemas`` including the reserved ``Uncertainty`` envelope
   (PKSmart emits a native CL fold-error, so ``fold_error_low`` / ``fold_error_high`` + the per-parameter
   fold factor in ``extra`` must survive validation).

Gate: ``pixi run pytest tests/test_phase1_integration.py -q`` green. This is a GATE, not a model task:
it never edits ``core`` or a model. If a check fails because a t10/t11 artifact is wrong, the gate BLOCKs
and names the offending model + defect so that model's task is revisited (t12 brief, "Blocked if").
"""

from __future__ import annotations

import ast
import json
import types
from pathlib import Path

import pytest

from core import dispatch, ledger, run
from core.dispatch import DispatchError
from core.models import Endpoint, ModelName
from core.registry import REGISTRY
from core.run import run_endpoint, select_models
from core.schemas import OutputRecord, validate_output

REPO_ROOT = Path(__file__).resolve().parent.parent

# The two models this gate certifies, each with the endpoint it is expected to feed and its folder. The
# endpoint is the model's single home endpoint (neither is cross-cutting), so it must be exactly this set.
CERTIFIED = {
    ModelName.rdkit_crippen: Endpoint.lipophilicity,
    ModelName.pksmart: Endpoint.clearance,
}

# Files every model folder must carry (the template t12 certifies; CLAUDE.md §5 model done-criteria).
TEMPLATE_FILES = ("pixi.toml", "pixi.lock", "run.py", "README.md")

# The uniform adapter CLI (CLAUDE.md §2): --input and --output are required; --gpu is present on every
# adapter (accepted and ignored by the CPU-only ones) so dispatch builds one command for all models.
REQUIRED_FLAGS = {"--input", "--output"}
UNIFORM_FLAGS = {"--input", "--output", "--gpu"}


def _cli_flags(run_py: Path) -> set[str]:
    """Parse an adapter's argparse statically and return its long option strings.

    Uses ``ast`` rather than importing / executing ``run.py``: the adapter imports its isolated-env deps
    (rdkit, pksmart) at module top, which the core env cannot import, so a static parse is the only
    laptop-runnable way to read the CLI. Collects the first string literal of every ``add_argument`` call
    that begins with ``--``.
    """
    tree = ast.parse(run_py.read_text(encoding="utf-8"))
    flags: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.startswith("--"):
                    flags.add(arg.value)
    return flags


def _schema_payload(model: ModelName) -> dict:
    """A schema-shaped output payload mirroring what each real adapter emits (for the mocked subprocess).

    rdkit_crippen is a deterministic descriptor (``uncertainty=None``); pksmart emits the reserved
    uncertainty envelope with a CL fold-error interval + the per-parameter fold factor in ``extra``. Both
    are validated against the real ``core.schemas.OutputRecord`` by dispatch, so a drift in the shared
    schema would fail here.
    """
    if model is ModelName.rdkit_crippen:
        return {
            "model": model.value,
            "endpoint_values": {"logP_crippen": 1.23, "MR": 45.6},
            "uncertainty": None,
            "raw": {"smiles": "CC(=O)O"},
            "provenance": {"model": model.value, "method": "Crippen"},
        }
    return {
        "model": model.value,
        "endpoint_values": {
            "CL_mL_min_kg": 12.0,
            "VDss_L_kg": 1.5,
            "t_half_h": 6.0,
            "fu": 0.2,
            "MRT_h": 8.0,
        },
        "uncertainty": {
            "fold_error_low": 6.0,
            "fold_error_high": 24.0,
            "ad_in_domain": True,
            "extra": {"cl_fold_error": 2.0, "ad_alert": ""},
        },
        "raw": {"smiles": "CC(=O)O"},
        "provenance": {"model": model.value, "method": "PKSmart two-stage RF"},
    }


def _ok_subprocess(cmd, env=None, **kwargs):
    """Fake ``subprocess.run`` that writes the schema-shaped payload for the dispatched model and exits 0.

    The model is recovered from the ``--output`` filename (``<name>.output.json``) exactly as the real
    dispatcher names it, so one fake serves both models.
    """
    out = Path(cmd[cmd.index("--output") + 1])
    model = ModelName(out.name.split(".")[0])
    out.write_text(json.dumps(_schema_payload(model)), encoding="utf-8")
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")


def _fail_subprocess(cmd, env=None, **kwargs):
    """Fake ``subprocess.run`` that exits non-zero and writes nothing (drives the fail-ledger path)."""
    return types.SimpleNamespace(returncode=3, stdout="", stderr="isolated env blew up")


# --------------------------------------------------------------------------- 1. registry membership
@pytest.mark.parametrize("model, endpoint", list(CERTIFIED.items()))
def test_model_registered_with_expected_wiring(model: ModelName, endpoint: Endpoint):
    """Both models are in the registry with the right endpoint, bulk-loop opt-in, and on-disk paths."""
    assert model in REGISTRY, f"{model.value} missing from REGISTRY"
    spec = REGISTRY[model]
    assert spec.name == model
    assert spec.endpoints == frozenset({endpoint}), (
        f"{model.value} endpoints {set(spec.endpoints)} != expected {{{endpoint.value}}}"
    )
    assert spec.in_bulk_loop is True, f"{model.value} must be in the bulk loop"
    assert spec.env_manifest is not None and spec.entrypoint is not None, f"{model.value} has None env/entrypoint"
    assert spec.env_manifest.exists(), f"{model.value} pixi.toml missing on disk: {spec.env_manifest}"
    assert spec.entrypoint.exists(), f"{model.value} run.py missing on disk: {spec.entrypoint}"
    # the registry anchors the folder at endpoints/<home>/<model>/
    assert spec.env_manifest.parent.name == model.value
    assert spec.env_manifest.parent.parent.name == endpoint.value


# --------------------------------------------------------------------------- 2. folder template + CLI
@pytest.mark.parametrize("model", list(CERTIFIED))
def test_model_folder_conforms_to_template(model: ModelName):
    """Every template file is present and run.py exposes the uniform --input/--output[/--gpu] CLI."""
    model_dir = REGISTRY[model].env_manifest.parent
    for fname in TEMPLATE_FILES:
        assert (model_dir / fname).exists(), f"{model.value}: template file {fname} missing"

    flags = _cli_flags(model_dir / "run.py")
    missing = REQUIRED_FLAGS - flags
    assert not missing, f"{model.value}: run.py CLI missing required flags {missing} (has {flags})"
    assert UNIFORM_FLAGS <= flags, (
        f"{model.value}: run.py must expose the uniform {UNIFORM_FLAGS} CLI (has {flags})"
    )


# --------------------------------------------------------------------------- 3. dispatch round-trip
@pytest.mark.parametrize("model", list(CERTIFIED))
def test_dispatch_run_model_validates_and_returns_output_record(model, tmp_config, fto43_input, monkeypatch):
    """Mocked subprocess -> schema-shaped payload -> dispatch validates -> OutputRecord + ok ledger line."""
    monkeypatch.setattr(dispatch.subprocess, "run", _ok_subprocess)

    record = dispatch.run_model(model, fto43_input, tmp_config.outputs, config=tmp_config)

    assert isinstance(record, OutputRecord)
    assert record.model == model
    recs = ledger.load(path=tmp_config.ledger)
    assert len(recs) == 1 and recs[0]["status"] == "ok" and recs[0]["model"] == model.value


@pytest.mark.parametrize("model", list(CERTIFIED))
def test_dispatch_failure_writes_fail_ledger_record(model, tmp_config, fto43_input, monkeypatch):
    """A non-zero subprocess raises DispatchError and records a single status=fail ledger line."""
    monkeypatch.setattr(dispatch.subprocess, "run", _fail_subprocess)

    with pytest.raises(DispatchError, match="exited 3"):
        dispatch.run_model(model, fto43_input, tmp_config.outputs, config=tmp_config)

    recs = ledger.load(path=tmp_config.ledger)
    assert len(recs) == 1
    assert recs[0]["status"] == "fail" and recs[0]["model"] == model.value


# --------------------------------------------------------------------------- 4. endpoint enumeration
@pytest.mark.parametrize("model, endpoint", list(CERTIFIED.items()))
def test_run_endpoint_selects_and_dispatches_model(model, endpoint, tmp_config, fto43_input, monkeypatch):
    """select_models(ep) includes the model, and run_endpoint actually dispatches it (aggregator mocked)."""
    assert model in {s.name for s in select_models(endpoint)}, (
        f"{model.value} not selected by run_endpoint({endpoint.value})"
    )

    dispatched: list[ModelName] = []

    def fake_run_model(name, input, out_dir, *, config=None):
        dispatched.append(name)
        return OutputRecord(model=name, provenance={"stub": True})

    monkeypatch.setattr(run.dispatch, "run_model", fake_run_model)
    monkeypatch.setattr(run, "load_aggregator", lambda ep: None)

    result = run_endpoint(endpoint, fto43_input, out=tmp_config.outputs / endpoint.value, config=tmp_config)
    assert model in dispatched, f"{model.value} not dispatched under {endpoint.value}"
    assert model in {r.model for r in result.records}
    assert result.failures == []


# --------------------------------------------------------------------------- 5. pksmart uncertainty round-trip
def test_pksmart_output_round_trips_with_uncertainty():
    """PKSmart's fold-error must survive validation into the reserved Uncertainty envelope (schema §3)."""
    payload = _schema_payload(ModelName.pksmart)
    record = validate_output(payload)

    assert record.model == ModelName.pksmart
    assert record.uncertainty is not None, "PKSmart emits a fold-error; Uncertainty must round-trip"
    lo = record.uncertainty.fold_error_low
    hi = record.uncertainty.fold_error_high
    assert isinstance(lo, float) and isinstance(hi, float) and 0.0 <= lo <= hi, f"bad fold interval [{lo}, {hi}]"
    cl = record.endpoint_values["CL_mL_min_kg"]
    assert lo <= cl <= hi, f"CL {cl} not inside its own fold-error interval [{lo}, {hi}]"
    assert "cl_fold_error" in record.uncertainty.extra, "the CL fold factor must survive in Uncertainty.extra"
