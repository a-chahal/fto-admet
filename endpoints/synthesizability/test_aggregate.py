"""Tests for the synthesizability aggregator: two separate single-source features, two entities.

Synthetic ``OutputRecord``-shaped inputs (laptop, core env - no box, no GPU). They pin:
- synthetic_complexity carries the SAscore read as a single source (LOWER = easier, in the unit string);
- route_findability carries the RAscore read as a single source, a SEPARATE entity from complexity;
- the two are never averaged into one number: each is its own feature with its own single-source score;
- any subset (only one source, or none) is tolerated with no fabricated values.

Output shape (per feature): score, unit, interval[low,high], reads{model:harmonized}, raw{model:native},
uncertainty{model_type:value}.
"""

from __future__ import annotations

from core.models import Endpoint, ModelName
from endpoints.synthesizability.aggregate import COMPLEXITY, FINDABILITY, aggregate

PROV = {"model": "test"}


def sascore(v: float) -> dict:
    return {"model": ModelName.sascore, "endpoint_values": {"SAscore": v},
            "uncertainty": None, "raw": {}, "provenance": PROV}


def rascore(v: float) -> dict:
    return {"model": ModelName.rascore, "endpoint_values": {"RAscore": v},
            "uncertainty": None, "raw": {}, "provenance": PROV}


def _feat(mol, name):
    return next(f for f in mol.features if f.feature == name)


# -------------------------------------------------------------------------- synthetic complexity (SAscore)
def test_synthetic_complexity_is_single_source_from_sascore():
    f = _feat(aggregate({"m": [sascore(2.5)]}).molecules[0], COMPLEXITY)
    assert f.score == 2.5
    assert f.interval is None               # one source -> no spread
    assert f.reads == {"sascore": 2.5}
    assert "down = easier" in f.unit        # the inversion is recorded in the unit


# -------------------------------------------------------------------------- route findability (RAscore)
def test_route_findability_is_single_source_from_rascore():
    f = _feat(aggregate({"m": [rascore(0.8)]}).molecules[0], FINDABILITY)
    assert f.score == 0.8
    assert f.interval is None
    assert f.reads == {"rascore": 0.8}


# -------------------------------------------------------------------------- two entities, never fused
def test_two_separate_features_never_averaged():
    mol = aggregate({"m": [sascore(2.0), rascore(0.9)]}).molecules[0]
    comp = _feat(mol, COMPLEXITY)
    find = _feat(mol, FINDABILITY)
    # each entity keeps its own value on its own scale; no combined/averaged number exists.
    assert comp.score == 2.0
    assert find.score == 0.9
    assert "rascore" not in comp.reads
    assert "sascore" not in find.reads


# -------------------------------------------------------------------------- subsets / graceful fallbacks
def test_missing_rascore_leaves_findability_empty():
    mol = aggregate({"m": [sascore(3.0)]}).molecules[0]
    assert _feat(mol, COMPLEXITY).score == 3.0
    find = _feat(mol, FINDABILITY)
    assert find.score is None and find.reads == {}


def test_missing_sascore_leaves_complexity_empty():
    mol = aggregate({"m": [rascore(0.7)]}).molecules[0]
    comp = _feat(mol, COMPLEXITY)
    assert comp.score is None and comp.reads == {}
    assert _feat(mol, FINDABILITY).score == 0.7


def test_no_source_yields_null_scores_no_crash():
    rec = {"model": ModelName.bayesherg, "endpoint_values": {"P_block": 0.5},
           "uncertainty": None, "raw": {}, "provenance": PROV}
    mol = aggregate({"m": [rec]}).molecules[0]
    for f in mol.features:
        assert f.score is None and f.interval is None and f.reads == {}


def test_nonnumeric_value_is_not_a_source():
    recs = [{"model": ModelName.sascore, "endpoint_values": {"SAscore": None},
             "uncertainty": None, "raw": {}, "provenance": PROV}]
    f = _feat(aggregate({"m": recs}).molecules[0], COMPLEXITY)
    assert f.reads == {} and f.score is None


# -------------------------------------------------------------------------- shape / plumbing
def test_endpoint_identity_and_uniform_shape():
    res = aggregate({"m": [sascore(2.5), rascore(0.8)]})
    assert res.endpoint == Endpoint.synthesizability and res.n_molecules == 1
    mol = res.molecules[0]
    assert mol.endpoint == Endpoint.synthesizability and mol.mol_id == "m"
    assert {f.feature for f in mol.features} == {COMPLEXITY, FINDABILITY}
    assert set(type(mol).model_fields) == {"endpoint", "mol_id", "features"}
    assert set(type(mol.features[0]).model_fields) == {
        "feature", "score", "unit", "interval", "reads", "raw", "uncertainty"}


def test_multiple_molecules_independent():
    res = aggregate({"a": [sascore(2.0)], "b": [sascore(8.0)]})
    by = {m.mol_id: _feat(m, COMPLEXITY).score for m in res.molecules}
    assert by == {"a": 2.0, "b": 8.0}


def test_input_shapes_normalize_the_same():
    recs = [sascore(2.5), rascore(0.8)]
    as_map = aggregate({"FTO-43": recs}).molecules[0]
    as_pairs = aggregate([("FTO-43", recs)]).molecules[0]
    as_dicts = aggregate([{"mol_id": "FTO-43", "records": recs}]).molecules[0]
    for m in (as_map, as_pairs, as_dicts):
        assert m.mol_id == "FTO-43"
        assert _feat(m, COMPLEXITY).score == 2.5
        assert _feat(m, FINDABILITY).score == 0.8
