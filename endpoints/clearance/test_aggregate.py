"""Tests for the clearance aggregator: three DECOMPOSED features, never merged across units (F-3).

Synthetic ``OutputRecord``-shaped inputs only (laptop, core env - no box, no GPU). They pin the science
that must survive the shape change:
- ``hepatocyte_clint`` is a CLEAN 2-source ensemble (OPERA Clint + ADMET-AI hepatocyte, SAME units),
  scored by the trained fusion spec;
- ``systemic_cl`` is a single PKSmart read (whole-body i.v. CL); untrained -> equal-weight passthrough,
  its native fold-error surfaced in ``uncertainty``;
- ``microsomal_clint`` is a single ADMET-AI read on its own distinct unit, scored by the trained spec;
- the three features stay separate: nothing is averaged or summed across their units.

Output shape (per feature): score, unit, interval[low,high], reads{model:harmonized}, raw{model:native},
uncertainty{model_type:value}. Exact fused values are pinned in tests/test_fusion.py.
"""

from __future__ import annotations

from core.models import Endpoint, ModelName
from endpoints.clearance.aggregate import (
    HEPATOCYTE_CLINT,
    HEPATOCYTE_CLINT_UNIT,
    MICROSOMAL_CLINT,
    MICROSOMAL_CLINT_UNIT,
    SYSTEMIC_CL,
    SYSTEMIC_CL_UNIT,
    aggregate,
)

PROV = {"model": "test"}


def opera_clint(clint: float, *, conf_index: float | None = None, ad_in_domain: bool | None = None) -> dict:
    # OPERA's per-endpoint AD/confidence lives in uncertainty.extra keyed by the endpoint name.
    extra: dict = {}
    if conf_index is not None:
        extra["Clint_conf_index"] = conf_index
    if ad_in_domain is not None:
        extra["Clint_ad_in_domain"] = ad_in_domain
    return {"model": ModelName.opera, "endpoint_values": {"Clint": clint},
            "uncertainty": {"extra": extra}, "raw": {}, "provenance": PROV}


def admet_ai(hepatocyte: float | None = None, microsome: float | None = None) -> dict:
    return {"model": ModelName.admet_ai,
            "endpoint_values": {"Clearance_Hepatocyte_AZ": hepatocyte,
                                "Clearance_Microsome_AZ": microsome,
                                "HIA_Hou": 0.98},  # an unrelated head that must be ignored
            "uncertainty": None, "raw": {}, "provenance": PROV}


def pksmart(cl: float, *, low=None, high=None, ad_in_domain=None, with_uncertainty=True) -> dict:
    unc = None
    if with_uncertainty:
        unc = {"fold_error_low": low, "fold_error_high": high, "ad_in_domain": ad_in_domain, "extra": {}}
    return {"model": ModelName.pksmart, "endpoint_values": {"CL_mL_min_kg": cl, "VDss_L_kg": 3.0},
            "uncertainty": unc, "raw": {}, "provenance": PROV}


def _feature(mol, name):
    return next(f for f in mol.features if f.feature == name)


# ------------------------------------------------------- hepatocyte_clint: trained fusion spec
def test_hepatocyte_clint_gathers_both_sources_with_harmonized_values():
    # The aggregator's job: gather OPERA Clint + ADMET-AI hepatocyte on the SAME units. The SCORE is now
    # produced by the trained fusion spec (exact value tested in tests/test_fusion.py), so assert the reads
    # are preserved with their harmonized values and a calibrated score + interval exist.
    f = _feature(aggregate({"m": [opera_clint(8.0), admet_ai(hepatocyte=12.0)]}).molecules[0],
                 HEPATOCYTE_CLINT)
    assert f.reads == {"opera": 8.0, "admet_ai": 12.0}   # harmonized reads preserved
    assert f.score is not None and f.interval is not None  # trained -> calibrated CLint + conformal interval
    assert f.unit == HEPATOCYTE_CLINT_UNIT


def test_hepatocyte_opera_ad_signals_land_in_uncertainty():
    f = _feature(aggregate({"m": [opera_clint(8.0, conf_index=0.72, ad_in_domain=True),
                                  admet_ai(hepatocyte=12.0)]}).molecules[0], HEPATOCYTE_CLINT)
    assert f.uncertainty["opera_conf_index"] == 0.72
    assert f.uncertainty["opera_ad_in_domain"] is True


def test_hepatocyte_single_admet_ai_source_yields_calibrated_score():
    f = _feature(aggregate({"m": [admet_ai(hepatocyte=12.0)]}).molecules[0], HEPATOCYTE_CLINT)
    assert f.reads == {"admet_ai": 12.0}
    assert f.score is not None and f.interval is not None


def test_hepatocyte_absent_yields_null_score():
    f = _feature(aggregate({"m": [pksmart(50.0)]}).molecules[0], HEPATOCYTE_CLINT)
    assert f.score is None and f.interval is None and f.reads == {}


