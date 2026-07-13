"""Tests for the herg aggregator: hERG_block (trained 4-arch fusion) + NaV1.5 / CaV1.2 context features.

Synthetic ``OutputRecord``-shaped inputs (laptop, core env - no box, no GPU). They pin the science that
must survive the shape change:
- three identity P(block) probabilities (admet_ai / bayesherg / cardiotox_net) harmonize onto hERG_block
  (their reads) and are calibrated onto the pIC50 target by the trained spec (interval attached);
- CardioGenAI's "hERG pIC50" (literal space) is CARRIED as a source with value=None (raw pIC50 in
  ``raw["cardiogenai"]``) - scored from raw by the spec, never as a probability read;
- BayeshERG's aleatoric/epistemic split and CardioTox's AD flag / Morgan on-bits ride along as native
  uncertainty signals keyed ``model_type`` in ``f.uncertainty``;
- NaV1.5 and CaV1.2 pIC50s are DIFFERENT entities -> their own single-source features, never fused;
- any subset (none -> score None) is tolerated.

Output shape (per feature): score, unit, interval[low,high], reads{model:harmonized}, raw{model:native},
uncertainty{model_type:value}. Exact fused values are pinned in tests/test_fusion.py.
"""

from __future__ import annotations

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


def cardiotox(p_block: float, ad_in_domain: bool | None = None, onbits: int | None = None) -> dict:
    return {"model": ModelName.cardiotox_net, "endpoint_values": {"P_block": p_block},
            "uncertainty": {"ad_in_domain": ad_in_domain, "extra": {"morgan_onbits": onbits}},
            "raw": {}, "provenance": PROV}


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


# -------------------------------------------------------------------------- the three probability sources
def test_three_probabilities_are_identity_reads():
    f = _feat(aggregate({"m": [admet_ai(0.3), bayesherg(0.42), cardiotox(0.6)]}).molecules[0], HERG_BLOCK)
    assert f.reads["admet_ai"] == 0.3
    assert f.reads["bayesherg"] == 0.42
    assert f.reads["cardiotox_net"] == 0.6


def test_bayesherg_alea_epis_ride_along_as_native_uncertainty():
    f = _feat(aggregate({"m": [bayesherg(0.42, alea=0.11, epis=0.07)]}).molecules[0], HERG_BLOCK)
    assert f.uncertainty["bayesherg_aleatoric"] == 0.11
    assert f.uncertainty["bayesherg_epistemic"] == 0.07


def test_cardiotox_ad_flag_and_onbits_ride_along_as_native_uncertainty():
    f = _feat(aggregate({"m": [cardiotox(0.6, ad_in_domain=False, onbits=120)]}).molecules[0], HERG_BLOCK)
    assert f.uncertainty["cardiotox_net_ad_in_domain"] is False
    assert f.uncertainty["cardiotox_net_morgan_onbits"] == 120


def test_probabilities_gathered_and_scored_via_trained_spec():
    # The trained 4-arch spec calibrates the three P(block) probabilities onto the pIC50 target (exact
    # fused value pinned in tests/test_fusion.py). Assert the reads are gathered and a calibrated pIC50
    # score + interval exist - not the old equal-weight probability mean.
    f = _feat(aggregate({"m": [admet_ai(0.4), bayesherg(0.2), cardiotox(0.6)]}).molecules[0], HERG_BLOCK)
    assert len(f.reads) == 3
    assert f.score is not None and f.interval is not None


def test_convergent_sources_have_low_uncertainty_divergent_high():
    tight = _feat(aggregate({"m": [admet_ai(0.5), bayesherg(0.5), cardiotox(0.5)]}).molecules[0], HERG_BLOCK)
    wide = _feat(aggregate({"m": [admet_ai(0.1), bayesherg(0.5), cardiotox(0.9)]}).molecules[0], HERG_BLOCK)
    tight_width = tight.interval[1] - tight.interval[0]
    wide_width = wide.interval[1] - wide.interval[0]
    assert tight_width < wide_width


# ------------------------------------------------------ cardiogenai pIC50 now scored via from_raw (F-1 resolved)
def test_cardiogenai_pic50_is_scored_from_raw():
    recs = [admet_ai(0.4), bayesherg(0.2), cardiotox(0.6), cardiogenai(herg=7.0)]
    f = _feat(aggregate({"m": recs}).molecules[0], HERG_BLOCK)
    assert "cardiogenai" not in f.reads               # still value=None on the axis; its pIC50 lives in raw
    assert f.raw["cardiogenai"] == 7.0
    assert len(f.reads) == 3                           # the three probability reads
    assert f.score is not None                         # all four architectures contribute (cardiogenai via from_raw)


