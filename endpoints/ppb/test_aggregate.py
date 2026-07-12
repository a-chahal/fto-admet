"""Tests for the ppb aggregator: one ``fraction_bound`` feature, scored by the trained fusion spec.

Synthetic ``OutputRecord``-shaped inputs (laptop, core env - no box, no GPU). They pin the science that
is the aggregator's real job - gathering + harmonizing the three native scales - and leave the exact
fused number to ``tests/test_fusion.py`` (a trained spec now produces score + conformal interval):
- the three native scales harmonize onto fraction_bound: OCHEM/ADMET-AI ``% / 100``, OPERA ``1 - FuB``
  (the inversion landmine - UP = more bound);
- each source keeps its native ``raw`` value + ``raw_unit``, and its harmonized ``value`` is preserved;
- when the spec's calibrated source is present a score + interval EXIST (not asserted to an exact value);
- any empty / no-source subset is tolerated (score None).
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
    assert f.score is not None and f.uncertainty is not None   # trained spec -> calibrated score + interval


def test_opera_fub_is_inverted_to_fraction_bound():
    """The landmine: FuB = 0.29 means 71% BOUND, not 29%."""
    f = _feature(aggregate({"m": [opera(0.29)]}).molecules[0])
    o = _src(f, "opera")
    assert o.value == 0.71                 # 1 - 0.29, NOT 0.29
    assert (o.raw, o.raw_unit) == (0.29, "fraction unbound")


def test_opera_fub_pred_key_alias_accepted():
    f = _feature(aggregate({"m": [opera(0.1, key="FuB_pred")]}).molecules[0])
    assert _src(f, "opera").value == 0.9


# -------------------------------------------------------------------------- spec-aware scoring
def test_all_three_sources_harmonized_and_scored():
    # The aggregator's real job: gather + harmonize the three native scales onto fraction_bound. The SCORE
    # is now produced by the trained fusion spec (exact value tested in tests/test_fusion.py), so assert the
    # sources are preserved (inversion + %/100 intact) and a calibrated score + interval exist.
    f = _feature(aggregate({"m": [ochem(66.94), admet_ai(66.0), opera(0.29)]}).molecules[0])
    assert f.n_sources == 3
    assert math.isclose(_src(f, "ochem_ppb").value, 0.6694)
    assert _src(f, "admet_ai").value == 0.66
    assert _src(f, "opera").value == 0.71                 # the inversion survives harmonization
    assert f.score is not None and f.uncertainty is not None


def test_score_and_interval_exist_across_source_mixes():
    # Under the trained spec the interval is the spec's conformal width, not the raw disagreement std, so
    # convergent vs divergent inputs are not asserted to differ here (that lives in tests/test_fusion.py);
    # both mixes still yield a calibrated score + interval.
    tight = _feature(aggregate({"m": [ochem(90.0), admet_ai(90.0), opera(0.1)]}).molecules[0])
    wide = _feature(aggregate({"m": [ochem(90.0), admet_ai(10.0), opera(0.9)]}).molecules[0])
    for f in (tight, wide):
        assert f.score is not None and f.uncertainty is not None


# -------------------------------------------------------------------------- subsets / graceful fallbacks
def test_single_spec_source_is_scored():
    # admet_ai is the spec's calibrated source: a single admet_ai read still yields a score + interval
    # (raw harmonized source preserved; the exact fused number lives in tests/test_fusion.py).
    f = _feature(aggregate({"m": [admet_ai(66.0)]}).molecules[0])
    assert _src(f, "admet_ai").value == 0.66       # raw harmonized source preserved
    assert f.score is not None and f.uncertainty is not None
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
    assert by["a"] < by["b"]        # calibration is monotone increasing: more % bound still ranks higher


def test_input_shapes_normalize_the_same():
    recs = [admet_ai(66.0)]
    as_map = aggregate({"FTO-43": recs}).molecules[0]
    as_pairs = aggregate([("FTO-43", recs)]).molecules[0]
    as_dicts = aggregate([{"mol_id": "FTO-43", "records": recs}]).molecules[0]
    scores = [_feature(m).score for m in (as_map, as_pairs, as_dicts)]
    assert len(set(scores)) == 1        # same input -> same fused score across all input shapes
    for m in (as_map, as_pairs, as_dicts):
        assert m.mol_id == "FTO-43"
        assert _feature(m).score is not None
