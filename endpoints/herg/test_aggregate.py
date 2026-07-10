"""Tests for the herg aggregator: hERG_block (3-prob ensemble) + NaV1.5 / CaV1.2 context features.

Synthetic ``OutputRecord``-shaped inputs (laptop, core env - no box, no GPU). They pin the science that
must survive the shape change:
- three identity P(block) probabilities (admet_ai / bayesherg / cardiotox_net) harmonize onto hERG_block;
  score = equally-weighted mean, uncertainty = std over the same values;
- CardioGenAI's "hERG pIC50" (literal space) is CARRIED as a source with value=None (raw pIC50 visible)
  and NEVER enters the mean - the pIC50 -> P(block) mapping is DEFERRED (F-1);
- NaV1.5 and CaV1.2 pIC50s are DIFFERENT entities -> their own single-source features, never fused;
- any subset (single source -> uncertainty None; none -> score None) is tolerated.
"""

from __future__ import annotations

import math

from core.models import Endpoint, ModelName
from endpoints.herg.aggregate import (
    CAV_BLOCK,
    HERG_BLOCK,
    NAV_BLOCK,
    aggregate,
)

PROV = {"model": "test"}


def admet_ai(p_block: float) -> dict:
    return {"model": ModelName.admet_ai, "endpoint_values": {"hERG": p_block},
            "uncertainty": None, "raw": {}, "provenance": PROV}


def bayesherg(p_block: float, alea: float | None = None, epis: float | None = None) -> dict:
    return {"model": ModelName.bayesherg, "endpoint_values": {"P_block": p_block},
            "uncertainty": {"aleatoric": alea, "epistemic": epis}, "raw": {}, "provenance": PROV}


def cardiotox(p_block: float) -> dict:
    return {"model": ModelName.cardiotox_net, "endpoint_values": {"P_block": p_block},
            "uncertainty": None, "raw": {}, "provenance": PROV}


def cardiogenai(*, herg: float | None = None, nav: float | None = None, cav: float | None = None) -> dict:
    ev: dict = {}
    if herg is not None:
        ev["hERG pIC50"] = herg
    if nav is not None:
        ev["NaV1.5 pIC50"] = nav
    if cav is not None:
        ev["CaV1.2 pIC50"] = cav
    return {"model": ModelName.cardiogenai, "endpoint_values": ev,
            "uncertainty": None, "raw": {}, "provenance": PROV}


def _feat(mol, name):
    return next(f for f in mol.features if f.feature == name)


def _src(feature, model):
    return next(s for s in feature.sources if s.model == model)


# -------------------------------------------------------------------------- the three probability sources
def test_three_probabilities_are_identity_sources():
    f = _feat(aggregate({"m": [admet_ai(0.3), bayesherg(0.42), cardiotox(0.6)]}).molecules[0], HERG_BLOCK)
    assert _src(f, "admet_ai").value == 0.3
    assert _src(f, "bayesherg").value == 0.42
    assert _src(f, "cardiotox_net").value == 0.6


def test_bayesherg_note_carries_alea_epis():
    f = _feat(aggregate({"m": [bayesherg(0.42, alea=0.11, epis=0.07)]}).molecules[0], HERG_BLOCK)
    note = _src(f, "bayesherg").note
    assert "alea=0.11" in note and "epis=0.07" in note


def test_score_is_mean_and_uncertainty_is_std_over_probabilities():
    f = _feat(aggregate({"m": [admet_ai(0.4), bayesherg(0.2), cardiotox(0.6)]}).molecules[0], HERG_BLOCK)
    vals = [0.4, 0.2, 0.6]
    mean = sum(vals) / 3
    var = sum((x - mean) ** 2 for x in vals) / 3
    assert f.n_sources == 3
    assert abs(f.score - mean) < 1e-9
    assert abs(f.uncertainty - math.sqrt(var)) < 1e-9


def test_convergent_sources_have_low_uncertainty_divergent_high():
    tight = _feat(aggregate({"m": [admet_ai(0.5), bayesherg(0.5), cardiotox(0.5)]}).molecules[0], HERG_BLOCK)
    wide = _feat(aggregate({"m": [admet_ai(0.1), bayesherg(0.5), cardiotox(0.9)]}).molecules[0], HERG_BLOCK)
    assert tight.uncertainty < wide.uncertainty