def test_cardiogenai_alone_is_scored_from_its_raw_pic50():
    f = _feat(aggregate({"m": [cardiogenai(herg=6.0)]}).molecules[0], HERG_BLOCK)
    assert f.reads == {} and f.raw["cardiogenai"] == 6.0
    assert f.score is not None                         # scored from raw pIC50 (others imputed), no longer None


# -------------------------------------------------------------------------- nav1.5 / cav1.2 separate entities
def test_nav_and_cav_are_separate_single_source_features():
    mol = aggregate({"m": [cardiogenai(nav=5.5, cav=4.2)]}).molecules[0]
    nav = _feat(mol, NAV_BLOCK)
    cav = _feat(mol, CAV_BLOCK)
    assert nav.score == 5.5 and nav.reads == {"cardiogenai": 5.5} and nav.interval is None
    assert cav.score == 4.2 and cav.reads == {"cardiogenai": 4.2} and cav.interval is None


def test_channels_never_fold_into_herg_block():
    mol = aggregate({"m": [admet_ai(0.4), cardiogenai(herg=7.0, nav=5.5, cav=4.2)]}).molecules[0]
    herg = _feat(mol, HERG_BLOCK)
    # the NaV/CaV pIC50s are their own features, never sources of hERG_block
    assert set(herg.reads) == {"admet_ai"} and set(herg.raw) == {"cardiogenai"}
    assert herg.score is not None  # calibrated fusion of admet_ai P(block) + cardiogenai pIC50


# -------------------------------------------------------------------------- subsets / graceful fallbacks
def test_single_probability_source_is_calibrated():
    f = _feat(aggregate({"m": [admet_ai(0.4)]}).molecules[0], HERG_BLOCK)
    assert f.score is not None and f.reads == {"admet_ai": 0.4}   # calibrated to pIC50 (not the raw 0.4)


def test_no_herg_source_yields_null_score_no_crash():
    rec = {"model": ModelName.opera, "endpoint_values": {"LogD": 1.0},
           "uncertainty": None, "raw": {}, "provenance": PROV}
    mol = aggregate({"m": [rec]}).molecules[0]
    for f in mol.features:
        assert f.reads == {} and f.raw == {} and f.score is None


def test_missing_or_nonnumeric_value_is_not_a_source():
    recs = [admet_ai(0.4), {"model": ModelName.bayesherg, "endpoint_values": {"P_block": None},
                            "uncertainty": None, "raw": {}, "provenance": PROV}]
    f = _feat(aggregate({"m": recs}).molecules[0], HERG_BLOCK)
    assert set(f.reads) == {"admet_ai"}


# -------------------------------------------------------------------------- shape / plumbing
def test_endpoint_identity_and_uniform_shape():
    res = aggregate({"m": [admet_ai(0.4)]})
    assert res.endpoint == Endpoint.herg and res.n_molecules == 1
    mol = res.molecules[0]
    assert mol.endpoint == Endpoint.herg and mol.mol_id == "m"
    assert {f.feature for f in mol.features} == {HERG_BLOCK, NAV_BLOCK, CAV_BLOCK}
    assert set(type(mol).model_fields) == {"endpoint", "mol_id", "features"}
    assert set(type(mol.features[0]).model_fields) == {
        "feature", "score", "unit", "interval", "reads", "raw", "uncertainty"}


def test_multiple_molecules_independent():
    res = aggregate({"safe": [admet_ai(0.05)], "risky": [admet_ai(0.95)]})
    by = {m.mol_id: _feat(m, HERG_BLOCK).score for m in res.molecules}
    assert by["safe"] is not None and by["risky"] is not None
    assert by["risky"] > by["safe"]   # monotone calibration: higher P(block) -> higher pIC50


def test_input_shapes_normalize_the_same():
    recs = [admet_ai(0.4)]
    mols = [aggregate({"FTO-43": recs}).molecules[0],
            aggregate([("FTO-43", recs)]).molecules[0],
            aggregate([{"mol_id": "FTO-43", "records": recs}]).molecules[0]]
    scores = {_feat(m, HERG_BLOCK).score for m in mols}
    assert all(m.mol_id == "FTO-43" for m in mols)
    assert len(scores) == 1 and scores.pop() is not None   # same calibrated score across all input shapes
