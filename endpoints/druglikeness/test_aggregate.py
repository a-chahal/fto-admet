"""Tests for the druglikeness aggregator: three separate single-source context features (NEVER a gate).

Synthetic ``OutputRecord``-shaped inputs (laptop, core env - no box, no GPU). They pin:
- lipinski_violations is a single numeric source (score = the count, no interval);
- veber_pass carries the native boolean in reads but has NO fused score (a boolean has no mean);
- qed is a single numeric source (score = the value);
- missing flags yield empty features (no crash, no fabricated zeros); the accepted input shapes normalize
  the same; multiple molecules stay independent.

Output shape (per feature): score, unit, interval[low,high], reads{model:harmonized}, raw{model:native},
uncertainty{model_type:value}.
"""

from __future__ import annotations

from core.models import Endpoint, ModelName
from endpoints.druglikeness.aggregate import LIPINSKI, QED, VEBER, aggregate

PROV = {"model": "test"}


def lvq_rec(lipinski=None, veber=None, qed=None) -> dict:
    """A lipinski_veber_qed-shaped record: the three context flags in endpoint_values."""
    ev: dict = {}
    if lipinski is not None:
        ev["Lipinski_violations"] = lipinski
    if veber is not None:
        ev["Veber_pass"] = veber
    if qed is not None:
        ev["QED"] = qed
    return {"model": ModelName.lipinski_veber_qed, "endpoint_values": ev,
            "uncertainty": None, "raw": {}, "provenance": PROV}


def _feat(mol, name):
    return next(f for f in mol.features if f.feature == name)


# -------------------------------------------------------------------------- lipinski: single numeric source
def test_lipinski_violations_single_numeric_source():
    f = _feat(aggregate({"m": [lvq_rec(lipinski=1)]}).molecules[0], LIPINSKI)
    assert f.score == 1.0 and f.interval is None         # single source -> value, no spread
    assert f.reads == {"lipinski_veber_qed": 1.0}


def test_zero_violations_is_a_value_not_absent():
    f = _feat(aggregate({"m": [lvq_rec(lipinski=0)]}).molecules[0], LIPINSKI)
    assert f.score == 0.0 and f.reads == {"lipinski_veber_qed": 0.0}   # 0 is meaningful, not dropped


# -------------------------------------------------------------------------- veber: boolean, score deferred
def test_veber_pass_carries_boolean_with_deferred_score():
    f = _feat(aggregate({"m": [lvq_rec(veber=True)]}).molecules[0], VEBER)
    assert f.score is None and f.interval is None        # a boolean has no mean
    assert f.reads["lipinski_veber_qed"] is True         # native boolean carried in reads


def test_veber_false_is_carried_not_dropped():
    f = _feat(aggregate({"m": [lvq_rec(veber=False)]}).molecules[0], VEBER)
    assert f.reads["lipinski_veber_qed"] is False


# -------------------------------------------------------------------------- qed: single numeric source
def test_qed_single_numeric_source():
    f = _feat(aggregate({"m": [lvq_rec(qed=0.734)]}).molecules[0], QED)
    assert f.score == 0.734 and f.interval is None
    assert f.reads == {"lipinski_veber_qed": 0.734}


# -------------------------------------------------------------------------- three features, uniform shape
def test_three_features_and_uniform_shape():
    res = aggregate({"m": [lvq_rec(lipinski=1, veber=True, qed=0.734)]})
    assert res.endpoint == Endpoint.druglikeness and res.n_molecules == 1
    mol = res.molecules[0]
    assert {f.feature for f in mol.features} == {LIPINSKI, VEBER, QED}
    assert set(type(mol).model_fields) == {"endpoint", "mol_id", "features"}
    assert set(type(mol.features[0]).model_fields) == {
        "feature", "score", "unit", "interval", "reads", "raw", "uncertainty"}


def test_missing_signals_yield_empty_features_no_crash():
    # only an unrelated record: all three features present but empty (no crash, no fabricated values)
    rec = {"model": ModelName.bayesherg, "endpoint_values": {"P_block": 0.5},
           "uncertainty": None, "raw": {}, "provenance": PROV}
    mol = aggregate({"m": [rec]}).molecules[0]
    for f in mol.features:
        assert f.reads == {} and f.score is None


def test_none_valued_flags_are_dropped_not_fabricated():
    rec = {"model": ModelName.lipinski_veber_qed,
           "endpoint_values": {"Lipinski_violations": None, "Veber_pass": None, "QED": None},
           "uncertainty": None, "raw": {}, "provenance": PROV}
    mol = aggregate({"m": [rec]}).molecules[0]
    for f in mol.features:
        assert f.reads == {} and f.score is None


# -------------------------------------------------------------------------- normalization / independence
def test_input_shapes_normalize_the_same():
    recs = [lvq_rec(qed=0.5)]
    as_map = aggregate({"FTO-43": recs}).molecules[0]
    as_pairs = aggregate([("FTO-43", recs)]).molecules[0]
    as_dicts = aggregate([{"mol_id": "FTO-43", "records": recs}]).molecules[0]
    for m in (as_map, as_pairs, as_dicts):
        assert m.mol_id == "FTO-43"
        assert _feat(m, QED).score == 0.5


def test_multiple_molecules_independent():
    res = aggregate({"a": [lvq_rec(qed=0.1)], "b": [lvq_rec(qed=0.9)]})
    by = {m.mol_id: _feat(m, QED).score for m in res.molecules}
    assert by == {"a": 0.1, "b": 0.9}