# -------------------------------------------------------------------------- cardiogenai carried, not scored
def test_cardiogenai_pic50_is_carried_but_excluded_from_score():
    recs = [admet_ai(0.4), bayesherg(0.2), cardiotox(0.6), cardiogenai(herg=7.0)]
    f = _feat(aggregate({"m": recs}).molecules[0], HERG_BLOCK)
    cg = _src(f, "cardiogenai")
    assert cg.value is None                     # NOT scored: pIC50 -> P(block) is DEFERRED (F-1)
    assert cg.raw == 7.0 and cg.raw_unit == "pIC50"
    assert f.n_sources == 4                      # carried as a source
    # score is still the mean of the THREE real probabilities, cardiogenai excluded
    assert abs(f.score - (0.4 + 0.2 + 0.6) / 3) < 1e-9


def test_deferred_marker_present_in_cardiogenai_note():
    f = _feat(aggregate({"m": [cardiogenai(herg=6.0)]}).molecules[0], HERG_BLOCK)
    assert "DEFERRED" in _src(f, "cardiogenai").note
    assert f.score is None and f.n_sources == 1  # only a carried value -> no numeric score


# -------------------------------------------------------------------------- nav1.5 / cav1.2 separate entities
def test_nav_and_cav_are_separate_single_source_features():
    mol = aggregate({"m": [cardiogenai(nav=5.5, cav=4.2)]}).molecules[0]
    nav = _feat(mol, NAV_BLOCK)
    cav = _feat(mol, CAV_BLOCK)
    assert nav.score == 5.5 and nav.n_sources == 1 and nav.uncertainty is None
    assert cav.score == 4.2 and cav.n_sources == 1 and cav.uncertainty is None


def test_channels_never_fold_into_herg_block():
    mol = aggregate({"m": [admet_ai(0.4), cardiogenai(herg=7.0, nav=5.5, cav=4.2)]}).molecules[0]
    herg = _feat(mol, HERG_BLOCK)
    # the NaV/CaV pIC50s are their own features, never sources of hERG_block
    assert [s.model for s in herg.sources] == ["admet_ai", "cardiogenai"]
    assert herg.score == 0.4  # only admet_ai's probability


# -------------------------------------------------------------------------- subsets / graceful fallbacks
def test_single_probability_source_has_score_but_no_uncertainty():
    f = _feat(aggregate({"m": [admet_ai(0.4)]}).molecules[0], HERG_BLOCK)
    assert f.score == 0.4 and f.uncertainty is None and f.n_sources == 1


def test_no_herg_source_yields_null_score_no_crash():
    rec = {"model": ModelName.opera, "endpoint_values": {"LogD": 1.0},
           "uncertainty": None, "raw": {}, "provenance": PROV}
    mol = aggregate({"m": [rec]}).molecules[0]
    for f in mol.features:
        assert f.n_sources == 0 and f.score is None


def test_missing_or_nonnumeric_value_is_not_a_source():
    recs = [admet_ai(0.4), {"model": ModelName.bayesherg, "endpoint_values": {"P_block": None},
                            "uncertainty": None, "raw": {}, "provenance": PROV}]
    f = _feat(aggregate({"m": recs}).molecules[0], HERG_BLOCK)
    assert [s.model for s in f.sources] == ["admet_ai"]


# -------------------------------------------------------------------------- shape / plumbing
def test_endpoint_identity_and_uniform_shape():
    res = aggregate({"m": [admet_ai(0.4)]})
    assert res.endpoint == Endpoint.herg and res.n_molecules == 1
    mol = res.molecules[0]
    assert mol.endpoint == Endpoint.herg and mol.mol_id == "m"
    assert {f.feature for f in mol.features} == {HERG_BLOCK, NAV_BLOCK, CAV_BLOCK}
    assert set(type(mol).model_fields) == {"endpoint", "mol_id", "features"}
    assert set(type(mol.features[0]).model_fields) == {
        "feature", "score", "uncertainty", "unit", "n_sources", "sources"}


def test_multiple_molecules_independent():
    res = aggregate({"safe": [admet_ai(0.05)], "risky": [admet_ai(0.95)]})
    by = {m.mol_id: _feat(m, HERG_BLOCK).score for m in res.molecules}
    assert by == {"safe": 0.05, "risky": 0.95}


def test_input_shapes_normalize_the_same():
    recs = [admet_ai(0.4)]
    as_map = aggregate({"FTO-43": recs}).molecules[0]
    as_pairs = aggregate([("FTO-43", recs)]).molecules[0]
    as_dicts = aggregate([{"mol_id": "FTO-43", "records": recs}]).molecules[0]
    for m in (as_map, as_pairs, as_dicts):
        assert m.mol_id == "FTO-43"
        assert _feat(m, HERG_BLOCK).score == 0.4
