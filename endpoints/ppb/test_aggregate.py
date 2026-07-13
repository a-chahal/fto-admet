"""Tests for the ppb aggregator: one ``fraction_bound`` feature, scored by the trained fusion spec.

Synthetic ``OutputRecord``-shaped inputs (laptop, core env - no box, no GPU). They pin the science that
is the aggregator's real job - gathering + harmonizing the three native scales - and leave the exact
fused number to ``tests/test_fusion.py`` (a trained spec now produces score + conformal interval):
- the three native scales harmonize onto fraction_bound: OCHEM/ADMET-AI ``% / 100``, OPERA ``1 - FuB``
  (the inversion landmine - UP = more bound);
- each source keeps its native ``raw`` value (in ``raw``) and its harmonized ``value`` (in ``reads``);
- each model's native AD signals land in ``uncertainty`` (OCHEM distance-to-model + AD, OPERA conf/AD);
- when the spec's calibrated source is present a score + interval EXIST (not asserted to an exact value).

Output shape (per feature): score, unit, interval[low,high], reads{model:harmonized}, raw{model:native},
uncertainty{model_type:value}. Exact fused values are pinned in tests/test_fusion.py.
"""

from __future__ import annotations

import math

from core.models import Endpoint, ModelName
from endpoints.ppb.aggregate import FEATURE, aggregate

PROV = {"model": "test"}


def ochem(pct_bound: float, key: str = "ppb_percent_bound", *,
          ad_in_domain: bool | None = None, distance_to_model: float | None = None) -> dict:
    unc: dict | None = None
    if ad_in_domain is not None or distance_to_model is not None:
        unc = {"ad_in_domain": ad_in_domain, "extra": {"distance_to_model": distance_to_model}}
    return {"model": ModelName.ochem_ppb, "endpoint_values": {key: pct_bound},
            "uncertainty": unc, "raw": {}, "provenance": PROV}


def admet_ai(pct_bound: float) -> dict:
    return {"model": ModelName.admet_ai, "endpoint_values": {"PPBR_AZ": pct_bound},
            "uncertainty": None, "raw": {}, "provenance": PROV}


def opera(fub: float, key: str = "FuB", *, conf_index: float | None = None,
          ad_in_domain: bool | None = None) -> dict:
    # OPERA's per-endpoint AD/confidence lives in uncertainty.extra keyed by the endpoint name.
    extra: dict = {}
    if conf_index is not None:
        extra["FuB_conf_index"] = conf_index
    if ad_in_domain is not None:
        extra["FuB_ad_in_domain"] = ad_in_domain
    unc = {"extra": extra} if extra else None
    return {"model": ModelName.opera, "endpoint_values": {key: fub},
            "uncertainty": unc, "raw": {}, "provenance": PROV}


def _feature(mol):
    assert len(mol.features) == 1
    f = mol.features[0]
    assert f.feature == FEATURE
    return f


# -------------------------------------------------------------------------- the three harmonizations
def test_percent_sources_divide_by_100_and_keep_raw():
    f = _feature(aggregate({"m": [ochem(87.3), admet_ai(66.0)]}).molecules[0])
    assert math.isclose(f.reads["ochem_ppb"], 0.873)   # harmonized read
    assert f.raw["ochem_ppb"] == 87.3                  # native % bound
    assert f.reads["admet_ai"] == 0.66 and f.raw["admet_ai"] == 66.0
    assert f.score is not None and f.interval is not None   # trained spec -> calibrated score + interval


def test_opera_fub_is_inverted_to_fraction_bound():
    """The landmine: FuB = 0.29 means 71% BOUND, not 29%."""
    f = _feature(aggregate({"m": [opera(0.29)]}).molecules[0])
    assert f.reads["opera"] == 0.71   # 1 - 0.29, NOT 0.29
    assert f.raw["opera"] == 0.29     # native fraction unbound retained


def test_opera_fub_pred_key_alias_accepted():
    f = _feature(aggregate({"m": [opera(0.1, key="FuB_pred")]}).molecules[0])
    assert f.reads["opera"] == 0.9


