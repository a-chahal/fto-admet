"""Cross-cutting integration tests: the frozen ``core`` contract before the model swarm (t09 gate).

Per-module unit tests already pin each module in isolation. This file pins the *seams between them* -
the contract ~40 downstream model / aggregator tasks build against - so a schema, registry, or wiring
drift is caught here (one fix) instead of poisoning every later smoke test. It touches only the public
``core`` surface and never edits ``core``: if an assertion here fails, the owning t01-t08 task is the
one to fix (this task BLOCKs and names the failing test).

Coherence frozen here:
- models <-> registry: ``ModelName`` and ``REGISTRY`` are a bijection (27 specs, one each).
- registry <-> Endpoint: every spec's ``endpoints`` is a non-empty subset of ``Endpoint``; the four
  cross-cutting sets match IO_SPEC §2; every endpoint is reachable by at least one bulk-loop model.
- registry env boundary: web-only + OPERA + PBPK carry ``None`` env/entrypoint; every other model has
  both, under ``endpoints/<home>/<model>/``.
- schemas <-> registry: every spec points at the shared ``InputRecord`` / ``OutputRecord`` base, both
  instantiate against the FTO-43 fixture, and the §3 uncertainty / AD envelope fields are reserved.
- dispatch <-> registry: ``build_command`` builds for every env-backed model and refuses every None one.
- run <-> registry <-> dispatch: ``run_endpoint`` enumerates exactly ``select_models(ep)`` per endpoint
  (dispatch + aggregator mocked), and a cross-cutting model is dispatched under each endpoint it feeds.
- packaging: ``core`` and every submodule import, and ``registry_validate()`` is green.

Gate: ``pixi run pytest tests/ -m "not model" -q``. Laptop / core env, no box, no GPU.
"""

from __future__ import annotations

import importlib

import pytest

from core import run
from core.dispatch import DispatchError, build_command
from core.models import Endpoint, ModelName
from core.registry import REGISTRY, registry_validate
from core.run import run_endpoint, select_models
from core.schemas import (
    InputRecord,
    OutputRecord,
    Uncertainty,
    validate_input,
    validate_output,
)

# The four cross-cutting endpoint sets (IO_SPEC §2), as plain strings, transcribed independently of the
# registry module so this is a real check, not a tautology against the same literal.
EXPECTED_CROSS_CUTTING = {
    ModelName.admet_ai: {
        "triage", "herg", "metabolism", "clearance", "ppb", "solubility", "lipophilicity",
        "permeability", "distribution", "toxicity",
    },
    ModelName.boiled_egg: {"distribution", "permeability"},
    ModelName.opera: {"lipophilicity", "clearance", "ppb"},
    ModelName.pgp: {"distribution", "permeability"},
}

# Models that never enter the bulk `pixi run` path -> env_manifest = entrypoint = None.
# OPERA is wired in: it ships a python-only env whose run.py shells out to the installed MCR runtime.
EXPECTED_NO_ENV = {
    ModelName.watanabe_renal,
    ModelName.watanabe_pgp_brain,
    ModelName.protox,
    ModelName.pbpk,
    ModelName.pgp,  # DERIVED: efflux read from admet_ai in the aggregator, never dispatched (no env)
}


# --------------------------------------------------------------------------- models <-> registry
def test_registry_validate_is_green():
    """The gate's own structural check: the registry is internally consistent."""
    registry_validate()  # raises RegistryError on any violation


def test_modelname_and_registry_are_a_bijection():
    assert set(REGISTRY) == set(ModelName)
    assert len(REGISTRY) == len(ModelName) == 26
    for name, spec in REGISTRY.items():
        assert spec.name == name, name


# --------------------------------------------------------------------------- registry <-> Endpoint
def test_every_spec_endpoints_are_nonempty_subset_of_endpoint():
    all_endpoints = set(Endpoint)
    for name, spec in REGISTRY.items():
        assert isinstance(spec.endpoints, frozenset), name
        assert spec.endpoints, name
        assert spec.endpoints <= all_endpoints, name


def test_four_cross_cutting_sets_present_and_exact():
    for name, expected in EXPECTED_CROSS_CUTTING.items():
        assert name in REGISTRY, name
        assert {e.value for e in REGISTRY[name].endpoints} == expected, name


def test_every_endpoint_reachable_by_at_least_one_bulk_model():
    """No endpoint may be a dead branch: the bulk loop must select >=1 model for each one."""
    for ep in Endpoint:
        selected = select_models(ep)
        assert selected, f"endpoint {ep.value} has no bulk-loop model (run_endpoint would be empty)"


# --------------------------------------------------------------------------- registry env boundary
def test_env_and_entrypoint_boundary_matches_none_set():
    for name, spec in REGISTRY.items():
        if name in EXPECTED_NO_ENV:
            assert spec.env_manifest is None, name
            assert spec.entrypoint is None, name
        else:
            assert spec.env_manifest is not None, name
            assert spec.entrypoint is not None, name
            # endpoints/<home>/<model>/{pixi.toml,run.py}
            assert spec.env_manifest.name == "pixi.toml", name
            assert spec.entrypoint.name == "run.py", name
            assert spec.env_manifest.parent == spec.entrypoint.parent, name
            assert spec.env_manifest.parent.name == name.value, name


