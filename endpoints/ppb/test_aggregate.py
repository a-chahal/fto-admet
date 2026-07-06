"""Tests for the ppb fraction-bound consensus aggregator (task t45).

Synthetic ``OutputRecord``-shaped inputs only (laptop, core env - no box, no GPU; OCHEM / OPERA may not
be live yet, so records are hand-built). They exercise:
- the done-criteria: OCHEM 90% + ADMET-AI 90% + OPERA FuB 0.1 all resolve to fraction bound ~= 0.90,
  with the OPERA inversion (1 - FuB) applied and direction UP = more bound;
- each normalizer in isolation (% -> /100; the OPERA 1 - FuB inversion is the landmine);
- the spread-as-confidence flag: convergent sources -> low spread + confident; divergent -> high + soft;
- any subset of the three sources being tolerated (single source, or none);
- the OPERA ``FuB`` / ``FuB_pred`` key alias and native confidence being carried through;
- the F-7 tripwire note when a "% bound" source's raw value already looks fractional.
"""

from __future__ import annotations

import math

from core.models import Endpoint, ModelName
from endpoints.ppb.aggregate import (
    HIGH,
    LOW,
    NA,
    SPREAD_RANGE_TRUST,
    aggregate,
    fub_to_fraction_bound,
    pct_to_fraction_bound,
)

PROV = {"model": "test"}


def ochem(pct_bound: float, key: str = "PPB", conf: float | None = 0.90, ad: bool | None = True) -> dict:
    unc = None
    if conf is not None or ad is not None:
        unc = {"confidence": conf, "ad_in_domain": ad}
    return {
        "model": ModelName.ochem_ppb,
        "endpoint_values": {key: pct_bound},
        "uncertainty": unc,
        "raw": {},
        "provenance": PROV,
    }


def admet_ai(pct_bound: float) -> dict:
    return {
        "model": ModelName.admet_ai,
        "endpoint_values": {"PPBR_AZ": pct_bound},
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }


def opera(fub: float, key: str = "FuB", conf: float | None = 0.80) -> dict:
    return {
        "model": ModelName.opera,
        "endpoint_values": {key: fub},
        "uncertainty": {"conf_index": conf} if conf is not None else None,
        "raw": {},
        "provenance": PROV,
    }


# --------------------------------------------------------------------------------------------------
# The normalizers in isolation (the landmine math).
# --------------------------------------------------------------------------------------------------
def test_pct_to_fraction_bound():
    assert pct_to_fraction_bound(90.0) == 0.90
    assert pct_to_fraction_bound(0.0) == 0.0
    assert pct_to_fraction_bound(100.0) == 1.0


def test_fub_inversion():
    # FuB = 0.1 means 90% bound, NOT 10%. The inversion is the whole point of F-7.
    assert fub_to_fraction_bound(0.1) == 0.9
    assert fub_to_fraction_bound(0.0) == 1.0
    assert fub_to_fraction_bound(1.0) == 0.0


# --------------------------------------------------------------------------------------------------
# Done-criteria: 90% / 90% / FuB 0.1 -> fraction bound ~= 0.90, inversion applied, direction UP.
# --------------------------------------------------------------------------------------------------
def test_done_criteria_all_three_resolve_to_0_90():
    result = aggregate({"FTO-43": [ochem(90.0), admet_ai(90.0), opera(0.1)]})

    assert result.endpoint == Endpoint.ppb
    assert result.n_molecules == 1
    mol = result.molecules[0]
    assert mol.mol_id == "FTO-43"
    assert mol.n_sources == 3

    # Every source lands on ~0.90 on the common fraction-bound axis.
    by_model = {s.model: s for s in mol.sources}
    assert math.isclose(by_model[ModelName.ochem_ppb].fraction_bound, 0.90)
    assert math.isclose(by_model[ModelName.admet_ai].fraction_bound, 0.90)
    assert math.isclose(by_model[ModelName.opera].fraction_bound, 0.90)

    # The OPERA source is on the fraction-UNBOUND scale and had the inversion applied.
    opera_src = by_model[ModelName.opera]
    assert opera_src.native_scale == "fraction unbound"
    assert opera_src.transform == "1 - FuB"
    assert opera_src.raw_value == 0.1

    # Consensus ~= 0.90, sources converge -> confident.
    assert math.isclose(mol.consensus, 0.90, abs_tol=1e-9)
    assert mol.spread_range == 0.0
    assert mol.spread_flag == LOW
    assert mol.confident is True

    # OCHEM is marked primary and carries its native accuracy + AD signal.
    assert by_model[ModelName.ochem_ppb].primary is True
    assert by_model[ModelName.ochem_ppb].confidence == 0.90
    assert by_model[ModelName.ochem_ppb].ad_in_domain is True


