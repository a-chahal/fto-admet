"""Unit tests for core.run (run ONE endpoint: enumerate -> dispatch each -> aggregate; + CLI).

Hermetic and laptop-only: ``dispatch.run_model`` and the dynamic aggregator load are mocked, so no real
model, env, box, or GPU is touched. The registry itself is real (it is a pure, in-process contract), so
the enumeration assertions exercise the actual ``in_bulk_loop`` / ``endpoints`` membership rules.
Gate: ``pixi run pytest tests/test_run.py -q``.
"""

import json

import pytest

from core import run
from core.models import Endpoint, ModelName
from core.registry import REGISTRY
from core.run import EndpointResult, run_endpoint, select_models
from core.schemas import OutputRecord


def _rec(name: ModelName) -> OutputRecord:
    """A minimal valid OutputRecord for the given model."""
    return OutputRecord(model=name, provenance={"stub": True})


def _record_dispatch(monkeypatch, *, fail: set[ModelName] | None = None):
    """Replace dispatch.run_model with a fake that records which models it was asked to run.

    Returns the ``dispatched`` list (in call order). Any model in ``fail`` raises DispatchError, standing
    in for a model whose subprocess failed (already ledgered inside the real run_model).
    """
    fail = fail or set()
    dispatched: list[ModelName] = []

    def fake_run_model(name, input, out_dir, *, config=None):
        dispatched.append(name)
        if name in fail:
            raise run.DispatchError(f"{name}: boom")
        return _rec(name)

    monkeypatch.setattr(run.dispatch, "run_model", fake_run_model)
    return dispatched


# --------------------------------------------------------------------------- model selection
def test_select_models_herg_is_exactly_the_bulk_loop_models():
    # hERG bulk-loop members: the two GPU ensemble models plus the two cross-cutting generalists.
    names = {s.name for s in select_models(Endpoint.herg)}
    assert names == {
        ModelName.bayesherg, ModelName.cardiotox_net, ModelName.admet_ai, ModelName.admetlab3,
    }
    # the non-bulk hERG models are excluded (shortlist / gated), never enumerated
    assert ModelName.ctoxpred2 not in names
    assert ModelName.cardiogenai not in names


def test_select_models_excludes_web_only_and_shortlist_everywhere():
    """No endpoint's bulk enumeration may ever include a non-bulk model."""
    non_bulk = {name for name, spec in REGISTRY.items() if not spec.in_bulk_loop}
    for ep in Endpoint:
        selected = {s.name for s in select_models(ep)}
        assert selected.isdisjoint(non_bulk), f"{ep}: leaked a non-bulk model {selected & non_bulk}"


def test_select_models_all_selected_are_bulk_and_member():
    for ep in Endpoint:
        for spec in select_models(ep):
            assert spec.in_bulk_loop
            assert ep in spec.endpoints


# --------------------------------------------------------------------------- cross-cutting membership
def test_cross_cutting_model_dispatched_under_each_of_its_endpoints(monkeypatch):
    # admet_ai feeds many endpoints; it must be dispatched under each one it belongs to.
    monkeypatch.setattr(run, "load_aggregator", lambda ep: None)
    for ep in (Endpoint.triage, Endpoint.herg, Endpoint.toxicity):
        dispatched = _record_dispatch(monkeypatch)
        run_endpoint(ep, {"smiles": "CC(=O)O"}, out="/tmp/ignored")
        assert ModelName.admet_ai in dispatched, f"admet_ai missing under {ep}"


# --------------------------------------------------------------------------- run_endpoint enumeration
def test_run_endpoint_dispatches_exactly_selected_models(monkeypatch):
    monkeypatch.setattr(run, "load_aggregator", lambda ep: None)
    dispatched = _record_dispatch(monkeypatch)

    result = run_endpoint(Endpoint.herg, {"smiles": "c1ccccc1"}, out="/tmp/ignored")

    assert set(dispatched) == {s.name for s in select_models(Endpoint.herg)}
    assert {r.model for r in result.records} == set(dispatched)
    assert result.failures == []


# --------------------------------------------------------------------------- missing aggregator
def test_run_endpoint_missing_aggregator_returns_records_and_note(monkeypatch):
    # Every endpoint now ships an aggregator, so simulate the absent-aggregator case at the seam.
    monkeypatch.setattr(run, "load_aggregator", lambda ep: None)
    _record_dispatch(monkeypatch)

    result = run_endpoint(Endpoint.herg, {"smiles": "c1ccccc1"}, out="/tmp/ignored")

    assert isinstance(result, EndpointResult)
    assert result.aggregate is None
    assert result.note is not None and "no aggregator" in result.note
    assert len(result.records) == len(select_models(Endpoint.herg))


