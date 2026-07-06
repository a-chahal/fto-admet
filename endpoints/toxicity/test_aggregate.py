"""Tests for the toxicity aggregator (task t49): a bulk-substitute panel + a ProTox confirmatory shortlist.

Synthetic ``OutputRecord``-shaped inputs only (laptop, core env - no box, no GPU). They exercise what this
two-tier endpoint exists to guarantee (task t49, IO_SPEC §2, §3 F-5):

- the BULK block is built from the automatable heads: ADMET-AI classifier heads (DILI / hERG / AMES /
  Carcinogens_Lagunin / ClinTox / Skin_Reaction) as per-endpoint P(toxic), ADMETlab organ-tox heads
  (nephro / neuro / cyto / immuno / genotox) as P(toxic), and toxicophores as a soft alert flag;
- ADMET-AI ``LD50_Zhu`` is a MAGNITUDE read (log 1/(mol/kg), up=toxic), NOT a probability;
- the SHORTLIST block is the ProTox web read (LD50 mg/kg, class 1-6, per-endpoint Active/Inactive + prob);
- the two blocks are SEPARATE and (F-5) there is NO path/field that merges ``LD50_Zhu`` with ProTox LD50;
- multi-model same-endpoint probabilities average on the SAME [0,1] scale; missing sources degrade cleanly.
"""

from __future__ import annotations

import math

from core.models import Endpoint, ModelName
from endpoints.toxicity.aggregate import (
    BulkPanel,
    ProToxShortlist,
    aggregate,
)

PROV = {"model": "test"}


def admet_ai_rec(**heads) -> dict:
    """An ADMET-AI-shaped record: classifier/regression heads live directly in endpoint_values (TDC names)."""
    return {"model": ModelName.admet_ai, "endpoint_values": dict(heads), "provenance": PROV}


def admetlab_rec(**heads) -> dict:
    """An ADMETlab-shaped record: organ-tox heads in endpoint_values (PLACEHOLDER keys, NEEDS_AARAN literal)."""
    return {"model": ModelName.admetlab3, "endpoint_values": dict(heads), "provenance": PROV}


def toxicophores_rec(hit=True, count=2, names=None, catalog="BRENK") -> dict:
    """A toxicophores-shaped record: hit/count/catalog in endpoint_values, matched names in raw."""
    return {
        "model": ModelName.toxicophores,
        "endpoint_values": {"tox_alert_hit": hit, "tox_alert_count": count, "catalog": catalog},
        "raw": {"tox_alert_names": names or ["nitro group", "michael acceptor"]},
        "provenance": PROV,
    }


def protox_rec(ld50=350.0, tox_class=3, accuracy=68.0, endpoints=None, nested=False) -> dict:
    """A ProTox-shaped record. ``nested=True`` uses the SOP transcription shape (scalars under raw.predictions)."""
    endpoints = endpoints if endpoints is not None else {
        "Hepatotoxicity": {"call": "Active", "probability": 0.71},
        "Carcinogenicity": {"call": "Inactive", "probability": 0.62},
    }
    if nested:
        return {
            "model": ModelName.protox,
            "endpoint_values": {},
            "raw": {
                "predictions": {
                    "LD50": {"value": ld50},
                    "tox_class": {"value": tox_class},
                    "prediction_accuracy": {"value": accuracy},
                    "endpoints": endpoints,
                }
            },
            "provenance": PROV,
        }
    return {
        "model": ModelName.protox,
        "endpoint_values": {"LD50": ld50, "tox_class": tox_class, "prediction_accuracy": accuracy},
        "raw": {"endpoints": endpoints},
        "provenance": PROV,
    }


# ---------------------------------------------------------------------------------------------------
# Bulk panel: per-endpoint P(toxic).
# ---------------------------------------------------------------------------------------------------


def test_admet_ai_classifier_heads_become_per_endpoint_p_toxic():
    res = aggregate({"m1": [admet_ai_rec(DILI=0.8, hERG=0.4, AMES=0.6,
                                         Carcinogens_Lagunin=0.2, ClinTox=0.9, Skin_Reaction=0.1)]})
    assert res.endpoint is Endpoint.toxicity
    assert res.n_molecules == 1
    panel = {be.endpoint: be for be in res.molecules[0].bulk.probability_panel}
    assert panel["hepatotoxicity_dili"].p_toxic == 0.8
    assert panel["herg_blockade"].p_toxic == 0.4
    assert panel["mutagenicity_ames"].p_toxic == 0.6
    assert panel["carcinogenicity"].p_toxic == 0.2
    assert panel["clinical_toxicity"].p_toxic == 0.9
    assert panel["skin_reaction"].p_toxic == 0.1
    # every panel entry is a probability kind with its single contributing model recorded.
    for be in res.molecules[0].bulk.probability_panel:
        assert be.kind == "probability"
        assert [c.model for c in be.contributions] == [ModelName.admet_ai]