def test_direction_up_is_more_bound():
    # A highly bound molecule (FuB 0.02 -> 98% bound) reads higher than a lightly bound one.
    high = aggregate([[opera(0.02)]]).molecules[0].consensus
    low = aggregate([[opera(0.80)]]).molecules[0].consensus
    assert high is not None and low is not None
    assert high > low
    assert math.isclose(high, 0.98)
    assert math.isclose(low, 0.20)


# --------------------------------------------------------------------------------------------------
# Spread as the confidence signal.
# --------------------------------------------------------------------------------------------------
def test_divergent_sources_flag_high_and_soft():
    # OCHEM 95% (0.95) vs OPERA FuB 0.6 (-> 0.40): a wide spread.
    result = aggregate({"m": [ochem(95.0), opera(0.6)]})
    mol = result.molecules[0]
    assert mol.n_sources == 2
    assert mol.spread_range is not None and mol.spread_range > SPREAD_RANGE_TRUST
    assert mol.spread_flag == HIGH
    assert mol.confident is False
    # The mean is still reported, and both per-source values remain visible (not fused away).
    assert math.isclose(mol.consensus, (0.95 + 0.40) / 2)
    assert {s.model for s in mol.sources} == {ModelName.ochem_ppb, ModelName.opera}


def test_single_source_tolerated_but_not_confident():
    result = aggregate({"m": [admet_ai(88.0)]})
    mol = result.molecules[0]
    assert mol.n_sources == 1
    assert math.isclose(mol.consensus, 0.88)
    assert mol.spread_flag == NA
    assert mol.spread_range is None
    assert mol.confident is False


def test_no_source_present():
    # A record from an unrelated model must not produce a ppb source.
    other = {
        "model": ModelName.rdkit_crippen,
        "endpoint_values": {"logP_crippen": 2.0},
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }
    result = aggregate({"m": [other]})
    mol = result.molecules[0]
    assert mol.n_sources == 0
    assert mol.consensus is None
    assert mol.spread_flag == NA
    assert mol.confident is False


# --------------------------------------------------------------------------------------------------
# Key aliases, native confidence, and the F-7 tripwire.
# --------------------------------------------------------------------------------------------------
def test_opera_fub_pred_key_alias():
    # The t45 brief names the OPERA field "FuB_pred"; the adapter emits "FuB". Both must be read.
    result = aggregate({"m": [opera(0.1, key="FuB_pred", conf=0.7)]})
    src = result.molecules[0].sources[0]
    assert src.field == "FuB_pred"
    assert math.isclose(src.fraction_bound, 0.90)
    assert src.confidence == 0.7


def test_ochem_candidate_key_read():
    # Any of the documented candidate keys is accepted for OCHEM's % bound value.
    result = aggregate({"m": [ochem(90.0, key="percent_bound")]})
    src = result.molecules[0].sources[0]
    assert src.field == "percent_bound"
    assert math.isclose(src.fraction_bound, 0.90)


def test_f7_tripwire_note_on_fractional_looking_pct():
    # A "% bound" source whose RAW value already lies in [0,1] gets a soft F-7 note (never rewritten).
    result = aggregate({"m": [ochem(0.9)]})  # 0.9 "percent" -> 0.009 fraction; suspicious
    src = result.molecules[0].sources[0]
    assert math.isclose(src.fraction_bound, 0.009)  # value is NOT silently reinterpreted
    assert any("F-7" in n or "FRACTION" in n for n in src.notes)


def test_multiple_molecules_and_input_shapes():
    # Mapping and list-of-pairs shapes both work, and molecules are independent.
    as_map = aggregate({"a": [ochem(90.0)], "b": [opera(0.1)]})
    assert [m.mol_id for m in as_map.molecules] == ["a", "b"]

    as_pairs = aggregate([("a", [ochem(90.0)]), ("b", [opera(0.1)])])
    assert [m.mol_id for m in as_pairs.molecules] == ["a", "b"]
    assert math.isclose(as_pairs.molecules[1].consensus, 0.90)


def test_result_carries_deferred_f7_and_calibration():
    result = aggregate({"m": [ochem(90.0)]})
    joined = " ".join(result.deferred)
    assert "F-7" in joined
    assert "calibrat" in joined.lower()
