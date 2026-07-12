"""Tests for the structural_alerts aggregator: deterministic pains / brenk / nih counts, no uncertainty.

Synthetic ``OutputRecord``-shaped inputs (laptop, core env - no box, no GPU). They pin the science that
must survive the shape change:
- three single-source count features (``pains`` / ``brenk`` / ``nih``), all from the pains_brenk model;
- score = the deterministic count, uncertainty always None (a substructure tally has no spread);
- counts are NEVER ensembled across models - each feature carries exactly one source;
- pains_brenk's backing match names are summarized into the Source note (raw stays scalar, not a list);
- a clean molecule (count 0) still reports a source; a missing source yields an empty feature, no crash.
"""

from __future__ import annotations

from core.models import Endpoint, ModelName
from endpoints.structural_alerts.aggregate import BRENK, NIH, PAINS, aggregate

PROV = {"model": "test"}


def pains_brenk(pains=None, brenk=None, nih=None,
                pains_matches=None, brenk_matches=None, nih_matches=None) -> dict:
    """A pains_brenk-shaped record: PAINS/BRENK/NIH counts in endpoint_values, named matches in raw."""
    return {
        "model": ModelName.pains_brenk,
        "endpoint_values": {"PAINS_count": pains, "BRENK_count": brenk, "NIH_count": nih},
        "uncertainty": None,
        "raw": {"PAINS_matches": pains_matches or [], "BRENK_matches": brenk_matches or [],
                "NIH_matches": nih_matches or []},
        "provenance": PROV,
    }


def admet_ai(*, pains_alert=None, brenk_alert=None) -> dict:
    """An admet_ai-shaped record: coarse count shortcuts - must NOT be fused into the named-catalog counts."""
    ev: dict = {}
    if pains_alert is not None:
        ev["PAINS_alert"] = pains_alert
    if brenk_alert is not None:
        ev["BRENK_alert"] = brenk_alert
    return {"model": ModelName.admet_ai, "endpoint_values": ev,
            "uncertainty": None, "raw": {}, "provenance": PROV}


def _feat(mol, name):
    return next(f for f in mol.features if f.feature == name)


def _src(feature, model):
    return next(s for s in feature.sources if s.model == model)


# -------------------------------------------------------------------------- counts as the feature score
def test_pains_brenk_nih_counts_are_the_feature_score():
    recs = [pains_brenk(
        pains=2, brenk=1, nih=1,
        pains_matches=[{"name": "quinone_A", "atoms": [1, 2]}, {"name": "catechol_A", "atoms": [4]}],
        brenk_matches=[{"name": "michael_acceptor", "atoms": [0]}],
        nih_matches=[{"name": "reactive_alkyl_halide", "atoms": [3]}],
    )]
    mol = aggregate({"m": recs}).molecules[0]
    for name, exp in ((PAINS, 2.0), (BRENK, 1.0), (NIH, 1.0)):
        f = _feat(mol, name)
        assert f.score == exp and f.uncertainty is None and f.n_sources == 1


def test_nih_count_comes_from_pains_brenk_with_named_matches():
    mol = aggregate({"m": [pains_brenk(nih=1, nih_matches=[{"name": "reactive_alkyl_halide", "atoms": [3]}])]}).molecules[0]
    n = _feat(mol, NIH)
    assert n.score == 1.0 and n.uncertainty is None and n.n_sources == 1
    s = _src(n, "pains_brenk")
    assert s.value == 1.0 and "reactive_alkyl_halide" in s.note


def test_match_names_are_summarized_into_note_not_into_raw():
    recs = [pains_brenk(pains=2, pains_matches=[
        {"name": "quinone_A", "atoms": [1, 2]}, {"name": "catechol_A", "atoms": [4]},
    ])]
    s = _src(_feat(aggregate({"m": recs}).molecules[0], PAINS), "pains_brenk")
    assert "quinone_A" in s.note and "catechol_A" in s.note
    assert s.raw is None                       # raw stays scalar - the match list never lands here


def test_note_when_no_named_matches():
    s = _src(_feat(aggregate({"m": [pains_brenk(pains=1)]}).molecules[0], PAINS), "pains_brenk")
    assert s.note == "no named matches"


# -------------------------------------------------------------------------- clean molecule / determinism
def test_clean_molecule_reports_zero_counts_not_absent():
    mol = aggregate({"m": [pains_brenk(pains=0, brenk=0, nih=0)]}).molecules[0]
    for name in (PAINS, BRENK, NIH):
        assert _feat(mol, name).score == 0.0 and _feat(mol, name).n_sources == 1


def test_counts_are_never_ensembled_across_models():
    # admet_ai's coarse PAINS/BRENK shortcuts are NOT read into the named-catalog features.
    recs = [pains_brenk(pains=0, brenk=0, nih=0), admet_ai(pains_alert=2, brenk_alert=5)]
    mol = aggregate({"m": recs}).molecules[0]
    p = _feat(mol, PAINS)
    assert p.n_sources == 1 and p.score == 0.0
    assert [s.model for s in p.sources] == ["pains_brenk"]


# -------------------------------------------------------------------------- subsets / graceful fallbacks
def test_missing_source_yields_empty_feature_no_crash():
    rec = {"model": ModelName.bayesherg, "endpoint_values": {"P_block": 0.5},
           "uncertainty": None, "raw": {}, "provenance": PROV}
    mol = aggregate({"m": [rec]}).molecules[0]
    for name in (PAINS, BRENK, NIH):
        f = _feat(mol, name)
        assert f.n_sources == 0 and f.score is None and f.uncertainty is None


def test_null_count_is_not_a_source():
    mol = aggregate({"m": [pains_brenk(pains=None, brenk=None, nih=None)]}).molecules[0]
    for name in (PAINS, BRENK, NIH):
        assert _feat(mol, name).n_sources == 0 and _feat(mol, name).score is None


# -------------------------------------------------------------------------- shape / plumbing
def test_endpoint_identity_and_uniform_shape():
    res = aggregate({"m": [pains_brenk(pains=1, nih=0)]})
    assert res.endpoint == Endpoint.structural_alerts and res.n_molecules == 1
    mol = res.molecules[0]
    assert mol.endpoint == Endpoint.structural_alerts and mol.mol_id == "m"
    assert {f.feature for f in mol.features} == {PAINS, BRENK, NIH}
    assert set(type(mol).model_fields) == {"endpoint", "mol_id", "features"}
    assert set(type(mol.features[0]).model_fields) == {
        "feature", "score", "uncertainty", "unit", "n_sources", "sources"}


def test_multiple_molecules_independent():
    hit = pains_brenk(pains=2, pains_matches=[{"name": "q", "atoms": [0]}])
    clean = pains_brenk(pains=0, brenk=0, nih=0)
    res = aggregate({"hit": [hit], "clean": [clean]})
    assert res.n_molecules == 2
    by = {m.mol_id: _feat(m, PAINS).score for m in res.molecules}
    assert by == {"hit": 2.0, "clean": 0.0}


def test_input_shapes_normalize_the_same():
    recs = [pains_brenk(pains=1)]
    as_map = aggregate({"FTO-43": recs}).molecules[0]
    as_pairs = aggregate([("FTO-43", recs)]).molecules[0]
    as_dicts = aggregate([{"mol_id": "FTO-43", "records": recs}]).molecules[0]
    for m in (as_map, as_pairs, as_dicts):
        assert m.mol_id == "FTO-43"
        assert _feat(m, PAINS).score == 1.0
