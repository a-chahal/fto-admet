"""Tests for core.fusion: the trained-spec applier and its equal-weight fallback.

Runs in the core env (pydantic only) - no sklearn, no box. Pins the inference contract:
- with NO spec, fuse() == ensemble() (equal-weight mean + disagreement std), so untrained features are
  unchanged and aggregators migrate one at a time;
- with a spec, score = Σ wᵢ·gᵢ(valueᵢ) + intercept over the calibrated sources;
- identity / linear / logistic calibrations apply as specified;
- a missing source uses its impute_value (never silently biases the sum);
- the normalized-conformal half-width is Q · scale(x) (rides on the calibrated disagreement).
"""

from __future__ import annotations

import math

from core.aggregate import Source, ensemble
from core.fusion import apply_spec, fuse
from core.fusion.spec import (
    Fusion,
    FusionSpec,
    Provenance,
    SourceCalibration,
    Target,
    UncertaintySpec,
)


def _spec(sources, weights, *, intercept=0.0, uncertainty=None) -> FusionSpec:
    return FusionSpec(
        feature="f", endpoint="ep",
        target=Target(name="t", units="log"),
        sources=sources,
        fusion=Fusion(weights=weights, intercept=intercept, method="ridge"),
        uncertainty=uncertainty or UncertaintySpec(),
        provenance=Provenance(dataset="test"),
    )


def _src(model, value):
    return Source(model=model, value=value)


# -------------------------------------------------------------------------- fallback == ensemble
def test_no_spec_falls_back_to_equal_weight_ensemble():
    sources = [_src("a", 1.0), _src("b", 2.0), _src("c", 3.0)]
    # "ep__f" has no committed spec -> identical to ensemble over the raw values
    assert fuse("ep", "f", sources) == ensemble([1.0, 2.0, 3.0], [1.0, 1.0, 1.0])


# -------------------------------------------------------------------------- weighted calibrated sum
def test_identity_calibration_weighted_sum_plus_intercept():
    spec = _spec(
        [SourceCalibration(model="a", kind="identity"),
         SourceCalibration(model="b", kind="identity")],
        weights={"a": 0.25, "b": 0.75}, intercept=0.1,
    )
    score, unc = apply_spec(spec, [_src("a", 2.0), _src("b", 4.0)])
    assert math.isclose(score, 0.25 * 2.0 + 0.75 * 4.0 + 0.1)   # 3.6
    assert unc is None                                          # uncertainty method defaults to "none"


def test_linear_calibration_applies():
    spec = _spec(
        [SourceCalibration(model="lin", kind="linear", params=[2.0, -1.0])],
        weights={"lin": 1.0},
    )
    score, _ = apply_spec(spec, [_src("lin", 3.0)])
    assert math.isclose(score, 2.0 * 3.0 - 1.0)                # linear g: 2x-1 = 5


def test_logistic_calibration_maps_to_unit_interval():
    spec = _spec([SourceCalibration(model="p", kind="logistic", params=[1.0, 0.0])], weights={"p": 1.0})
    score, _ = apply_spec(spec, [_src("p", 0.0)])
    assert math.isclose(score, 0.5)                            # sigmoid(0) = 0.5


# -------------------------------------------------------------------------- missing source imputation
def test_missing_source_uses_impute_value():
    spec = _spec(
        [SourceCalibration(model="a", kind="identity", impute_value=10.0),
         SourceCalibration(model="b", kind="identity", impute_value=0.0)],
        weights={"a": 0.5, "b": 0.5},
    )
    # only 'b' present; 'a' imputes to 10.0
    score, _ = apply_spec(spec, [_src("b", 4.0)])
    assert math.isclose(score, 0.5 * 10.0 + 0.5 * 4.0)        # 7.0


def test_no_matching_source_yields_none():
    spec = _spec([SourceCalibration(model="a")], weights={"a": 1.0})
    assert apply_spec(spec, [_src("other", 1.0)]) == (None, None)