def test_env_manifest_and_entrypoint_are_set_together():
    for name, spec in REGISTRY.items():
        assert (spec.env_manifest is None) == (spec.entrypoint is None), name


# --------------------------------------------------------------------------- schemas <-> registry
def test_every_spec_uses_the_shared_schema_base():
    for name, spec in REGISTRY.items():
        assert spec.input_schema is InputRecord, name
        assert spec.output_schema is OutputRecord, name


def test_input_schema_instantiates_from_fto43_fixture(fto43_input):
    for name, spec in REGISTRY.items():
        rec = spec.input_schema.model_validate(fto43_input)
        assert isinstance(rec, InputRecord)
        assert rec.smiles == fto43_input["smiles"], name
        assert rec.mol_id == fto43_input["mol_id"], name


def test_output_schema_instantiates_for_every_model():
    for name in REGISTRY:
        rec = validate_output({"model": name.value, "provenance": {"stub": True}})
        assert isinstance(rec, OutputRecord)
        assert rec.model == name


def test_uncertainty_envelope_reserves_ad_and_uncertainty_fields():
    """§3 schema rule: the AD / uncertainty fields exist from day one so no adapter is retrofitted."""
    reserved = set(Uncertainty.model_fields)
    assert {
        "aleatoric", "epistemic", "fold_error_low", "fold_error_high",
        "confidence", "ad_in_domain", "ad_index", "conf_index", "extra",
    } <= reserved
    # an empty envelope is valid (a model emitting no native signal)
    assert Uncertainty().model_dump()["extra"] == {}


def test_output_record_reserves_envelope_shape():
    fields = set(OutputRecord.model_fields)
    assert {"model", "endpoint_values", "uncertainty", "raw", "provenance"} <= fields
    rec = OutputRecord(model=ModelName.pksmart, provenance={"ok": True})
    assert rec.endpoint_values == {} and rec.raw == {} and rec.uncertainty is None


def test_input_record_rejects_empty_smiles():
    with pytest.raises(Exception):  # pydantic ValidationError
        validate_input({"smiles": "   "})


# --------------------------------------------------------------------------- dispatch <-> registry
def test_build_command_works_for_every_env_model_and_refuses_none(tmp_path):
    in_path = tmp_path / "in.json"
    out_path = tmp_path / "out.json"
    for name, spec in REGISTRY.items():
        if spec.env_manifest is None:
            with pytest.raises(DispatchError):
                build_command(spec, in_path, out_path, None)
        else:
            cmd = build_command(spec, in_path, out_path, None)
            assert cmd[:3] == ["pixi", "run", "--manifest-path"], name
            assert str(spec.env_manifest) in cmd and str(spec.entrypoint) in cmd, name
            assert cmd[-4:] == ["--input", str(in_path), "--output", str(out_path)], name


# --------------------------------------------------------------------------- run enumeration (mocked)
def _mock_dispatch(monkeypatch):
    """Replace dispatch + aggregator with hermetic fakes; return the list of dispatched model names."""
    dispatched: list[ModelName] = []

    def fake_run_model(name, input, out_dir, *, config=None):
        dispatched.append(name)
        return OutputRecord(model=name, provenance={"stub": True})

    monkeypatch.setattr(run.dispatch, "run_model", fake_run_model)
    monkeypatch.setattr(run, "load_aggregator", lambda ep: None)
    return dispatched


def test_run_endpoint_enumerates_exactly_selected_models_for_every_endpoint(monkeypatch, tmp_path, fto43_input):
    for ep in Endpoint:
        dispatched = _mock_dispatch(monkeypatch)
        result = run_endpoint(ep, fto43_input, out=tmp_path / ep.value)
        expected = {s.name for s in select_models(ep)}
        assert set(dispatched) == expected, ep
        assert {r.model for r in result.records} == expected, ep
        assert result.failures == [], ep


def test_cross_cutting_model_dispatched_under_each_of_its_endpoints(monkeypatch, tmp_path, fto43_input):
    for name, spec in REGISTRY.items():
        if name not in EXPECTED_CROSS_CUTTING or not spec.in_bulk_loop:
            continue
        for ep in spec.endpoints:
            dispatched = _mock_dispatch(monkeypatch)
            run_endpoint(ep, fto43_input, out=tmp_path / f"{name.value}-{ep.value}")
            assert name in dispatched, f"{name} not dispatched under {ep}"


# --------------------------------------------------------------------------- packaging / importability
CORE_SUBMODULES = (
    "core.config", "core.models", "core.schemas", "core.registry",
    "core.gpu", "core.ledger", "core.dispatch", "core.run",
)


def test_core_package_and_submodules_import():
    core = importlib.import_module("core")
    assert hasattr(core, "get_config")
    for mod in CORE_SUBMODULES:
        assert importlib.import_module(mod) is not None, mod


# --------------------------------------------------------------------------- fixture sanity
def test_fto43_fixture_is_a_valid_input_record(fto43, fto43_input):
    rec = validate_input(fto43_input)
    assert rec.smiles and rec.mol_id == fto43.mol_id
    # the placeholder is honestly surfaced, not silently trusted as the real structure
    assert fto43.cid == 164886650
    assert isinstance(fto43.smiles_is_placeholder, bool)