# ------------------------------------------------------- systemic_cl: single PKSmart read + fold-error signal
def test_systemic_cl_carries_value_and_fold_error_signal():
    f = _feature(aggregate({"m": [pksmart(89.6, low=37.3, high=215.0, ad_in_domain=True)]}).molecules[0],
                 SYSTEMIC_CL)
    assert f.reads == {"pksmart": 89.6}
    assert f.score == 89.6 and f.interval is None   # untrained -> equal-weight passthrough, no interval
    assert f.unit == SYSTEMIC_CL_UNIT
    # native fold-error surfaced in uncertainty (was previously a note string)
    assert f.uncertainty["pksmart_fold_error_low"] == 37.3
    assert f.uncertainty["pksmart_fold_error_high"] == 215.0
    assert f.uncertainty["pksmart_ad_in_domain"] is True


def test_systemic_cl_survives_missing_uncertainty():
    f = _feature(aggregate({"m": [pksmart(40.0, with_uncertainty=False)]}).molecules[0], SYSTEMIC_CL)
    assert f.reads == {"pksmart": 40.0}
    assert f.score == 40.0 and f.uncertainty == {}   # no native signals when the record has no uncertainty


def test_systemic_cl_absent_yields_null_score():
    f = _feature(aggregate({"m": [opera_clint(8.0)]}).molecules[0], SYSTEMIC_CL)
    assert f.score is None and f.reads == {}


# ------------------------------------------------------- microsomal_clint: single ADMET-AI read
def test_microsomal_clint_is_single_admet_ai_read():
    # trained single-source spec: the admet_ai microsome read is calibrated to Biogen HLM CLint (exact
    # value tested in tests/test_fusion.py), so assert the read is gathered with its harmonized value and
    # a calibrated score + conformal interval exist.
    f = _feature(aggregate({"m": [admet_ai(microsome=30.0)]}).molecules[0], MICROSOMAL_CLINT)
    assert f.reads == {"admet_ai": 30.0}
    assert f.score is not None and f.interval is not None
    assert f.unit == MICROSOMAL_CLINT_UNIT


def test_microsomal_clint_absent_yields_null_score():
    f = _feature(aggregate({"m": [opera_clint(8.0)]}).molecules[0], MICROSOMAL_CLINT)
    assert f.score is None and f.reads == {}


# ------------------------------------------------------- decomposition: never merged across units
def test_three_decomposed_features_with_distinct_units():
    recs = [opera_clint(8.0), admet_ai(hepatocyte=12.0, microsome=30.0),
            pksmart(89.6, low=37.3, high=215.0)]
    mol = aggregate({"FTO-43": recs}).molecules[0]
    names = [f.feature for f in mol.features]
    assert names == [HEPATOCYTE_CLINT, SYSTEMIC_CL, MICROSOMAL_CLINT]
    units = {f.feature: f.unit for f in mol.features}
    # Three distinct unit strings; nothing shared or fused across matrices.
    assert units[HEPATOCYTE_CLINT] == "uL/min/10^6 cells (up = faster clearance)"
    assert units[SYSTEMIC_CL] == "mL/min/kg (whole-body IV clearance, up = faster)"
    assert units[MICROSOMAL_CLINT] == "uL/min/mg (up = faster clearance)"
    # hepatocyte fused the two same-unit reads; the microsomal read stayed in its OWN feature.
    hep = _feature(mol, HEPATOCYTE_CLINT)
    assert hep.reads == {"opera": 8.0, "admet_ai": 12.0}
    assert _feature(mol, MICROSOMAL_CLINT).reads == {"admet_ai": 30.0}
    # ADMET-AI hepatocyte (12) and microsome (30) were never merged: only 8.0 + 12.0 fed the hepatocyte
    # feature; the microsome value (30) never entered it.
    assert set(hep.reads.values()) == {8.0, 12.0}
    assert hep.score is not None


# ------------------------------------------------------- shape / plumbing
def test_endpoint_identity_and_uniform_shape():
    res = aggregate({"m": [admet_ai(hepatocyte=12.0)]})
    assert res.endpoint == Endpoint.clearance and res.n_molecules == 1
    mol = res.molecules[0]
    assert mol.endpoint == Endpoint.clearance and mol.mol_id == "m"
    assert set(type(mol).model_fields) == {"endpoint", "mol_id", "features"}
    assert set(type(mol.features[0]).model_fields) == {
        "feature", "score", "unit", "interval", "reads", "raw", "uncertainty"}


def test_multiple_molecules_independent():
    res = aggregate({"a": [admet_ai(hepatocyte=8.0)], "b": [admet_ai(hepatocyte=20.0)]})
    by = {m.mol_id: _feature(m, HEPATOCYTE_CLINT).score for m in res.molecules}
    assert by["a"] < by["b"]  # the calibration is monotone increasing: higher CLint still ranks higher


def test_input_shapes_normalize_the_same():
    recs = [admet_ai(hepatocyte=12.0)]
    as_map = aggregate({"FTO-43": recs}).molecules[0]
    as_pairs = aggregate([("FTO-43", recs)]).molecules[0]
    as_dicts = aggregate([{"mol_id": "FTO-43", "records": recs}]).molecules[0]
    scores = [_feature(m, HEPATOCYTE_CLINT).score for m in (as_map, as_pairs, as_dicts)]
    assert len(set(scores)) == 1 and scores[0] is not None  # same input -> same fused score across shapes
    for m in (as_map, as_pairs, as_dicts):
        assert m.mol_id == "FTO-43"


def test_empty_input_yields_empty_result():
    res = aggregate([])
    assert res.molecules == [] and res.n_molecules == 0
