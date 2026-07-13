"""Tests for the distribution aggregator: three separate entities (penetration / druglikeness / efflux).

Synthetic ``OutputRecord``-shaped inputs (laptop, core env - no box, no GPU). They pin:
- bbb_penetration carries the three native reads (0-6 score, probability, boolean) and fuses them via the
  trained rule spec into a calibrated log Kp,uu score;
- cns_druglikeness (CNS_MPO) is a SEPARATE feature, never folded into penetration;
- pgp_efflux is derived from admet_ai's Pgp_Broccatelli, a third separate entity (F-4).

Output shape (per feature): score, unit, interval[low,high], reads{model:harmonized}, raw{model:native},
uncertainty{model_type:value}. Exact fused values are pinned in tests/test_fusion.py.
"""

from __future__ import annotations

from core.models import Endpoint, ModelName
from endpoints.distribution.aggregate import DRUGLIKENESS, EFFLUX, PENETRATION, aggregate

PROV = {"model": "test"}


def bbb_score(v: float) -> dict:
    return {"model": ModelName.bbb_score, "endpoint_values": {"BBB_Score": v},
            "uncertainty": None, "raw": {}, "provenance": PROV}


def cns_mpo(v: float) -> dict:
    return {"model": ModelName.cns_mpo, "endpoint_values": {"CNS_MPO": v},
            "uncertainty": None, "raw": {}, "provenance": PROV}


def admet_ai(*, bbb: float | None = None, pgp: float | None = None) -> dict:
    ev: dict = {}
    if bbb is not None:
        ev["BBB_Martins"] = bbb
    if pgp is not None:
        ev["Pgp_Broccatelli"] = pgp
    return {"model": ModelName.admet_ai, "endpoint_values": ev, "uncertainty": None, "raw": {}, "provenance": PROV}


def boiled_egg(bbb: bool) -> dict:
    return {"model": ModelName.boiled_egg, "endpoint_values": {"BBB_boiled_egg": bbb},
            "uncertainty": None, "raw": {}, "provenance": PROV}


def _feat(mol, name):
    return next(f for f in mol.features if f.feature == name)


# -------------------------------------------------------------------------- penetration: 3 reads, fused score
def test_penetration_scores_the_trained_rule_fusion():
    recs = [bbb_score(5.13), admet_ai(bbb=0.95), boiled_egg(True)]
    f = _feat(aggregate({"m": recs}).molecules[0], PENETRATION)
    assert f.score is not None                            # trained rule fusion -> calibrated log Kp,uu (was None)
    assert len(f.reads) == 3
    assert f.reads["bbb_score"] == 5.13
    assert f.reads["admet_ai"] == 0.95                    # carried (contaminated on the Kp,uu set, not in the spec)
    assert f.reads["boiled_egg"] is True                 # boolean read carried natively, scored as 0/1


# -------------------------------------------------------------------------- cns druglikeness is separate
def test_cns_mpo_is_a_separate_feature_not_folded_into_penetration():
    recs = [bbb_score(5.13), cns_mpo(5.0), admet_ai(bbb=0.95)]
    mol = aggregate({"m": recs}).molecules[0]
    pen = _feat(mol, PENETRATION)
    dl = _feat(mol, DRUGLIKENESS)
    assert "cns_mpo" not in pen.reads                      # NOT in penetration
    assert dl.score == 5.0 and dl.reads == {"cns_mpo": 5.0}  # its own single-source value


# -------------------------------------------------------------------------- efflux derived from generalist
def test_pgp_efflux_derived_from_admet_ai():
    # The aggregator's job: gather admet_ai's Pgp_Broccatelli via extract_pgp. The SCORE is now produced
    # by the trained fusion spec (exact value tested in tests/test_fusion.py), so assert the source is
    # preserved and a calibrated score + interval exist - not the raw number.
    f = _feat(aggregate({"m": [admet_ai(pgp=0.44)]}).molecules[0], EFFLUX)
    assert f.reads == {"admet_ai": 0.44}                            # raw source preserved via extract_pgp
    assert f.score is not None and f.interval is not None           # trained -> calibrated efflux + conformal interval


# -------------------------------------------------------------------------- three features, uniform shape
def test_three_features_and_uniform_shape():
    recs = [bbb_score(5.13), cns_mpo(5.0), admet_ai(bbb=0.95, pgp=0.44), boiled_egg(True)]
    res = aggregate({"m": recs})
    assert res.endpoint == Endpoint.distribution and res.n_molecules == 1
    mol = res.molecules[0]
    assert {f.feature for f in mol.features} == {PENETRATION, DRUGLIKENESS, EFFLUX}
    assert set(type(mol).model_fields) == {"endpoint", "mol_id", "features"}
    assert set(type(mol.features[0]).model_fields) == {
        "feature", "score", "unit", "interval", "reads", "raw", "uncertainty"}


def test_missing_signals_yield_empty_features_no_crash():
    # only an unrelated record: all three features present but empty (no crash, no fabricated values)
    rec = {"model": ModelName.bayesherg, "endpoint_values": {"P_block": 0.5},
           "uncertainty": None, "raw": {}, "provenance": PROV}
    mol = aggregate({"m": [rec]}).molecules[0]
    for f in mol.features:
        assert f.reads == {} and f.score is None
