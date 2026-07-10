"""Tests for the clearance aggregator: three DECOMPOSED features, never merged across units (F-3).

Synthetic ``OutputRecord``-shaped inputs only (laptop, core env - no box, no GPU). They pin the science
that must survive the shape change:
- ``hepatocyte_clint`` is a CLEAN 2-source ensemble (OPERA Clint + ADMET-AI hepatocyte, SAME units):
  score = mean, uncertainty = std;
- ``systemic_cl`` is a single PKSmart read (whole-body i.v. CL) with its native fold-error in the note;
- ``microsomal_clint`` is a single ADMET-AI read on its own distinct unit;
- the three features stay separate: nothing is averaged or summed across their units;
- any subset (single source -> uncertainty None; none -> score None) is tolerated.
"""

from __future__ import annotations

import math

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


def opera_clint(clint: float) -> dict:
    return {"model": ModelName.opera, "endpoint_values": {"Clint": clint},
            "uncertainty": {"conf_index": 0.7, "extra": {}}, "raw": {}, "provenance": PROV}


def admet_ai(hepatocyte: float | None = None, microsome: float | None = None) -> dict:
    return {"model": ModelName.admet_ai,
            "endpoint_values": {"Clearance_Hepatocyte_AZ": hepatocyte,
                                "Clearance_Microsome_AZ": microsome,
                                "HIA_Hou": 0.98},  # an unrelated head that must be ignored
            "uncertainty": None, "raw": {}, "provenance": PROV}


def pksmart(cl: float, *, fold_error=None, low=None, high=None, with_uncertainty=True) -> dict:
    unc = None
    if with_uncertainty:
        unc = {"fold_error_low": low, "fold_error_high": high, "extra": {"cl_fold_error": fold_error}}
    return {"model": ModelName.pksmart, "endpoint_values": {"CL_mL_min_kg": cl, "VDss_L_kg": 3.0},
            "uncertainty": unc, "raw": {}, "provenance": PROV}


def _feature(mol, name):
    f = next(f for f in mol.features if f.feature == name)
    return f


def _src(feature, model):
    return next(s for s in feature.sources if s.model == model)


# ------------------------------------------------------- hepatocyte_clint: clean same-unit ensemble
def test_hepatocyte_clint_is_mean_and_std_over_same_units():
    f = _feature(aggregate({"m": [opera_clint(8.0), admet_ai(hepatocyte=12.0)]}).molecules[0],
                 HEPATOCYTE_CLINT)
    vals = [8.0, 12.0]
    mean = sum(vals) / 2
    var = sum((x - mean) ** 2 for x in vals) / 2
    assert f.n_sources == 2
    assert math.isclose(f.score, mean)
    assert math.isclose(f.uncertainty, math.sqrt(var))
    assert f.unit == HEPATOCYTE_CLINT_UNIT
    assert {s.model for s in f.sources} == {"opera", "admet_ai"}


def test_hepatocyte_convergent_lower_uncertainty_than_divergent():
    tight = _feature(aggregate({"m": [opera_clint(10.0), admet_ai(hepatocyte=10.5)]}).molecules[0],
                     HEPATOCYTE_CLINT)
    wide = _feature(aggregate({"m": [opera_clint(10.0), admet_ai(hepatocyte=40.0)]}).molecules[0],
                    HEPATOCYTE_CLINT)
    assert tight.uncertainty < wide.uncertainty


def test_hepatocyte_single_source_has_score_but_no_uncertainty():
    f = _feature(aggregate({"m": [opera_clint(8.0)]}).molecules[0], HEPATOCYTE_CLINT)
    assert f.score == 8.0 and f.uncertainty is None and f.n_sources == 1


def test_hepatocyte_absent_yields_null_score():
    f = _feature(aggregate({"m": [pksmart(50.0)]}).molecules[0], HEPATOCYTE_CLINT)
    assert f.score is None and f.uncertainty is None and f.n_sources == 0


# ------------------------------------------------------- systemic_cl: single PKSmart read + fold-error note
def test_systemic_cl_carries_value_and_fold_error_note():
    f = _feature(aggregate({"m": [pksmart(89.6, fold_error=2.4, low=37.3, high=215.0)]}).molecules[0],
                 SYSTEMIC_CL)
    s = _src(f, "pksmart")
    assert s.value == 89.6
    assert f.score == 89.6 and f.uncertainty is None and f.n_sources == 1
    assert f.unit == SYSTEMIC_CL_UNIT
    assert "low=37.3" in s.note and "high=215.0" in s.note and "cl_fold=2.4" in s.note


