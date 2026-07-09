"""Tests for the triage aggregator (task t51): the funnel-entry generalist flag table. FLAGS ONLY.

Synthetic ``OutputRecord``-shaped inputs only (laptop, core env - no box, no GPU). They exercise the
guarantees this endpoint exists to provide (task t51, IO_SPEC §1 #1-#3, SETTLED §7):

- the two generalists (ADMET-AI v2 / ADMETlab 3.0) are summarized into a per-property
  flag table, keyed by canonical property;
- uncertainty = CROSS-MODEL SPREAD: when generalists that share a property diverge, the flag is raised;
  when they agree, it is not;
- a SINGLE generalist is never authority: a lone read is marked ``single_source``, not "ok";
- ADMETlab's Youden high/low flag feeds the confidence read;
- FLAGS ONLY - there is no gate/kill anywhere (every ``is_gate`` is False; no promote/reject verdict);
- ADMET-AI's excluded VDss/half-life heads stay absent and are never resurrected (F-17);
- the accepted input shapes normalize the same way; missing generalists degrade gracefully.
"""

from __future__ import annotations

from core.models import Endpoint, ModelName
from endpoints.triage.aggregate import (
    CONF_LOW,
    CONF_OK,
    CONF_SINGLE,
    EXCLUDED_R2_NEGATIVE,
    PROB_SPREAD_FLAG,
    aggregate,
)

PROV = {"model": "test"}


def admet_ai_rec(**heads) -> dict:
    """An ADMET-AI record whose endpoint_values are the given canonical heads (probabilities/regressions)."""
    return {
        "model": ModelName.admet_ai,
        "endpoint_values": dict(heads),
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }


def admetlab3_rec(heads: dict, conf_flags: dict | None = None) -> dict:
    """An ADMETlab record; per-endpoint Youden high/low flags ride in uncertainty.extra["confidence_flags"]."""
    unc = None
    if conf_flags is not None:
        unc = {"extra": {"confidence_flags": conf_flags}}
    return {
        "model": ModelName.admetlab3,
        "endpoint_values": dict(heads),
        "uncertainty": unc,
        "raw": {},
        "provenance": PROV,
    }


def _prop(mol, name):
    """Fetch a single PropertyFlag row by canonical name."""
    for p in mol.properties:
        if p.property == name:
            return p
    raise AssertionError(f"property {name!r} not in flag table: {[p.property for p in mol.properties]}")


# --------------------------------------------------------------------------------------------------
# Shape / endpoint identity.
# --------------------------------------------------------------------------------------------------
def test_endpoint_identity_and_flag_table_shape():
    res = aggregate({"m": [admet_ai_rec(hERG=0.2, BBB_Martins=0.9)]})
    assert res.endpoint == Endpoint.triage
    assert res.n_molecules == 1
    mol = res.molecules[0]
    assert mol.present is True
    assert {p.property for p in mol.properties} == {"hERG", "BBB_Martins"}
    assert mol.n_properties == 2


# --------------------------------------------------------------------------------------------------
# Cross-model spread = the uncertainty signal.
# --------------------------------------------------------------------------------------------------
def test_divergent_generalists_raise_the_flag():
    """Two generalists reporting the same probability property, far apart, raise the divergence flag."""
    recs = [
        admet_ai_rec(hERG=0.1),
        admetlab3_rec({"hERG": 0.9}),  # spread 0.8 > PROB_SPREAD_FLAG -> divergent
    ]
    hERG = _prop(aggregate({"m": recs}).molecules[0], "hERG")
    assert hERG.n_models == 2
    assert hERG.spread == 0.8 > PROB_SPREAD_FLAG
    assert hERG.prob_scale is True
    assert hERG.divergent is True
    assert hERG.confidence == CONF_LOW


def test_agreeing_generalists_do_not_raise_the_flag():
    """Two generalists that agree closely on a probability property are not divergent and read as ok."""
    recs = [admet_ai_rec(hERG=0.80), admetlab3_rec({"hERG": 0.85})]  # spread 0.05
    hERG = _prop(aggregate({"m": recs}).molecules[0], "hERG")
    assert hERG.divergent is False
    assert hERG.confidence == CONF_OK


def test_single_generalist_is_never_authority():
    """A property reported by exactly one generalist is single_source (not cross-checked), never ok/low."""
    hERG = _prop(aggregate({"m": [admet_ai_rec(hERG=0.05)]}).molecules[0], "hERG")
    assert hERG.n_models == 1
    assert hERG.divergent is False
    assert hERG.spread is None
    assert hERG.confidence == CONF_SINGLE


def test_divergent_properties_summary_lists_only_flagged():
    recs = [
        admet_ai_rec(hERG=0.1, BBB_Martins=0.9),
        admetlab3_rec({"hERG": 0.9, "BBB_Martins": 0.88}),  # hERG diverges, BBB agrees
    ]
    mol = aggregate({"m": recs}).molecules[0]
    assert mol.divergent_properties == ["hERG"]