def test_ochem_ad_signals_land_in_uncertainty():
    f = _feature(aggregate({"m": [ochem(66.94, ad_in_domain=True, distance_to_model=0.42)]}).molecules[0])
    assert f.uncertainty["ochem_ppb_ad_in_domain"] is True
    assert f.uncertainty["ochem_ppb_distance_to_model"] == 0.42


def test_opera_ad_signals_land_in_uncertainty():
    f = _feature(aggregate({"m": [opera(0.29, conf_index=0.6, ad_in_domain=False)]}).molecules[0])
    assert f.uncertainty["opera_conf_index"] == 0.6
    assert f.uncertainty["opera_ad_in_domain"] is False


# -------------------------------------------------------------------------- spec-aware scoring
def test_all_three_sources_harmonized_and_scored():
    # The aggregator's real job: gather + harmonize the three native scales onto fraction_bound. The SCORE
    # is now produced by the trained fusion spec (exact value tested in tests/test_fusion.py), so assert the
    # reads are preserved (inversion + %/100 intact) and a calibrated score + interval exist.
    f = _feature(aggregate({"m": [ochem(66.94), admet_ai(66.0), opera(0.29)]}).molecules[0])
    assert set(f.reads) == {"ochem_ppb", "admet_ai", "opera"}
    assert math.isclose(f.reads["ochem_ppb"], 0.6694)
    assert f.reads["admet_ai"] == 0.66
    assert f.reads["opera"] == 0.71                 # the inversion survives harmonization
    assert f.score is not None and f.interval is not None


def test_score_and_interval_exist_across_source_mixes():
    # Under the trained spec the interval is the spec's conformal width, not the raw disagreement std, so
    # convergent vs divergent inputs are not asserted to differ here (that lives in tests/test_fusion.py);
    # both mixes still yield a calibrated score + interval.
    tight = _feature(aggregate({"m": [ochem(90.0), admet_ai(90.0), opera(0.1)]}).molecules[0])
    wide = _feature(aggregate({"m": [ochem(90.0), admet_ai(10.0), opera(0.9)]}).molecules[0])
    for f in (tight, wide):
        assert f.score is not None and f.interval is not None


# -------------------------------------------------------------------------- subsets / graceful fallbacks
def test_single_spec_source_is_scored():
    # admet_ai is the spec's calibrated source: a single admet_ai read still yields a score + interval
    # (raw harmonized read preserved; the exact fused number lives in tests/test_fusion.py).
    f = _feature(aggregate({"m": [admet_ai(66.0)]}).molecules[0])
    assert f.reads == {"admet_ai": 0.66}   # raw harmonized read preserved
    assert f.score is not None and f.interval is not None


def test_no_ppb_source_yields_null_score_no_crash():
    f = _feature(aggregate({"m": [{"model": ModelName.bayesherg, "endpoint_values": {"P_block": 0.5},
                                   "uncertainty": None, "raw": {}, "provenance": PROV}]}).molecules[0])
    assert f.score is None and f.interval is None and f.reads == {}


def test_missing_or_nonnumeric_value_is_not_a_source():
    # a % key present but null both drop out (never a fabricated 0)
    recs = [ochem(87.3), {"model": ModelName.admet_ai, "endpoint_values": {"PPBR_AZ": None},
                          "uncertainty": None, "raw": {}, "provenance": PROV}]
    f = _feature(aggregate({"m": recs}).molecules[0])
    assert set(f.reads) == {"ochem_ppb"}


# -------------------------------------------------------------------------- shape / plumbing
def test_endpoint_identity_and_shape():
    res = aggregate({"m": [ochem(66.94)]})
    assert res.endpoint == Endpoint.ppb and res.n_molecules == 1
    mol = res.molecules[0]
    assert mol.endpoint == Endpoint.ppb and mol.mol_id == "m"
    assert set(type(mol).model_fields) == {"endpoint", "mol_id", "features"}
    assert set(type(mol.features[0]).model_fields) == {
        "feature", "score", "unit", "interval", "reads", "raw", "uncertainty"}


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
