"""Tests for the permeability aggregator: three separate entities, two scores DEFERRED (mixed axis).

Synthetic ``OutputRecord``-shaped inputs (laptop, core env - no box, no GPU). They pin:
- passive_permeability (Caco2 log Papp + PAMPA probability) has NO fused score yet: two incompatible
  scales, deferred until calibration -> score None;
- intestinal_absorption (HIA_Hou probability + BOILED-Egg boolean) is also score DEFERRED;
- pgp_efflux is derived from admet_ai's Pgp_Broccatelli, a third separate entity (F-4) that DOES score.

Output shape (per feature): score, unit, interval[low,high], reads{model:harmonized}, raw{model:native},
uncertainty{model_type:value}.
"""

from __future__ import annotations

from core.models import Endpoint, ModelName
from endpoints.permeability.aggregate import ABSORPTION, EFFLUX, PASSIVE, aggregate

PROV = {"model": "test"}


def admet_ai(*, caco2: float | None = None, pampa: float | None = None,
             hia: float | None = None, pgp: float | None = None) -> dict:
    ev: dict = {}
    if caco2 is not None:
        ev["Caco2_Wang"] = caco2
    if pampa is not None:
        ev["PAMPA_NCATS"] = pampa
    if hia is not None:
        ev["HIA_Hou"] = hia
    if pgp is not None:
        ev["Pgp_Broccatelli"] = pgp
    return {"model": ModelName.admet_ai, "endpoint_values": ev,
            "uncertainty": None, "raw": {}, "provenance": PROV}


def boiled_egg(hia: bool) -> dict:
    return {"model": ModelName.boiled_egg, "endpoint_values": {"HIA_boiled_egg": hia},
            "uncertainty": None, "raw": {}, "provenance": PROV}


def _feat(mol, name):
    return next(f for f in mol.features if f.feature == name)


# ------------------------------------------------------ passive permeability: score deferred (mixed axis)
def test_passive_permeability_score_is_deferred():
    recs = [admet_ai(caco2=-4.5, pampa=0.82)]
    f = _feat(aggregate({"m": recs}).molecules[0], PASSIVE)
    assert f.score is None and f.interval is None and f.unit is None   # mixed scales -> deferred, never averaged


def test_passive_permeability_deferred_even_with_a_single_read():
    f = _feat(aggregate({"m": [admet_ai(caco2=-4.5)]}).molecules[0], PASSIVE)
    assert f.score is None


# ------------------------------------------------------ intestinal absorption: prob + bool, score deferred
def test_intestinal_absorption_score_is_deferred():
    recs = [admet_ai(hia=0.9), boiled_egg(True)]
    f = _feat(aggregate({"m": recs}).molecules[0], ABSORPTION)
    assert f.score is None and f.interval is None and f.unit is None


def test_boiled_egg_false_does_not_produce_a_score():
    f = _feat(aggregate({"m": [boiled_egg(False)]}).molecules[0], ABSORPTION)
    assert f.score is None


# ------------------------------------------------------ efflux derived from generalist (DOES score)
def test_pgp_efflux_derived_from_admet_ai():
    f = _feat(aggregate({"m": [admet_ai(pgp=0.44)]}).molecules[0], EFFLUX)
    assert f.score == 0.44 and f.interval is None
    assert f.reads == {"admet_ai": 0.44}


def test_pgp_efflux_out_of_range_rejected():
    # the pgp helper rejects a non-[0,1] value rather than clamping, so it contributes no source
    f = _feat(aggregate({"m": [admet_ai(pgp=1.7)]}).molecules[0], EFFLUX)
    assert f.reads == {} and f.score is None


# ------------------------------------------------------ three features, uniform shape
def test_three_features_and_uniform_shape():
    recs = [admet_ai(caco2=-4.5, pampa=0.82, hia=0.9, pgp=0.44), boiled_egg(True)]
    res = aggregate({"m": recs})
    assert res.endpoint == Endpoint.permeability and res.n_molecules == 1
    mol = res.molecules[0]
    assert mol.endpoint == Endpoint.permeability and mol.mol_id == "m"
    assert {f.feature for f in mol.features} == {PASSIVE, ABSORPTION, EFFLUX}
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


def test_multiple_molecules_independent():
    res = aggregate({"a": [admet_ai(pgp=0.2)], "b": [admet_ai(pgp=0.8)]})
    by = {m.mol_id: _feat(m, EFFLUX).score for m in res.molecules}
    assert by == {"a": 0.2, "b": 0.8}


def test_input_shapes_normalize_the_same():
    recs = [admet_ai(pgp=0.44)]
    as_map = aggregate({"FTO-43": recs}).molecules[0]
    as_pairs = aggregate([("FTO-43", recs)]).molecules[0]
    as_dicts = aggregate([{"mol_id": "FTO-43", "records": recs}]).molecules[0]
    for m in (as_map, as_pairs, as_dicts):
        assert m.mol_id == "FTO-43"
        assert _feat(m, EFFLUX).score == 0.44