def test_logistic_link_squashes_score_to_probability():
    # A classification spec (fusion.link == "logistic") sigmoids the weighted sum into a probability.
    spec = FusionSpec(
        feature="f", endpoint="ep", target=Target(name="t", units="prob", transform="logit"),
        sources=[SourceCalibration(model="a", kind="identity")],
        fusion=Fusion(weights={"a": 1.0}, intercept=0.0, method="logistic", link="logistic"),
        uncertainty=UncertaintySpec(),  # method "none" -> no interval for classification
        provenance=Provenance(dataset="test"),
    )
    score, unc = apply_spec(spec, [_src("a", 0.0)])
    assert math.isclose(score, 0.5) and unc is None            # sigmoid(0) = 0.5, no conformal interval
    hi, _ = apply_spec(spec, [_src("a", 4.0)])
    assert 0.0 < score < hi < 1.0                              # monotone, bounded in (0,1)


def test_boolean_source_is_calibrated_as_zero_one():
    # A trained calibration treats a boolean flag as a 0/1 indicator (the equal-weight ensemble rejects
    # bools, but a fit calibration of e.g. BOILED-Egg's in-yolk BBB call is a meaningful 0/1 feature).
    spec = _spec([SourceCalibration(model="boiled_egg", kind="linear", params=[2.0, 1.0])],
                 weights={"boiled_egg": 1.0})
    on, _ = apply_spec(spec, [Source(model="boiled_egg", value=True)])
    off, _ = apply_spec(spec, [Source(model="boiled_egg", value=False)])
    assert math.isclose(on, 2.0 * 1.0 + 1.0) and math.isclose(off, 2.0 * 0.0 + 1.0)  # True->1, False->0


def test_from_raw_source_calibrates_its_raw_not_value():
    # A from_raw source (e.g. CardioGenAI's pIC50 on the P(block) hERG feature) is calibrated from its
    # native raw, even though the aggregator carries value=None on the common scale.
    spec = _spec([SourceCalibration(model="cardiogenai", kind="linear", params=[1.0, 0.5], from_raw=True)],
                 weights={"cardiogenai": 1.0})
    score, _ = apply_spec(spec, [Source(model="cardiogenai", value=None, raw=6.0, raw_unit="pIC50")])
    assert math.isclose(score, 1.0 * 6.0 + 0.5)   # calibrated from raw=6.0, not imputed/dropped


def test_non_from_raw_source_that_failed_to_harmonize_is_dropped_not_read_from_raw():
    # A default (from_raw=False) source whose value is None because harmonization FAILED (e.g. logD's
    # crippen with no pKa) must NOT be read from its raw (a different scale) - it is dropped/imputed.
    spec = _spec([SourceCalibration(model="a", kind="linear", params=[1.0, 0.0], impute_value=2.0),
                  SourceCalibration(model="crippen", kind="linear", params=[1.0, 0.0])],
                 weights={"a": 1.0, "crippen": 1.0})
    # 'a' present (=3.0); crippen has value=None but a raw on a foreign scale -> dropped, not read from raw
    score, _ = apply_spec(spec, [Source(model="a", value=3.0),
                                 Source(model="crippen", value=None, raw=99.0)])
    assert math.isclose(score, 1.0 * 3.0)   # only 'a'; crippen dropped (raw=99 NOT used)


# -------------------------------------------------------------------------- conformal half-width
def test_conformal_halfwidth_is_quantile_times_disagreement_std():
    unc = UncertaintySpec(method="normalized_conformal", quantile=2.0, scale="disagreement_std")
    spec = _spec(
        [SourceCalibration(model="a", kind="identity"), SourceCalibration(model="b", kind="identity")],
        weights={"a": 0.5, "b": 0.5}, uncertainty=unc,
    )
    _, width = apply_spec(spec, [_src("a", 0.0), _src("b", 2.0)])
    std = math.sqrt(((0.0 - 1.0) ** 2 + (2.0 - 1.0) ** 2) / 2)  # population std of {0,2} = 1.0
    assert math.isclose(width, 2.0 * std)                       # Q * std = 2.0


def test_scale_floor_bounds_the_width():
    unc = UncertaintySpec(method="normalized_conformal", quantile=1.0, scale="disagreement_std", scale_floor=0.5)
    spec = _spec([SourceCalibration(model="a", kind="identity")], weights={"a": 1.0}, uncertainty=unc)
    _, width = apply_spec(spec, [_src("a", 5.0)])              # single source -> std 0, floored to 0.5
    assert math.isclose(width, 0.5)
