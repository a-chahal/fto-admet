"""Tests for the toxicity aggregator: a panel of independent single-source features.

Synthetic ``OutputRecord``-shaped inputs (laptop, core env - no box, no GPU). They pin what this endpoint
guarantees after the shape change:
- each ADMET-AI classifier head becomes its OWN single-source P(toxic) feature (score = the value,
  uncertainty undefined for one point);
- ``LD50_Zhu`` is a SEPARATE ``acute_ld50`` magnitude feature (log 1/(mol/kg), up = more toxic), never
  a probability and never folded into another feature;
- the toxicophores count becomes ``tox_alerts`` with the matched names summarized into the source note;
- a feature is emitted ONLY when its source key is present (no fabricated zeros); the output is the
  uniform ``core.aggregate`` shape.
"""

from __future__ import annotations

from core.models import Endpoint, ModelName
from endpoints.toxicity.aggregate import (
    ADMET_AI_PROB_HEADS,
    LD50_FEATURE,
    TOX_ALERTS_FEATURE,
    aggregate,
)

PROV = {"model": "test"}


def admet_ai(**heads) -> dict:
    """An ADMET-AI-shaped record: classifier/regression heads live directly in endpoint_values (TDC names)."""
    return {"model": ModelName.admet_ai, "endpoint_values": dict(heads),
            "uncertainty": None, "raw": {}, "provenance": PROV}


def toxicophores(count=2, names=None) -> dict:
    """A toxicophores-shaped record: count in endpoint_values, matched names in raw."""
    return {"model": ModelName.toxicophores,
            "endpoint_values": {"tox_alert_count": count},
            "uncertainty": None, "raw": {"tox_alert_names": names if names is not None else ["nitro group", "epoxide"]},
            "provenance": PROV}


def _feat(mol, name):
    return next(f for f in mol.features if f.feature == name)


def _has(mol, name) -> bool:
    return any(f.feature == name for f in mol.features)


# -------------------------------------------------------------------------- one feature per ADMET-AI head
def test_each_admet_ai_head_becomes_its_own_single_source_feature():
    rec = admet_ai(**{"DILI": 0.8, "AMES": 0.6, "hERG": 0.4, "NR-AR": 0.1,
                      "SR-p53": 0.3, "Carcinogens_Lagunin": 0.2})
    mol = aggregate({"m": [rec]}).molecules[0]
    got = {f.feature: f.score for f in mol.features}
    assert got == {"dili": 0.8, "ames_mutagenicity": 0.6, "herg_cardiotox": 0.4,
                   "nr_ar": 0.1, "sr_p53": 0.3, "carcinogenicity": 0.2}
    dili = _feat(mol, "dili")
    assert dili.n_sources == 1 and dili.uncertainty is None       # single source -> no disagreement
    assert dili.sources[0].model == "admet_ai"
    assert dili.unit == "P(dili) [0,1] (up = more toxic)"


def test_full_tox21_panel_maps_every_head_by_its_feature_name():
    # feed every mapped head at a distinct value, assert the feature-name -> value mapping is exact.
    values = {key: round(0.01 * (i + 1), 2) for i, key in enumerate(ADMET_AI_PROB_HEADS.values())}
    mol = aggregate({"m": [admet_ai(**values)]}).molecules[0]
    for feature, key in ADMET_AI_PROB_HEADS.items():
        assert _feat(mol, feature).score == values[key]


# -------------------------------------------------------------------------- LD50 is a separate magnitude
def test_ld50_zhu_is_a_separate_magnitude_feature_not_a_probability():
    mol = aggregate({"m": [admet_ai(LD50_Zhu=2.3, DILI=0.5)]}).molecules[0]
    ld50 = _feat(mol, LD50_FEATURE)
    assert ld50.score == 2.3
    assert ld50.unit == "log(1/(mol/kg)) (up = more acutely toxic)"
    assert ld50.n_sources == 1 and ld50.uncertainty is None
    # LD50 never becomes a probability feature; DILI stays its own feature.
    assert _has(mol, "dili")
    assert LD50_FEATURE not in ADMET_AI_PROB_HEADS


