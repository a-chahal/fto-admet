"""Tests for the metabolism aggregator: three separate features, SoM scored on FAME3R alone (F-2).

Synthetic ``OutputRecord``-shaped inputs (laptop, core env - no box, no GPU). They pin the science that
must survive the shape change:
- hepatocyte_clint and microsomal_clint are SEPARATE single-source features (different units/matrices,
  never combined, F-3/F-17);
- site_of_metabolism is scored on the FAME3R ``max_som_probability`` alone; SMARTCyp's ``top_som_score``
  is carried as a concordance Source with ``value=None`` (opposite direction, incompatible kJ/mol scale)
  and is NEVER averaged into the probability (F-2);
- the per-atom tables stay in each model's ``rec.raw`` - not copied into a Source;
- any subset (missing sources) degrades gracefully.
"""

from __future__ import annotations

from core.models import Endpoint, ModelName
from endpoints.metabolism.aggregate import (
    HEPATOCYTE,
    MICROSOME,
    SMARTCYP_SCORE_UNIT,
    SOM,
    aggregate,
)

PROV = {"model": "test"}


def admet_ai(*, hepatocyte: float | None = None, microsome: float | None = None) -> dict:
    return {
        "model": ModelName.admet_ai,
        "endpoint_values": {
            "Clearance_Hepatocyte_AZ": hepatocyte,
            "Clearance_Microsome_AZ": microsome,
            "HIA_Hou": 0.98,  # an unrelated head that must be ignored
        },
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }


def fame3r(max_prob: float, top_atom: int = 3) -> dict:
    """A FAME3R record: scalar max probability + top atom in endpoint_values; per-atom table in raw."""
    return {
        "model": ModelName.fame3r,
        "endpoint_values": {"max_som_probability": max_prob, "top_som_atom_index": top_atom},
        "uncertainty": None,
        "raw": {"atoms": [{"atom_index": top_atom, "som_probability": max_prob}]},
        "provenance": PROV,
    }


def smartcyp(top_score: float, top_atom: int = 3) -> dict:
    """A SMARTCyp record: scalar top Score + top atom in endpoint_values; per-atom table in raw."""
    return {
        "model": ModelName.smartcyp,
        "endpoint_values": {"top_som_score": top_score, "top_som_atom_index": top_atom},
        "uncertainty": None,
        "raw": {"atoms": [{"atom_index": top_atom, "Score": top_score}]},
        "provenance": PROV,
    }


def _feat(mol, name):
    return next(f for f in mol.features if f.feature == name)


def _src(feature, model):
    return next(s for s in feature.sources if s.model == model)


# -------------------------------------------------------------------------- the two CLint features
def test_hepatocyte_and_microsome_are_separate_single_source_features():
    mol = aggregate({"m": [admet_ai(hepatocyte=35.0, microsome=50.0)]}).molecules[0]
    hep = _feat(mol, HEPATOCYTE)
    mic = _feat(mol, MICROSOME)
    assert hep.score == 35.0 and hep.uncertainty is None and hep.n_sources == 1
    assert mic.score == 50.0 and mic.uncertainty is None and mic.n_sources == 1
    # Different units => never merged.
    assert hep.unit != mic.unit
    # Both carry the F-17 low-weight/qualitative note.
    assert "F-17" in _src(hep, "admet_ai").note
    assert "F-17" in _src(mic, "admet_ai").note


def test_missing_clint_head_degrades_gracefully():
    mol = aggregate({"m": [admet_ai(hepatocyte=12.0)]}).molecules[0]
    assert _feat(mol, HEPATOCYTE).n_sources == 1 and _feat(mol, HEPATOCYTE).score == 12.0
    assert _feat(mol, MICROSOME).n_sources == 0 and _feat(mol, MICROSOME).score is None