def test_admetlab_organ_tox_heads_join_the_panel():
    res = aggregate({"m1": [admetlab_rec(nephrotoxicity=0.55, neurotoxicity=0.30, cytotoxicity=0.70,
                                         immunotoxicity=0.10, genotoxicity=0.90)]})
    panel = {be.endpoint: be.p_toxic for be in res.molecules[0].bulk.probability_panel}
    assert panel == {
        "nephrotoxicity": 0.55, "neurotoxicity": 0.30, "cytotoxicity": 0.70,
        "immunotoxicity": 0.10, "genotoxicity": 0.90,
    }


def test_same_endpoint_probabilities_average_on_one_scale():
    # ADMET-AI hERG and (hypothetically) another same-endpoint source would average; here two records
    # both carry the ADMET-AI hERG head, so the endpoint groups and the mean is taken.
    res = aggregate({"m1": [admet_ai_rec(hERG=0.4), admet_ai_rec(hERG=0.6)]})
    herg = next(be for be in res.molecules[0].bulk.probability_panel if be.endpoint == "herg_blockade")
    assert herg.p_toxic == 0.5
    assert {c.p_toxic for c in herg.contributions} == {0.4, 0.6}


def test_out_of_range_or_missing_probability_is_skipped_never_fabricated():
    res = aggregate({"m1": [admet_ai_rec(DILI=1.4, hERG=None, AMES=0.5)]})
    panel = {be.endpoint for be in res.molecules[0].bulk.probability_panel}
    assert panel == {"mutagenicity_ames"}  # 1.4 (out of range) and None both dropped, not coerced


def test_toxicophores_is_a_soft_alert_not_a_probability():
    res = aggregate({"m1": [toxicophores_rec(hit=True, count=2, names=["nitro group", "epoxide"])]})
    bulk = res.molecules[0].bulk
    assert bulk.probability_panel == []  # an alert is NOT a probability
    assert len(bulk.alerts) == 1
    alert = bulk.alerts[0]
    assert alert.model is ModelName.toxicophores
    assert alert.hit is True and alert.count == 2 and alert.catalog == "BRENK"
    assert alert.names == ["nitro group", "epoxide"]
    assert alert.soft_flag is True  # over-flags; look-closer, NOT an auto-kill


def test_bulk_is_not_a_quality_equivalence_claim():
    res = aggregate({"m1": [admet_ai_rec(DILI=0.5)]})
    assert res.molecules[0].bulk.is_quality_equivalent is False


# ---------------------------------------------------------------------------------------------------
# LD50_Zhu magnitude read (F-5 landmine).
# ---------------------------------------------------------------------------------------------------


def test_ld50_zhu_is_a_magnitude_read_not_a_probability():
    res = aggregate({"m1": [admet_ai_rec(LD50_Zhu=2.3, DILI=0.5)]})
    bulk = res.molecules[0].bulk
    # LD50_Zhu never enters the probability panel...
    assert all(be.endpoint != "acute_oral_ld50_zhu" for be in bulk.probability_panel)
    assert "hepatotoxicity_dili" in {be.endpoint for be in bulk.probability_panel}
    # ...it is a magnitude read with the log(1/(mol/kg)) unit and up=more-toxic direction.
    assert len(bulk.magnitude_reads) == 1
    mr = bulk.magnitude_reads[0]
    assert mr.endpoint == "acute_oral_ld50_zhu"
    assert mr.value == 2.3
    assert mr.unit == "log(1/(mol/kg))"
    assert mr.direction == "up = more toxic"
    assert mr.model is ModelName.admet_ai


def test_ld50_zhu_marked_not_comparable_to_protox_ld50():
    res = aggregate({"m1": [admet_ai_rec(LD50_Zhu=2.3)]})
    assert res.molecules[0].bulk.magnitude_reads[0].comparable_to_protox_ld50 is False


# ---------------------------------------------------------------------------------------------------
# ProTox shortlist (separate block).
# ---------------------------------------------------------------------------------------------------


def test_protox_shortlist_flat_shape():
    res = aggregate({"m1": [protox_rec(ld50=350.0, tox_class=3, accuracy=68.0)]})
    sl = res.molecules[0].shortlist
    assert isinstance(sl, ProToxShortlist)
    assert sl.model is ModelName.protox
    assert sl.tier == "shortlist"
    assert sl.ld50_mg_kg == 350.0
    assert sl.ld50_unit == "mg/kg" and sl.ld50_direction == "lower = more toxic"
    assert sl.tox_class == 3
    assert sl.prediction_accuracy == 68.0
    calls = {e.name: (e.call, e.probability) for e in sl.endpoints}
    assert calls["Hepatotoxicity"] == ("Active", 0.71)
    assert calls["Carcinogenicity"] == ("Inactive", 0.62)


def test_protox_shortlist_nested_sop_transcription_shape():
    res = aggregate({"m1": [protox_rec(ld50=120.0, tox_class=2, accuracy=71.0, nested=True)]})
    sl = res.molecules[0].shortlist
    assert sl.ld50_mg_kg == 120.0 and sl.tox_class == 2 and sl.prediction_accuracy == 71.0
    assert {e.name for e in sl.endpoints} == {"Hepatotoxicity", "Carcinogenicity"}


