"""Tests for the ppb aggregator: one ``fraction_bound`` feature, score = mean, uncertainty = std.

Synthetic ``OutputRecord``-shaped inputs (laptop, core env - no box, no GPU). They pin the science that
must survive the shape change:
- the three native scales harmonize onto fraction_bound: OCHEM/ADMET-AI ``% / 100``, OPERA ``1 - FuB``
  (the inversion landmine - UP = more bound);
- score = equally-weighted mean of the harmonized values, uncertainty = std over the same values;
- each source keeps its native ``raw`` value + ``raw_unit``;
- any subset (single source -> uncertainty None; none -> score None) is tolerated.
"""

from __future__ import annotations

import math

from core.models import Endpoint, ModelName
from endpoints.ppb.aggregate import FEATURE, aggregate

PROV = {"model": "test"}


def ochem(pct_bound: float, key: str = "ppb_percent_bound") -> dict:
    return {"model": ModelName.ochem_ppb, "endpoint_values": {key: pct_bound},
            "uncertainty": None, "raw": {}, "provenance": PROV}


def admet_ai(pct_bound: float) -> dict:
    return {"model": ModelName.admet_ai, "endpoint_values": {"PPBR_AZ": pct_bound},
            "uncertainty": None, "raw": {}, "provenance": PROV}


def opera(fub: float, key: str = "FuB") -> dict:
    return {"model": ModelName.opera, "endpoint_values": {key: fub},
            "uncertainty": None, "raw": {}, "provenance": PROV}


def _feature(mol):
    assert len(mol.features) == 1
    f = mol.features[0]
    assert f.feature == FEATURE
    return f


def _src(feature, model):
    return next(s for s in feature.sources if s.model == model)


# -------------------------------------------------------------------------- the three harmonizations
def test_percent_sources_divide_by_100_and_keep_raw():
    f = _feature(aggregate({"m": [ochem(87.3), admet_ai(66.0)]}).molecules[0])
    o, a = _src(f, "ochem_ppb"), _src(f, "admet_ai")
    assert math.isclose(o.value, 0.873)
    assert (o.raw, o.raw_unit) == (87.3, "% bound")
    assert a.value == 0.66 and (a.raw, a.raw_unit) == (66.0, "% bound")


def test_opera_fub_is_inverted_to_fraction_bound():
    """The landmine: FuB = 0.29 means 71% BOUND, not 29%."""
    f = _feature(aggregate({"m": [opera(0.29)]}).molecules[0])
    o = _src(f, "opera")
    assert o.value == 0.71                 # 1 - 0.29, NOT 0.29
    assert (o.raw, o.raw_unit) == (0.29, "fraction unbound")


def test_opera_fub_pred_key_alias_accepted():
    f = _feature(aggregate({"m": [opera(0.1, key="FuB_pred")]}).molecules[0])
    assert _src(f, "opera").value == 0.9


# -------------------------------------------------------------------------- score = mean, uncertainty = std
def test_score_is_mean_and_uncertainty_is_std_over_harmonized_values():
    f = _feature(aggregate({"m": [ochem(66.94), admet_ai(66.0), opera(0.29)]}).molecules[0])
    vals = [0.6694, 0.66, 0.71]                 # the three harmonized fraction_bound values
    mean = sum(vals) / 3
    var = sum((x - mean) ** 2 for x in vals) / 3
    assert f.n_sources == 3
    assert abs(f.score - mean) < 1e-9
    assert abs(f.uncertainty - math.sqrt(var)) < 1e-9   # population std over the same values


def test_convergent_sources_have_low_uncertainty_divergent_high():
    tight = _feature(aggregate({"m": [ochem(90.0), admet_ai(90.0), opera(0.1)]}).molecules[0])
    wide = _feature(aggregate({"m": [ochem(90.0), admet_ai(10.0), opera(0.9)]}).molecules[0])
    assert tight.uncertainty < wide.uncertainty   # std is the disagreement signal


# -------------------------------------------------------------------------- subsets / graceful fallbacks
def test_single_source_has_score_but_no_uncertainty():
    f = _feature(aggregate({"m": [admet_ai(66.0)]}).molecules[0])
    assert f.score == 0.66
    assert f.uncertainty is None          # disagreement is undefined for one source
    assert f.n_sources == 1


def test_no_ppb_source_yields_null_score_no_crash():
    f = _feature(aggregate({"m": [{"model": ModelName.bayesherg, "endpoint_values": {"P_block": 0.5},
                                   "uncertainty": None, "raw": {}, "provenance": PROV}]}).molecules[0])
    assert f.score is None and f.uncertainty is None and f.n_sources == 0


def test_missing_or_nonnumeric_value_is_not_a_source():
    # a % key present but null, and a non-numeric string, both drop out (never a fabricated 0)
    recs = [ochem(87.3), {"model": ModelName.admet_ai, "endpoint_values": {"PPBR_AZ": None},
                          "uncertainty": None, "raw": {}, "provenance": PROV}]
    f = _feature(aggregate({"m": recs}).molecules[0])
    assert [s.model for s in f.sources] == ["ochem_ppb"]


# -------------------------------------------------------------------------- shape / plumbing
def test_endpoint_identity_and_shape():
    res = aggregate({"m": [ochem(66.94)]})
    assert res.endpoint == Endpoint.ppb and res.n_molecules == 1
    mol = res.molecules[0]
    assert mol.endpoint == Endpoint.ppb and mol.mol_id == "m"
    # uniform shape only: no consensus/spread_flag/confident/notes fields survive
    assert set(type(mol).model_fields) == {"endpoint", "mol_id", "features"}
    assert set(type(mol.features[0]).model_fields) == {"feature", "score", "uncertainty", "unit", "n_sources", "sources"}


def test_multiple_molecules_independent():
    res = aggregate({"a": [admet_ai(20.0)], "b": [admet_ai(80.0)]})
    by = {m.mol_id: _feature(m).score for m in res.molecules}
    assert by == {"a": 0.2, "b": 0.8}


def test_input_shapes_normalize_the_same():
    recs = [admet_ai(66.0)]
    as_map = aggregate({"FTO-43": recs}).molecules[0]
    as_pairs = aggregate([("FTO-43", recs)]).molecules[0]
    as_dicts = aggregate([{"mol_id": "FTO-43", "records": recs}]).molecules[0]
    for m in (as_map, as_pairs, as_dicts):
        assert m.mol_id == "FTO-43"
        assert _feature(m).score == 0.66
