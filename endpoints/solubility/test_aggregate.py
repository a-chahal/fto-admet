"""Tests for the solubility aggregator: two SEPARATE single-source entities (log S and SFI).

Synthetic ``OutputRecord``-shaped inputs (laptop, core env - no box, no GPU). They pin the science that
must survive the shape change:
- aqueous_solubility (admet_ai Solubility_AqSolDB, log S, up = more soluble) is its own feature;
- formulation_risk (sfi SFI, down = more soluble / lower risk) is a DIFFERENT entity, never fused with logS;
- each is single-source: the trained aqueous spec calibrates + attaches an interval; untrained SFI passes through;
- the two are never averaged, co-ranked, or negated into a shared scale;
- missing/non-numeric lenses drop out (no fabricated values), and any subset is tolerated.

Output shape (per feature): score, unit, interval[low,high], reads{model:harmonized}, raw{model:native},
uncertainty{model_type:value}. Exact fused values are pinned in tests/test_fusion.py.
"""

from __future__ import annotations

from core.models import Endpoint, ModelName
from endpoints.solubility.aggregate import AQUEOUS, FORMULATION, aggregate

PROV = {"model": "test"}


def sfi_rec(sfi: float) -> dict:
    return {"model": ModelName.sfi, "endpoint_values": {"SFI": sfi},
            "uncertainty": None, "raw": {}, "provenance": PROV}


def admet_ai(logs: float) -> dict:
    return {"model": ModelName.admet_ai, "endpoint_values": {"Solubility_AqSolDB": logs},
            "uncertainty": None, "raw": {}, "provenance": PROV}


def _feat(mol, name):
    return next(f for f in mol.features if f.feature == name)


# -------------------------------------------------------------------------- aqueous solubility (log S)
def test_aqueous_solubility_gathers_admet_ai_read():
    f = _feat(aggregate({"m": [admet_ai(-4.2)]}).molecules[0], AQUEOUS)
    assert f.reads == {"admet_ai": -4.2}                        # harmonized read preserved
    assert f.score is not None and f.interval is not None       # trained -> calibrated logS + conformal interval
    assert f.unit == "log(mol/L) (up = more soluble)"


# -------------------------------------------------------------------------- formulation risk (SFI)
def test_formulation_risk_is_single_source_sfi():
    f = _feat(aggregate({"m": [sfi_rec(5.0)]}).molecules[0], FORMULATION)
    assert f.score == 5.0 and f.interval is None                # untrained SFI -> equal-weight passthrough, no interval
    assert f.reads == {"sfi": 5.0}
    assert "down = more soluble" in f.unit


# -------------------------------------------------------------------------- the two entities stay separate
def test_sfi_and_logs_are_separate_features_never_fused():
    mol = aggregate({"m": [sfi_rec(5.0), admet_ai(-4.2)]}).molecules[0]
    aq = _feat(mol, AQUEOUS)
    fr = _feat(mol, FORMULATION)
    assert set(aq.reads) == {"admet_ai"}                        # SFI is NOT co-ranked/averaged into logS
    assert set(fr.reads) == {"sfi"}
    assert aq.reads["admet_ai"] == -4.2 and fr.score == 5.0


def test_two_features_and_uniform_shape():
    res = aggregate({"m": [sfi_rec(5.0), admet_ai(-4.2)]})
    assert res.endpoint == Endpoint.solubility and res.n_molecules == 1
    mol = res.molecules[0]
    assert mol.endpoint == Endpoint.solubility and mol.mol_id == "m"
    assert {f.feature for f in mol.features} == {AQUEOUS, FORMULATION}
    assert set(type(mol).model_fields) == {"endpoint", "mol_id", "features"}
    assert set(type(mol.features[0]).model_fields) == {
        "feature", "score", "unit", "interval", "reads", "raw", "uncertainty"}


# -------------------------------------------------------------------------- subsets / graceful fallbacks
def test_missing_lens_yields_empty_feature_no_crash():
    mol = aggregate({"m": [admet_ai(-3.0)]}).molecules[0]
    assert "admet_ai" in _feat(mol, AQUEOUS).reads
    fr = _feat(mol, FORMULATION)
    assert fr.reads == {} and fr.score is None and fr.interval is None


def test_unrelated_record_yields_two_empty_features():
    rec = {"model": ModelName.bayesherg, "endpoint_values": {"P_block": 0.5},
           "uncertainty": None, "raw": {}, "provenance": PROV}
    mol = aggregate({"m": [rec]}).molecules[0]
    for f in mol.features:
        assert f.reads == {} and f.score is None


def test_nonnumeric_value_is_not_a_read():
    recs = [{"model": ModelName.sfi, "endpoint_values": {"SFI": None},
             "uncertainty": None, "raw": {}, "provenance": PROV}]
    fr = _feat(aggregate({"m": recs}).molecules[0], FORMULATION)
    assert fr.reads == {} and fr.score is None


# -------------------------------------------------------------------------- shape / plumbing
def test_multiple_molecules_independent():
    res = aggregate({"a": [admet_ai(-2.0)], "b": [admet_ai(-6.0)]})
    by = {m.mol_id: _feat(m, AQUEOUS).score for m in res.molecules}
    assert by["a"] > by["b"]        # the calibration is monotone increasing: higher logS still ranks higher


def test_input_shapes_normalize_the_same():
    recs = [sfi_rec(5.0), admet_ai(-4.2)]
    mols = [aggregate({"FTO-43": recs}).molecules[0],
            aggregate([("FTO-43", recs)]).molecules[0],
            aggregate([{"mol_id": "FTO-43", "records": recs}]).molecules[0]]
    scores = {_feat(m, AQUEOUS).score for m in mols}
    assert len(scores) == 1        # same input -> same fused score across all input shapes
    for m in mols:
        assert m.mol_id == "FTO-43" and _feat(m, FORMULATION).score == 5.0


def test_empty_input_yields_empty_verdict():
    res = aggregate([])
    assert res.molecules == [] and res.n_molecules == 0
