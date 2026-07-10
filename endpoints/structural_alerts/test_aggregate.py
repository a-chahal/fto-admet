"""Tests for the structural_alerts aggregator: deterministic pains / brenk / nih counts, no uncertainty.

Synthetic ``OutputRecord``-shaped inputs (laptop, core env - no box, no GPU). They pin the science that
must survive the shape change:
- three single-source count features: ``pains`` / ``brenk`` from pains_brenk's counts, ``nih`` from admet_ai;
- score = the deterministic count, uncertainty always None (a substructure tally has no spread);
- counts are NEVER ensembled across models - each feature carries exactly one source;
- pains_brenk's backing match names are summarized into the Source note (raw stays scalar, not a list);
- a clean molecule (count 0) still reports a source; a missing source yields an empty feature, no crash.
"""

from __future__ import annotations

from core.models import Endpoint, ModelName
from endpoints.structural_alerts.aggregate import BRENK, NIH, PAINS, aggregate

PROV = {"model": "test"}


def pains_brenk(pains=None, brenk=None, pains_matches=None, brenk_matches=None) -> dict:
    """A pains_brenk-shaped record: counts in endpoint_values, named matches ({name, atoms}) in raw."""
    return {
        "model": ModelName.pains_brenk,
        "endpoint_values": {"PAINS_count": pains, "BRENK_count": brenk},
        "uncertainty": None,
        "raw": {"PAINS_matches": pains_matches or [], "BRENK_matches": brenk_matches or []},
        "provenance": PROV,
    }


def admet_ai(*, nih=None, pains_alert=None, brenk_alert=None) -> dict:
    """An admet_ai-shaped record: count shortcuts in endpoint_values, no matched-alert names."""
    ev: dict = {}
    if nih is not None:
        ev["NIH_alert"] = nih
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
def test_pains_and_brenk_counts_are_the_feature_score():
    recs = [pains_brenk(
        pains=2, brenk=1,
        pains_matches=[{"name": "quinone_A", "atoms": [1, 2]}, {"name": "catechol_A", "atoms": [4]}],
        brenk_matches=[{"name": "michael_acceptor", "atoms": [0]}],
    )]
    mol = aggregate({"m": recs}).molecules[0]
    p, b = _feat(mol, PAINS), _feat(mol, BRENK)
    assert p.score == 2.0 and p.uncertainty is None and p.n_sources == 1
    assert b.score == 1.0 and b.uncertainty is None and b.n_sources == 1


def test_nih_count_comes_from_admet_ai():
    mol = aggregate({"m": [admet_ai(nih=3)]}).molecules[0]
    n = _feat(mol, NIH)
    assert n.score == 3.0 and n.uncertainty is None and n.n_sources == 1
    assert _src(n, "admet_ai").value == 3.0


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
    mol = aggregate({"m": [pains_brenk(pains=0, brenk=0)]}).molecules[0]
    assert _feat(mol, PAINS).score == 0.0 and _feat(mol, PAINS).n_sources == 1
    assert _feat(mol, BRENK).score == 0.0 and _feat(mol, BRENK).n_sources == 1


def test_counts_are_never_ensembled_across_models():
    # admet_ai's PAINS_alert shortcut is NOT read into the pains feature - only pains_brenk feeds it.
    recs = [pains_brenk(pains=0, brenk=0), admet_ai(pains_alert=2, brenk_alert=5, nih=1)]
    mol = aggregate({"m": recs}).molecules[0]
    p = _feat(mol, PAINS)
    assert p.n_sources == 1 and p.score == 0.0          # only pains_brenk's 0, admet_ai not fused in
    assert [s.model for s in p.sources] == ["pains_brenk"]
    assert _feat(mol, NIH).score == 1.0                 # nih still sourced from admet_ai


# -------------------------------------------------------------------------- subsets / graceful fallbacks
def test_missing_source_yields_empty_feature_no_crash():
    # only an unrelated record: all three features present but empty (no crash, no fabricated zero)
    rec = {"model": ModelName.bayesherg, "endpoint_values": {"P_block": 0.5},
           "uncertainty": None, "raw": {}, "provenance": PROV}
    mol = aggregate({"m": [rec]}).molecules[0]
    for name in (PAINS, BRENK, NIH):
        f = _feat(mol, name)
        assert f.n_sources == 0 and f.score is None and f.uncertainty is None


def test_null_count_is_not_a_source():
    mol = aggregate({"m": [pains_brenk(pains=None, brenk=None)]}).molecules[0]
    assert _feat(mol, PAINS).n_sources == 0 and _feat(mol, PAINS).score is None


# -------------------------------------------------------------------------- shape / plumbing
def test_endpoint_identity_and_uniform_shape():
    res = aggregate({"m": [pains_brenk(pains=1), admet_ai(nih=0)]})
    assert res.endpoint == Endpoint.structural_alerts and res.n_molecules == 1
    mol = res.molecules[0]
    assert mol.endpoint == Endpoint.structural_alerts and mol.mol_id == "m"
    assert {f.feature for f in mol.features} == {PAINS, BRENK, NIH}
    assert set(type(mol).model_fields) == {"endpoint", "mol_id", "features"}
    assert set(type(mol.features[0]).model_fields) == {
        "feature", "score", "uncertainty", "unit", "n_sources", "sources"}


def test_multiple_molecules_independent():
    hit = pains_brenk(pains=2, pains_matches=[{"name": "q", "atoms": [0]}])
    clean = pains_brenk(pains=0, brenk=0)
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