# --------------------------------------------------------------------------------------------------
# Non-probability scales: spread recorded, but NO flag (calibration DEFERRED).
# --------------------------------------------------------------------------------------------------
def test_non_probability_spread_is_recorded_but_does_not_raise_flag():
    """logD-scale reads (outside [0,1]) get a recorded spread but never a divergence flag (DEFERRED)."""
    recs = [
        admet_ai_rec(Lipophilicity_AstraZeneca=1.0),
        admetlab3_rec({"Lipophilicity_AstraZeneca": 4.5}),  # spread 3.5, but not a probability scale
    ]
    logd = _prop(aggregate({"m": recs}).molecules[0], "Lipophilicity_AstraZeneca")
    assert logd.spread == 3.5
    assert logd.prob_scale is False
    assert logd.divergent is False


# --------------------------------------------------------------------------------------------------
# ADMETlab Youden high/low flag feeds the confidence read.
# --------------------------------------------------------------------------------------------------
def test_admetlab_low_confidence_flag_drives_confidence_low():
    """Even when the two generalists agree, an ADMETlab Youden 'low' flag drags the confidence to low."""
    recs = [
        admet_ai_rec(hERG=0.82),
        admetlab3_rec({"hERG": 0.85}, conf_flags={"hERG": "low"}),  # agree, but native low flag
    ]
    hERG = _prop(aggregate({"m": recs}).molecules[0], "hERG")
    assert hERG.divergent is False
    assert hERG.confidence == CONF_LOW
    assert hERG.reads[1].native_conf_flag == "low"


def test_admetlab_high_confidence_flag_leaves_agreement_ok():
    recs = [admet_ai_rec(hERG=0.82), admetlab3_rec({"hERG": 0.85}, conf_flags={"hERG": "high"})]
    hERG = _prop(aggregate({"m": recs}).molecules[0], "hERG")
    assert hERG.confidence == CONF_OK


# --------------------------------------------------------------------------------------------------
# FLAGS ONLY - no kill / gate anywhere.
# --------------------------------------------------------------------------------------------------
def test_flags_only_never_a_gate():
    """Every property flag is explicitly non-gating; the result carries no promote/reject/pass-fail field."""
    recs = [admet_ai_rec(hERG=0.99, AMES=0.99), admetlab3_rec({"hERG": 0.05})]
    res = aggregate({"m": recs})
    mol = res.molecules[0]
    assert all(p.is_gate is False for p in mol.properties)
    # The result schema deliberately has no kill/verdict/promote field.
    fields = set(type(res).model_fields)
    assert not (fields & {"kill", "verdict", "promote", "reject", "pass_", "gate", "advance"})


# --------------------------------------------------------------------------------------------------
# Exclusions (F-17): VDss / half-life never appear.
# --------------------------------------------------------------------------------------------------
def test_excluded_heads_stay_absent_even_if_a_stray_record_carries_them():
    """A guard against resurrection: even if a record wrongly carried VDss/half-life, triage drops them."""
    rec = admet_ai_rec(hERG=0.3, VDss_Lombardo=2.0, Half_Life_Obach=5.0)
    mol = aggregate({"m": [rec]}).molecules[0]
    names = {p.property for p in mol.properties}
    assert names == {"hERG"}
    assert not (names & EXCLUDED_R2_NEGATIVE)


# --------------------------------------------------------------------------------------------------
# Input-shape normalization + graceful degradation.
# --------------------------------------------------------------------------------------------------
def test_input_shapes_normalize_the_same():
    recs = [admet_ai_rec(hERG=0.1), admetlab3_rec({"hERG": 0.9})]
    as_map = aggregate({"FTO-43": recs}).molecules[0]
    as_pairs = aggregate([("FTO-43", recs)]).molecules[0]
    as_dicts = aggregate([{"mol_id": "FTO-43", "records": recs}]).molecules[0]
    as_bare = aggregate([recs]).molecules[0]
    assert as_map.mol_id == as_pairs.mol_id == as_dicts.mol_id == "FTO-43"
    assert as_bare.mol_id == "mol_0"
    for m in (as_map, as_pairs, as_dicts, as_bare):
        assert _prop(m, "hERG").divergent is True


def test_no_generalist_reads_degrades_gracefully():
    """A molecule with no generalist record is present=False with an empty table, not an error."""
    other = {
        "model": ModelName.bayesherg,
        "endpoint_values": {"score": 0.5},
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }
    mol = aggregate({"m": [other]}).molecules[0]
    assert mol.present is False
    assert mol.properties == []
    assert mol.n_properties == 0


def test_clean_named_generalists_co_populate_one_property_and_can_diverge():
    """ADMET-AI + ADMETlab share a clean canonical key, so they co-populate one row and spread is computed."""
    recs = [admet_ai_rec(CYP3A4=0.2), admetlab3_rec({"CYP3A4": 0.9})]
    cyp = _prop(aggregate({"m": recs}).molecules[0], "CYP3A4")
    assert cyp.n_models == 2
    assert {r.model for r in cyp.reads} == {ModelName.admet_ai, ModelName.admetlab3}
    assert cyp.spread == 0.7 > PROB_SPREAD_FLAG
    assert cyp.divergent is True
