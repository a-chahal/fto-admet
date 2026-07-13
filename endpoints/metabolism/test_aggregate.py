"""Tests for the metabolism aggregator: one site-of-metabolism feature, scored on FAME3R alone (F-2).

Synthetic ``OutputRecord``-shaped inputs (laptop, core env - no box, no GPU). They pin the science:
- metabolism is ONLY site-of-metabolism; hepatic CLint (stability) is the clearance endpoint's, not
  duplicated here (so admet_ai's clearance heads are ignored by this aggregator);
- site_of_metabolism is scored on the FAME3R ``max_som_probability`` alone; SMARTCyp's ``top_som_score``
  is carried with ``value=None`` (opposite direction, incompatible kJ/mol scale) - its native Score lives
  in ``f.raw["smartcyp"]`` and is NEVER averaged into the probability (F-2);
- FAME3R's native AD reliability (``ad_index`` + mean FAME3RScore) rides along in ``f.uncertainty``;
- the per-atom tables stay in each model's ``rec.raw`` - not copied into a Source.

Output shape (per feature): score, unit, interval[low,high], reads{model:harmonized}, raw{model:native},
uncertainty{model_type:value}.
"""

from __future__ import annotations

from core.models import Endpoint, ModelName
from endpoints.metabolism.aggregate import SOM, aggregate

PROV = {"model": "test"}


def admet_ai(*, hepatocyte: float | None = None) -> dict:
    # ADMET-AI's clearance heads must be IGNORED here (they belong to the clearance endpoint, not metabolism).
    return {"model": ModelName.admet_ai,
            "endpoint_values": {"Clearance_Hepatocyte_AZ": hepatocyte, "HIA_Hou": 0.98},
            "uncertainty": None, "raw": {}, "provenance": PROV}


def fame3r(max_prob: float, top_atom: int = 3,
           ad_index: float | None = None, score_mean: float | None = None) -> dict:
    """A FAME3R record: scalar max probability + top atom in endpoint_values; per-atom table in raw."""
    return {"model": ModelName.fame3r,
            "endpoint_values": {"max_som_probability": max_prob, "top_som_atom_index": top_atom},
            "uncertainty": {"ad_index": ad_index, "extra": {"fame3r_score_mean": score_mean}},
            "raw": {"atoms": [{"atom_index": top_atom, "som_probability": max_prob}]},
            "provenance": PROV}


def smartcyp(top_score: float, top_atom: int = 3) -> dict:
    """A SMARTCyp record: scalar top Score + top atom in endpoint_values; per-atom table in raw."""
    return {"model": ModelName.smartcyp,
            "endpoint_values": {"top_som_score": top_score, "top_som_atom_index": top_atom},
            "uncertainty": None, "raw": {"atoms": [{"atom_index": top_atom, "Score": top_score}]},
            "provenance": PROV}


def _feat(mol, name):
    return next(f for f in mol.features if f.feature == name)


# -------------------------------------------------------------------------- metabolism is SoM only
def test_only_one_feature_and_clearance_heads_are_ignored():
    mol = aggregate({"m": [admet_ai(hepatocyte=35.0), fame3r(0.9)]}).molecules[0]
    assert {f.feature for f in mol.features} == {SOM}   # no hepatocyte/microsomal CLint here
    assert _feat(mol, SOM).score == 0.9                 # admet_ai's clearance head did not enter


# -------------------------------------------------------------------------- site of metabolism (F-2)
def test_som_scored_on_fame3r_probability_alone():
    f = _feat(aggregate({"m": [fame3r(0.95, top_atom=3)]}).molecules[0], SOM)
    assert f.score == 0.95 and f.interval is None
    assert f.reads == {"fame3r": 0.95}


def test_fame3r_ad_reliability_rides_along_as_native_uncertainty():
    f = _feat(aggregate({"m": [fame3r(0.95, ad_index=0.82, score_mean=0.31)]}).molecules[0], SOM)
    assert f.uncertainty["fame3r_ad_index"] == 0.82
    assert f.uncertainty["fame3r_fame3r_score_mean"] == 0.31


def test_smartcyp_carried_as_concordance_not_fused():
    """SMARTCyp's Score is on a different kJ/mol scale (opposite direction): value=None, never averaged."""
    f = _feat(aggregate({"m": [fame3r(0.95, top_atom=3), smartcyp(20.0, top_atom=3)]}).molecules[0], SOM)
    assert f.score == 0.95            # SMARTCyp's 20.0 kJ/mol Score does NOT move the FAME3R probability
    assert f.reads == {"fame3r": 0.95}       # smartcyp value=None never becomes a read
    assert f.raw["smartcyp"] == 20.0         # its native Score lives in raw


def test_smartcyp_alone_has_no_score():
    f = _feat(aggregate({"m": [smartcyp(15.0, top_atom=1)]}).molecules[0], SOM)
    assert f.score is None and f.interval is None
    assert f.reads == {} and f.raw["smartcyp"] == 15.0   # carried in raw, no read, no score


def test_no_som_source_yields_empty_feature():
    f = _feat(aggregate({"m": [admet_ai(hepatocyte=5.0)]}).molecules[0], SOM)
    assert f.reads == {} and f.raw == {} and f.score is None


def test_per_atom_tables_are_not_copied_into_reads_or_raw():
    f = _feat(aggregate({"m": [fame3r(0.9), smartcyp(20.0)]}).molecules[0], SOM)
    for v in list(f.reads.values()) + list(f.raw.values()):
        assert not isinstance(v, (list, tuple))


# -------------------------------------------------------------------------- shape / plumbing
def test_uniform_shape():
    res = aggregate({"FTO-43": [fame3r(0.9), smartcyp(20.0)]})
    assert res.endpoint == Endpoint.metabolism and res.n_molecules == 1
    mol = res.molecules[0]
    assert set(type(mol).model_fields) == {"endpoint", "mol_id", "features"}
    assert set(type(mol.features[0]).model_fields) == {
        "feature", "score", "unit", "interval", "reads", "raw", "uncertainty"}


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
    errored = {"model": ModelName.fame3r,
               "endpoint_values": {"max_som_probability": None, "top_som_atom_index": None},
               "uncertainty": None, "raw": {"error": "RDKit could not parse SMILES"}, "provenance": PROV}
    f = _feat(aggregate({"bad": [errored]}).molecules[0], SOM)
    assert f.reads == {} and f.score is None