# -------------------------------------------------------------------------- site of metabolism (F-2)
def test_som_scored_on_fame3r_probability_alone():
    f = _feat(aggregate({"m": [fame3r(0.95, top_atom=3)]}).molecules[0], SOM)
    assert f.score == 0.95 and f.uncertainty is None and f.n_sources == 1
    src = _src(f, "fame3r")
    assert src.value == 0.95 and "top atom idx=3" in src.note


def test_smartcyp_carried_as_concordance_not_fused():
    """SMARTCyp's Score is on a different kJ/mol scale (opposite direction): value=None, never averaged."""
    f = _feat(aggregate({"m": [fame3r(0.95, top_atom=3), smartcyp(20.0, top_atom=3)]}).molecules[0], SOM)
    # score is still the FAME3R probability - SMARTCyp's 20.0 kJ/mol Score does NOT move it.
    assert f.score == 0.95
    assert f.n_sources == 2
    sc = _src(f, "smartcyp")
    assert sc.value is None                       # carried, never fused into the mean
    assert (sc.raw, sc.raw_unit) == (20.0, SMARTCYP_SCORE_UNIT)
    assert "not fused" in sc.note and "top SoM atom idx=3" in sc.note


def test_smartcyp_alone_has_no_score():
    """With only SMARTCyp present (no numeric value), the SoM feature carries the read but has no score."""
    f = _feat(aggregate({"m": [smartcyp(15.0, top_atom=1)]}).molecules[0], SOM)
    assert f.score is None and f.uncertainty is None
    assert f.n_sources == 1 and _src(f, "smartcyp").value is None


def test_no_som_source_yields_empty_feature():
    f = _feat(aggregate({"m": [admet_ai(hepatocyte=5.0)]}).molecules[0], SOM)
    assert f.n_sources == 0 and f.score is None


def test_per_atom_tables_are_not_copied_into_sources():
    """The per-atom table stays in rec.raw; the Source carries only the scalar summary, not a list."""
    f = _feat(aggregate({"m": [fame3r(0.9), smartcyp(20.0)]}).molecules[0], SOM)
    for s in f.sources:
        assert not isinstance(s.value, (list, tuple))
        assert not isinstance(s.raw, (list, tuple))


# -------------------------------------------------------------------------- shape / plumbing
def test_three_features_and_uniform_shape():
    recs = [admet_ai(hepatocyte=35.0, microsome=50.0), fame3r(0.9), smartcyp(20.0)]
    res = aggregate({"FTO-43": recs})
    assert res.endpoint == Endpoint.metabolism and res.n_molecules == 1
    mol = res.molecules[0]
    assert {f.feature for f in mol.features} == {HEPATOCYTE, MICROSOME, SOM}
    assert set(type(mol).model_fields) == {"endpoint", "mol_id", "features"}
    assert set(type(mol.features[0]).model_fields) == {
        "feature", "score", "uncertainty", "unit", "n_sources", "sources"}


def test_multiple_molecules_independent():
    res = aggregate({"a": [fame3r(0.2)], "b": [fame3r(0.8)]})
    by = {m.mol_id: _feat(m, SOM).score for m in res.molecules}
    assert by == {"a": 0.2, "b": 0.8}


def test_input_shapes_normalize_the_same():
    recs = [fame3r(0.9, top_atom=3)]
    as_map = aggregate({"FTO-43": recs}).molecules[0]
    as_pairs = aggregate([("FTO-43", recs)]).molecules[0]
    as_dicts = aggregate([{"mol_id": "FTO-43", "records": recs}]).molecules[0]
    for m in (as_map, as_pairs, as_dicts):
        assert m.mol_id == "FTO-43"
        assert _feat(m, SOM).score == 0.9


def test_errored_record_does_not_crash():
    errored = {
        "model": ModelName.fame3r,
        "endpoint_values": {"max_som_probability": None, "top_som_atom_index": None},
        "uncertainty": None,
        "raw": {"error": "RDKit could not parse SMILES"},
        "provenance": PROV,
    }
    f = _feat(aggregate({"bad": [errored]}).molecules[0], SOM)
    assert f.n_sources == 0 and f.score is None
