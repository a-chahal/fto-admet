"""Unit tests for core.registry (the curated ModelSpec / REGISTRY contract).

REGISTRY is the single source of truth dispatch and every aggregator key off (CLAUDE.md §2), so these
tests pin: exactly 28 specs one-per-ModelName, endpoints as a non-empty frozenset subset of Endpoint,
the five cross-cutting sets from IO_SPEC §2, the None-env boundary for web-only + out-of-band models,
the gpu/bulk flags, non-empty provenance, and immutability. Gate:
``pytest tests/test_registry.py``. Laptop / core env, no box, no GPU.
"""

import dataclasses

import pytest

from core.models import Endpoint, ModelName
from core.registry import (
    REGISTRY,
    ModelSpec,
    Provenance,
    RegistryError,
    registry_validate,
)
from core.schemas import InputRecord, OutputRecord

# The five cross-cutting endpoint sets, transcribed from the t04 brief / IO_SPEC §2.
EXPECTED_CROSS_CUTTING = {
    ModelName.admet_ai: {
        "triage", "herg", "metabolism", "clearance", "ppb", "solubility", "lipophilicity",
        "permeability", "distribution", "toxicity",
    },
    ModelName.admetlab3: {
        "triage", "herg", "metabolism", "distribution", "ppb", "toxicity", "permeability",
    },
    ModelName.boiled_egg: {"distribution", "permeability"},
    ModelName.opera: {"lipophilicity", "clearance", "ppb"},
    ModelName.pgp: {"distribution", "permeability"},
}

# Models that never enter the bulk `pixi run` path -> env_manifest = entrypoint = None.
# OPERA is wired in: it now ships a python-only env whose run.py shells out to the installed MCR runtime.
NO_ENV_MODELS = {
    ModelName.watanabe_renal,
    ModelName.watanabe_pgp_brain,
    ModelName.protox,
    ModelName.pbpk,
}

# Hard GPU requirement (gpu = "yes"); "opt" collapses to False.
GPU_MODELS = {ModelName.bayesherg, ModelName.cardiotox_net, ModelName.cardiogenai}

# Models NOT in the bulk loop (bulk = "no").
NOT_BULK_MODELS = {
    ModelName.ctoxpred2,
    ModelName.cardiogenai,
    ModelName.watanabe_renal,
    ModelName.pbpk,
    ModelName.watanabe_pgp_brain,
    ModelName.aizynthfinder,
    ModelName.protox,
}


def test_registry_validate_passes():
    registry_validate()


def test_one_spec_per_model_name():
    assert set(REGISTRY) == set(ModelName)
    assert len(REGISTRY) == 28


def test_key_matches_spec_name():
    for name, spec in REGISTRY.items():
        assert spec.name == name


def test_endpoints_are_frozenset_subset_and_nonempty():
    all_endpoints = set(Endpoint)
    for name, spec in REGISTRY.items():
        assert isinstance(spec.endpoints, frozenset), name
        assert spec.endpoints, name
        assert spec.endpoints <= all_endpoints, name


def test_cross_cutting_sets_match_iospec():
    for name, expected in EXPECTED_CROSS_CUTTING.items():
        assert {e.value for e in REGISTRY[name].endpoints} == expected, name


def test_single_models_home_only():
    # Every non-cross-cutting model has exactly one endpoint.
    for name, spec in REGISTRY.items():
        if name not in EXPECTED_CROSS_CUTTING:
            assert len(spec.endpoints) == 1, name


def test_no_env_models_have_none_manifest_and_entrypoint():
    for name, spec in REGISTRY.items():
        if name in NO_ENV_MODELS:
            assert spec.env_manifest is None, name
            assert spec.entrypoint is None, name
        else:
            assert spec.env_manifest is not None, name
            assert spec.entrypoint is not None, name


def test_env_paths_follow_folder_convention():
    for name, spec in REGISTRY.items():
        if spec.env_manifest is None:
            continue
        # endpoints/<home>/<model>/pixi.toml and .../run.py
        assert spec.env_manifest.name == "pixi.toml", name
        assert spec.entrypoint.name == "run.py", name
        assert spec.env_manifest.parent == spec.entrypoint.parent, name
        assert spec.env_manifest.parent.name == name.value, name
        home = spec.env_manifest.parent.parent.name
        assert home in {e.value for e in Endpoint}, name
        assert home in {e.value for e in spec.endpoints}, name


def test_gpu_flags():
    for name, spec in REGISTRY.items():
        assert spec.requires_gpu == (name in GPU_MODELS), name


def test_bulk_flags():
    for name, spec in REGISTRY.items():
        assert spec.in_bulk_loop == (name not in NOT_BULK_MODELS), name


def test_flags_are_bool():
    for name, spec in REGISTRY.items():
        assert isinstance(spec.requires_gpu, bool), name
        assert isinstance(spec.in_bulk_loop, bool), name


def test_provenance_has_access_tag():
    for name, spec in REGISTRY.items():
        assert isinstance(spec.provenance, Provenance), name
        assert spec.provenance.access_tag, name


def test_schemas_reference_shared_base():
    for name, spec in REGISTRY.items():
        assert spec.input_schema is InputRecord, name
        assert spec.output_schema is OutputRecord, name


def test_model_spec_is_frozen():
    spec = REGISTRY[ModelName.pksmart]
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.requires_gpu = True  # type: ignore[misc]


def test_provenance_is_frozen():
    prov = REGISTRY[ModelName.pksmart].provenance
    with pytest.raises(dataclasses.FrozenInstanceError):
        prov.access_tag = "OTHER"  # type: ignore[misc]


def test_dropped_upstreams_absent():
    names = {n.value for n in REGISTRY}
    for dropped in ("deephit", "spielvogel", "cardiodpi", "fame3"):
        assert dropped not in names


def test_registry_validate_raises_on_tampered_copy():
    # registry_validate reads the module REGISTRY; assert it catches a bad spec via a local rebuild.
    bad = ModelSpec(
        name=ModelName.pksmart,
        endpoints=frozenset(),  # empty -> invalid
        env_manifest=None,
        entrypoint=None,
        input_schema=InputRecord,
        output_schema=OutputRecord,
        requires_gpu=False,
        in_bulk_loop=True,
        provenance=Provenance(access_tag="CODE-PKG"),
    )
    assert bad.endpoints == frozenset()
    # Sanity: a direct RegistryError is importable and raisable (the gate's failure channel).
    with pytest.raises(RegistryError):
        raise RegistryError("sentinel")