# -------------------------------------------------------------------------- toxicophores count -> tox_alerts
def test_toxicophores_count_becomes_tox_alerts_with_names_in_note():
    mol = aggregate({"m": [toxicophores(count=2, names=["nitro group", "michael acceptor"])]}).molecules[0]
    alerts = _feat(mol, TOX_ALERTS_FEATURE)
    assert alerts.score == 2 and alerts.n_sources == 1
    assert alerts.unit == "count of BRENK tox alerts (0 = clean)"
    assert alerts.sources[0].note == "nitro group; michael acceptor"


def test_tox_alerts_zero_count_is_still_emitted_as_a_real_read():
    mol = aggregate({"m": [toxicophores(count=0, names=[])]}).molecules[0]
    alerts = _feat(mol, TOX_ALERTS_FEATURE)
    assert alerts.score == 0 and alerts.sources[0].note is None


# -------------------------------------------------------------------------- emit only present keys
def test_only_present_keys_emit_features_no_fabricated_zeros():
    # a molecule with ONLY DILI reported -> only the dili feature, nothing else invented.
    mol = aggregate({"m": [admet_ai(DILI=0.8)]}).molecules[0]
    assert [f.feature for f in mol.features] == ["dili"]
    assert not _has(mol, "ames_mutagenicity") and not _has(mol, LD50_FEATURE)


def test_missing_or_nonnumeric_value_is_not_a_feature():
    # DILI null and AMES a non-numeric string both drop out; only the numeric hERG survives.
    mol = aggregate({"m": [admet_ai(DILI=None, AMES="n/a", hERG=0.4)]}).molecules[0]
    assert [f.feature for f in mol.features] == ["herg_cardiotox"]


def test_molecule_with_no_toxicity_source_has_no_features():
    unrelated = {"model": ModelName.bayesherg, "endpoint_values": {"P_block": 0.5},
                 "uncertainty": None, "raw": {}, "provenance": PROV}
    mol = aggregate({"m": [unrelated]}).molecules[0]
    assert mol.features == []


# -------------------------------------------------------------------------- shape / plumbing
def test_endpoint_identity_and_uniform_shape():
    res = aggregate({"m": [admet_ai(DILI=0.5, LD50_Zhu=2.0), toxicophores(count=1)]})
    assert res.endpoint == Endpoint.toxicity and res.n_molecules == 1
    mol = res.molecules[0]
    assert mol.endpoint == Endpoint.toxicity and mol.mol_id == "m"
    assert {f.feature for f in mol.features} == {"dili", LD50_FEATURE, TOX_ALERTS_FEATURE}
    assert set(type(mol).model_fields) == {"endpoint", "mol_id", "features"}
    assert set(type(mol.features[0]).model_fields) == {"feature", "score", "uncertainty", "unit", "n_sources", "sources"}


def test_multiple_molecules_independent():
    res = aggregate({"a": [admet_ai(DILI=0.2)], "b": [admet_ai(DILI=0.8)]})
    by = {m.mol_id: _feat(m, "dili").score for m in res.molecules}
    assert by == {"a": 0.2, "b": 0.8}


def test_input_shapes_normalize_the_same():
    recs = [admet_ai(DILI=0.5)]
    as_map = aggregate({"FTO-43": recs}).molecules[0]
    as_pairs = aggregate([("FTO-43", recs)]).molecules[0]
    as_dicts = aggregate([{"mol_id": "FTO-43", "records": recs}]).molecules[0]
    for m in (as_map, as_pairs, as_dicts):
        assert m.mol_id == "FTO-43"
        assert _feat(m, "dili").score == 0.5


def test_empty_input_is_clean():
    res = aggregate({})
    assert res.n_molecules == 0 and res.molecules == []
    assert res.endpoint == Endpoint.toxicity