def test_systemic_cl_note_survives_missing_uncertainty():
    f = _feature(aggregate({"m": [pksmart(40.0, with_uncertainty=False)]}).molecules[0], SYSTEMIC_CL)
    s = _src(f, "pksmart")
    assert s.value == 40.0
    assert "low=None" in s.note and "high=None" in s.note and "cl_fold=None" in s.note


def test_systemic_cl_absent_yields_null_score():
    f = _feature(aggregate({"m": [opera_clint(8.0)]}).molecules[0], SYSTEMIC_CL)
    assert f.score is None and f.n_sources == 0


# ------------------------------------------------------- microsomal_clint: single ADMET-AI read
def test_microsomal_clint_is_single_admet_ai_read():
    f = _feature(aggregate({"m": [admet_ai(microsome=30.0)]}).molecules[0], MICROSOMAL_CLINT)
    assert f.score == 30.0 and f.uncertainty is None and f.n_sources == 1
    assert f.unit == MICROSOMAL_CLINT_UNIT
    assert _src(f, "admet_ai").value == 30.0


def test_microsomal_clint_absent_yields_null_score():
    f = _feature(aggregate({"m": [opera_clint(8.0)]}).molecules[0], MICROSOMAL_CLINT)
    assert f.score is None and f.n_sources == 0


# ------------------------------------------------------- decomposition: never merged across units
def test_three_decomposed_features_with_distinct_units():
    recs = [opera_clint(8.0), admet_ai(hepatocyte=12.0, microsome=30.0),
            pksmart(89.6, fold_error=2.4, low=37.3, high=215.0)]
    mol = aggregate({"FTO-43": recs}).molecules[0]
    names = [f.feature for f in mol.features]
    assert names == [HEPATOCYTE_CLINT, SYSTEMIC_CL, MICROSOMAL_CLINT]
    units = {f.feature: f.unit for f in mol.features}
    # Three distinct unit strings; nothing shared or fused across matrices.
    assert units[HEPATOCYTE_CLINT] == "uL/min/10^6 cells (up = faster clearance)"
    assert units[SYSTEMIC_CL] == "mL/min/kg (whole-body IV clearance, up = faster)"
    assert units[MICROSOMAL_CLINT] == "uL/min/mg (up = faster clearance)"
    # hepatocyte ensembled the two same-unit reads; the microsomal read stayed in its OWN feature.
    assert _feature(mol, HEPATOCYTE_CLINT).n_sources == 2
    assert _feature(mol, MICROSOMAL_CLINT).n_sources == 1
    # ADMET-AI hepatocyte (12) and microsome (30) were never averaged: no 21.0 anywhere.
    assert _feature(mol, HEPATOCYTE_CLINT).score == 10.0  # (8 + 12) / 2, microsome not involved


# ------------------------------------------------------- shape / plumbing
def test_endpoint_identity_and_uniform_shape():
    res = aggregate({"m": [admet_ai(hepatocyte=12.0)]})
    assert res.endpoint == Endpoint.clearance and res.n_molecules == 1
    mol = res.molecules[0]
    assert mol.endpoint == Endpoint.clearance and mol.mol_id == "m"
    assert set(type(mol).model_fields) == {"endpoint", "mol_id", "features"}
    assert set(type(mol.features[0]).model_fields) == {
        "feature", "score", "uncertainty", "unit", "n_sources", "sources"}


def test_multiple_molecules_independent():
    res = aggregate({"a": [opera_clint(8.0)], "b": [opera_clint(20.0)]})
    by = {m.mol_id: _feature(m, HEPATOCYTE_CLINT).score for m in res.molecules}
    assert by == {"a": 8.0, "b": 20.0}


def test_input_shapes_normalize_the_same():
    recs = [admet_ai(hepatocyte=12.0)]
    as_map = aggregate({"FTO-43": recs}).molecules[0]
    as_pairs = aggregate([("FTO-43", recs)]).molecules[0]
    as_dicts = aggregate([{"mol_id": "FTO-43", "records": recs}]).molecules[0]
    for m in (as_map, as_pairs, as_dicts):
        assert m.mol_id == "FTO-43"
        assert _feature(m, HEPATOCYTE_CLINT).score == 12.0


def test_empty_input_yields_empty_result():
    res = aggregate([])
    assert res.molecules == [] and res.n_molecules == 0