def test_no_protox_record_yields_no_shortlist():
    res = aggregate({"m1": [admet_ai_rec(DILI=0.5)]})
    assert res.molecules[0].shortlist is None
    # ...but the bulk block is still produced.
    assert res.molecules[0].bulk.probability_panel[0].endpoint == "hepatotoxicity_dili"


# ---------------------------------------------------------------------------------------------------
# The core F-5 guarantee: the two LD50 reads NEVER merge.
# ---------------------------------------------------------------------------------------------------


def test_ld50_zhu_and_protox_ld50_stay_distinct_never_merged():
    # A molecule with BOTH an ADMET-AI LD50_Zhu and a ProTox LD50 in the same bundle.
    res = aggregate({"m1": [admet_ai_rec(LD50_Zhu=2.3, DILI=0.5), protox_rec(ld50=350.0, tox_class=3)]})
    mol = res.molecules[0]

    # 1. The bulk LD50_Zhu magnitude read carries the log scale + up-direction, ONLY in bulk.
    zhu = mol.bulk.magnitude_reads[0]
    assert zhu.value == 2.3 and zhu.unit == "log(1/(mol/kg))" and zhu.direction == "up = more toxic"

    # 2. The ProTox LD50 carries mg/kg + lower-direction, ONLY in the shortlist, under a DIFFERENT field.
    assert mol.shortlist.ld50_mg_kg == 350.0
    assert mol.shortlist.ld50_unit == "mg/kg" and mol.shortlist.ld50_direction == "lower = more toxic"

    # 3. The two values live in structurally separate blocks: the shortlist has no LD50_Zhu, and the bulk
    #    has no mg/kg read. There is no merged/averaged/converted scalar anywhere.
    assert not math.isclose(zhu.value, mol.shortlist.ld50_mg_kg)  # distinct numbers, never averaged
    sl_dump = mol.shortlist.model_dump()
    assert "LD50_Zhu" not in sl_dump and "acute_oral_ld50_zhu" not in str(sl_dump)
    bulk_dump = mol.bulk.model_dump()
    assert 350.0 not in _all_numbers(bulk_dump)  # the mg/kg value never leaks into the bulk block
    assert 2.3 not in _all_numbers(mol.shortlist.model_dump())  # the log value never leaks into shortlist

    # 4. LD50_Zhu is not, and cannot become, a probability-panel endpoint.
    assert all("ld50" not in be.endpoint for be in mol.bulk.probability_panel)


def _all_numbers(obj) -> set:
    """Collect every numeric leaf in a nested dict/list (helper for the no-leak assertions above)."""
    out: set = set()
    if isinstance(obj, dict):
        for v in obj.values():
            out |= _all_numbers(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out |= _all_numbers(v)
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)):
        out.add(float(obj))
    return out


# ---------------------------------------------------------------------------------------------------
# Full FTO-43-shaped bundle + input-shape normalization.
# ---------------------------------------------------------------------------------------------------


def test_full_bundle_produces_both_blocks_separately():
    bundle = [
        admet_ai_rec(LD50_Zhu=2.1, DILI=0.7, hERG=0.5, AMES=0.4,
                     Carcinogens_Lagunin=0.3, ClinTox=0.8, Skin_Reaction=0.2),
        admetlab_rec(nephrotoxicity=0.4, neurotoxicity=0.5, cytotoxicity=0.6,
                     immunotoxicity=0.2, genotoxicity=0.3),
        toxicophores_rec(hit=True, count=1, names=["michael acceptor"]),
        protox_rec(ld50=300.0, tox_class=3, accuracy=70.0),
    ]
    res = aggregate({"FTO-43": bundle})
    mol = res.molecules[0]
    assert mol.mol_id == "FTO-43"
    # bulk block: 6 ADMET-AI classifier endpoints + 5 ADMETlab organ-tox = 11 probability endpoints,
    # 1 magnitude read (LD50_Zhu), 1 alert.
    assert len(mol.bulk.probability_panel) == 11
    assert len(mol.bulk.magnitude_reads) == 1
    assert len(mol.bulk.alerts) == 1
    # shortlist block: present and separate.
    assert mol.shortlist is not None and mol.shortlist.ld50_mg_kg == 300.0
    # the placeholder NEEDS_AARAN note is surfaced when ADMETlab contributes.
    assert any("PLACEHOLDER" in n for n in mol.bulk.notes)


def test_input_shapes_normalize_identically():
    rec = admet_ai_rec(DILI=0.5)
    as_map = aggregate({"m1": [rec]})
    as_pairs = aggregate([("m1", [rec])])
    as_dicts = aggregate([{"mol_id": "m1", "records": [rec]}])
    as_bare = aggregate([[rec]])
    for res in (as_map, as_pairs, as_dicts):
        assert res.molecules[0].mol_id == "m1"
    assert as_bare.molecules[0].mol_id == "mol_0"
    for res in (as_map, as_pairs, as_dicts, as_bare):
        assert res.molecules[0].bulk.probability_panel[0].p_toxic == 0.5


def test_empty_input_is_clean():
    res = aggregate({})
    assert res.n_molecules == 0 and res.molecules == []
    assert res.endpoint is Endpoint.toxicity