# --------------------------------------------------------------------------- aggregator invoked
def test_run_endpoint_calls_aggregator_with_collected_records(monkeypatch):
    _record_dispatch(monkeypatch)
    seen: dict = {}

    def fake_aggregate(records):
        seen["records"] = records
        return {"fused": len(records)}

    monkeypatch.setattr(run, "load_aggregator", lambda ep: fake_aggregate)

    result = run_endpoint(Endpoint.herg, {"smiles": "c1ccccc1"}, out="/tmp/ignored")

    assert seen["records"] == result.records
    assert result.aggregate == {"fused": len(result.records)}
    assert result.note is None


# --------------------------------------------------------------------------- a model failing is tolerated
def test_run_endpoint_records_failures_but_keeps_going(monkeypatch):
    monkeypatch.setattr(run, "load_aggregator", lambda ep: None)
    dispatched = _record_dispatch(monkeypatch, fail={ModelName.bayesherg})

    result = run_endpoint(Endpoint.herg, {"smiles": "c1ccccc1"}, out="/tmp/ignored")

    # every selected model was still attempted
    assert set(dispatched) == {s.name for s in select_models(Endpoint.herg)}
    # the failing one is not in records, but is recorded as a failure
    assert ModelName.bayesherg not in {r.model for r in result.records}
    assert [m for m, _ in result.failures] == [ModelName.bayesherg]


# --------------------------------------------------------------------------- load_aggregator seam
def test_load_aggregator_absent_endpoint_is_none(monkeypatch):
    # An endpoint whose aggregate.py module is absent resolves to None, never raises. Every endpoint now
    # ships an aggregator, so simulate the absent-module case at the import seam.
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    assert run.load_aggregator(Endpoint.herg) is None


# --------------------------------------------------------------------------- CLI
def test_cli_endpoint_runs_and_prints_summary(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(run, "load_aggregator", lambda ep: None)
    dispatched = _record_dispatch(monkeypatch)
    inp = tmp_path / "in.json"
    inp.write_text(json.dumps({"smiles": "CC(=O)O"}))

    rc = run.main(["--endpoint", "herg", "--input", str(inp), "--out", str(tmp_path / "o")])

    assert rc == 0
    assert set(dispatched) == {s.name for s in select_models(Endpoint.herg)}
    out = json.loads(capsys.readouterr().out)
    assert out["endpoint"] == "herg"
    assert set(out["models"]) == {m.value for m in dispatched}
    assert out["failures"] == []


def test_cli_endpoint_nonzero_exit_on_failure(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(run, "load_aggregator", lambda ep: None)
    _record_dispatch(monkeypatch, fail={ModelName.bayesherg})
    inp = tmp_path / "in.json"
    inp.write_text(json.dumps({"smiles": "CC(=O)O"}))

    rc = run.main(["--endpoint", "herg", "--input", str(inp), "--out", str(tmp_path / "o")])

    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["failures"] and out["failures"][0]["model"] == ModelName.bayesherg.value


def test_cli_single_model_dispatches_only_that_model(monkeypatch, tmp_path, capsys):
    dispatched = _record_dispatch(monkeypatch)
    inp = tmp_path / "in.json"
    inp.write_text(json.dumps({"smiles": "CC(=O)O"}))

    rc = run.main(["--model", "admet_ai", "--input", str(inp), "--out", str(tmp_path / "o")])

    assert rc == 0
    assert dispatched == [ModelName.admet_ai]  # exactly one model, no endpoint enumeration
    out = json.loads(capsys.readouterr().out)
    assert out["model"] == ModelName.admet_ai.value


def test_cli_single_model_failure_exits_nonzero(monkeypatch, tmp_path, capsys):
    _record_dispatch(monkeypatch, fail={ModelName.admet_ai})
    inp = tmp_path / "in.json"
    inp.write_text(json.dumps({"smiles": "CC(=O)O"}))

    rc = run.main(["--model", "admet_ai", "--input", str(inp), "--out", str(tmp_path / "o")])

    assert rc == 1
    assert "fail" in capsys.readouterr().err


def test_cli_requires_endpoint_or_model(tmp_path):
    inp = tmp_path / "in.json"
    inp.write_text(json.dumps({"smiles": "CC(=O)O"}))
    with pytest.raises(SystemExit):
        run.main(["--input", str(inp)])
