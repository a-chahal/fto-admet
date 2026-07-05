"""Tests for the DECOMPOSED clearance aggregator (task t43).

Synthetic ``OutputRecord``-shaped inputs only (laptop, core env - no box, no GPU). They exercise the one
thing this aggregator exists to guarantee (F-3, CLAUDE.md §4): the four clearance sources land in three
SEPARATE labeled reads, each with its own unit string, and are NEVER combined numerically.

- renal / hepatic / aggregate come back as distinct reads with distinct unit strings;
- the hepatic CLint candidates stay separate (even the two sharing "uL/min/10^6 cells"), never averaged;
- ADMET-AI clearance candidates carry the F-17 low-weight flag;
- PKSmart CL is ranking-only and always surfaced WITH its fold-error (never the bare number);
- PKSmart CL gets a relative within-series rank (1 = fastest clearance), the only cross-molecule math;
- there is no combined/summed/averaged clearance scalar anywhere in the result;
- the accepted input shapes normalize the same way; missing sources degrade gracefully.
"""

from __future__ import annotations

from core.models import Endpoint, ModelName
from endpoints.clearance.aggregate import (
    ADMET_AI_HEPATOCYTE_UNIT,
    ADMET_AI_MICROSOME_UNIT,
    ANCHOR_CL_ML_MIN_KG,
    OPERA_CLINT_UNIT,
    PKSMART_CL_UNIT,
    WATANABE_CLR_UNIT,
    aggregate,
)

PROV = {"model": "test"}


def watanabe_rec(fe=None, clr=None, fu_p=None) -> dict:
    return {
        "model": ModelName.watanabe_renal,
        "endpoint_values": {"fe": fe, "CLr": clr, "fu_p": fu_p},
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }


def admet_ai_rec(hepatocyte=None, microsome=None) -> dict:
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


def opera_clint_rec(clint=None) -> dict:
    # OPERA emits one record per endpoint; the clearance-relevant one keys `Clint` (suffix stripped).
    return {
        "model": ModelName.opera,
        "endpoint_values": {"Clint": clint},
        "uncertainty": {"conf_index": 0.7, "extra": {}},
        "raw": {"endpoint": "Clint", "units": OPERA_CLINT_UNIT},
        "provenance": PROV,
    }


def pksmart_rec(cl=None, fold_error=None, low=None, high=None, with_uncertainty=True) -> dict:
    unc = None
    if with_uncertainty:
        unc = {
            "fold_error_low": low,
            "fold_error_high": high,
            "extra": {"cl_fold_error": fold_error},
        }
    return {
        "model": ModelName.pksmart,
        "endpoint_values": {"CL_mL_min_kg": cl, "VDss_L_kg": 3.0},
        "uncertainty": unc,
        "raw": {},
        "provenance": PROV,
    }


def full_mol(mol_id: str, cl: float) -> tuple[str, list[dict]]:
    """A molecule with all four sources present (CL varies so the set can be ranked)."""
    return mol_id, [
        watanabe_rec(fe="high", clr=5.0, fu_p=0.1),
        admet_ai_rec(hepatocyte=12.0, microsome=30.0),
        opera_clint_rec(clint=8.0),
        pksmart_rec(cl=cl, fold_error=2.4, low=cl / 2.4, high=cl * 2.4),
    ]


# --------------------------------------------------------------------------------------------------
# Core contract: four sources -> three separate labeled reads with distinct units.
# --------------------------------------------------------------------------------------------------
def test_three_labeled_reads_with_distinct_units():
    res = aggregate([full_mol("FTO-43", cl=89.6)])
    assert res.endpoint == Endpoint.clearance
    assert res.n_molecules == 1

    m = res.molecules[0]
    # RENAL
    assert m.renal.present is True
    assert m.renal.clr == 5.0
    assert m.renal.clr_unit == WATANABE_CLR_UNIT == "mL/min/kg"
    assert m.renal.fe == "high" and m.renal.fu_p == 0.1
    # HEPATIC - three candidates, kept separate, each with its own unit/matrix
    assert m.hepatic.present is True
    units = {(c.model, c.matrix): c.unit for c in m.hepatic.clint_candidates}
    assert units[(ModelName.admet_ai, "hepatocyte")] == ADMET_AI_HEPATOCYTE_UNIT == "uL/min/10^6 cells"
    assert units[(ModelName.admet_ai, "microsome")] == ADMET_AI_MICROSOME_UNIT == "uL/min/mg"
    assert units[(ModelName.opera, "intrinsic")] == OPERA_CLINT_UNIT == "uL/min/10^6 cells"
    # AGGREGATE
    assert m.aggregate.present is True
    assert m.aggregate.cl == 89.6 and m.aggregate.cl_unit == PKSMART_CL_UNIT == "mL/min/kg"
    assert m.aggregate.anchor_cl == ANCHOR_CL_ML_MIN_KG

    # The three reads carry DISTINCT unit strings for the whole-molecule/whole-body numbers.
    assert m.renal.clr_unit == "mL/min/kg"          # renal plasma clearance
    assert m.aggregate.cl_unit == "mL/min/kg"       # whole-body i.v. clearance (same string, different matrix)
    hep_units = {c.unit for c in m.hepatic.clint_candidates}
    assert hep_units == {"uL/min/10^6 cells", "uL/min/mg"}  # hepatic CLint units differ from the CL units


# --------------------------------------------------------------------------------------------------
# The landmine: NEVER combine across units. No averaged/summed clearance scalar exists anywhere.
# --------------------------------------------------------------------------------------------------
def test_no_combined_clearance_scalar_anywhere():
    res = aggregate([full_mol("A", cl=50.0)])
    m = res.molecules[0]

    # Reads stay decomposed: there is no field that fuses the four numbers.
    dumped = m.model_dump()
    assert set(dumped.keys()) == {"mol_id", "renal", "hepatic", "aggregate", "notes"}

    # Sanity: the hepatic candidates are individually preserved, never reduced to one number.
    vals = sorted(c.value for c in m.hepatic.clint_candidates)
    assert vals == [8.0, 12.0, 30.0]  # opera Clint, admet_ai hepatocyte, admet_ai microsome - all three kept

    # If anyone HAD averaged the hepatic candidates it would be (8+12+30)/3 = 16.67; assert no such value
    # surfaces as a hepatic scalar (there is no aggregated hepatic field at all).
    hep_dump = m.hepatic.model_dump()
    assert "clint_mean" not in hep_dump and "clint" not in hep_dump
    # And the two hepatic candidates that share a unit string are still two separate entries.
    same_unit = [c for c in m.hepatic.clint_candidates if c.unit == "uL/min/10^6 cells"]
    assert {c.model for c in same_unit} == {ModelName.admet_ai, ModelName.opera}


def test_admet_ai_clearance_candidates_are_low_weight():
    res = aggregate([full_mol("A", cl=50.0)])
    cands = {c.model: c for c in res.molecules[0].hepatic.clint_candidates}
    # F-17: ADMET-AI clearance heads are weak -> qualitative only.
    for c in res.molecules[0].hepatic.clint_candidates:
        if c.model == ModelName.admet_ai:
            assert c.low_weight is True
        if c.model == ModelName.opera:
            assert c.low_weight is False
    assert ModelName.admet_ai in cands and ModelName.opera in cands


# --------------------------------------------------------------------------------------------------
# PKSmart: ranking-only, fold-error always surfaced with the CL, never the bare number.
# --------------------------------------------------------------------------------------------------
def test_pksmart_cl_carries_fold_error():
    res = aggregate([full_mol("A", cl=89.6)])
    agg = res.molecules[0].aggregate
    assert agg.ranking_only is True
    assert agg.fold_error == 2.4
    assert agg.fold_error_low is not None and agg.fold_error_high is not None
    assert agg.fold_error_available is True
    assert any("RANKING-ONLY" in n for n in agg.notes)


def test_pksmart_cl_without_fold_error_is_flagged():
    molecules = [("A", [pksmart_rec(cl=40.0, with_uncertainty=False)])]
    res = aggregate(molecules)
    agg = res.molecules[0].aggregate
    assert agg.cl == 40.0
    assert agg.fold_error_available is False
    assert any("must NOT be surfaced on its own" in n for n in agg.notes)


def test_pksmart_cl_relative_rank_across_set():
    # 1 = fastest clearance = highest CL = worst liability.
    molecules = [full_mol("slow", cl=20.0), full_mol("fast", cl=120.0), full_mol("mid", cl=60.0)]
    res = aggregate(molecules)
    by_id = {m.mol_id: m for m in res.molecules}
    assert by_id["fast"].aggregate.cl_rank == 1
    assert by_id["mid"].aggregate.cl_rank == 2
    assert by_id["slow"].aggregate.cl_rank == 3
    assert res.n_cl_ranked == 3


# --------------------------------------------------------------------------------------------------
# SoM presence is a qualitative hepatic input, never a number.
# --------------------------------------------------------------------------------------------------
def test_som_presence_flagged_not_numericized():
    smartcyp_rec = {
        "model": ModelName.smartcyp,
        "endpoint_values": {},  # SoM is a per-atom table in raw, not a scalar
        "uncertainty": None,
        "raw": {"per_atom": [{"atom": "C.7", "Ranking": 1}]},
        "provenance": PROV,
    }
    molecules = [("A", [admet_ai_rec(hepatocyte=10.0), smartcyp_rec])]
    res = aggregate(molecules)
    hep = res.molecules[0].hepatic
    assert hep.som_available is True
    assert ModelName.smartcyp in hep.som_models
    # SoM did not add a numeric CLint candidate.
    assert all(c.model != ModelName.smartcyp for c in hep.clint_candidates)


# --------------------------------------------------------------------------------------------------
# Graceful degradation when sources are missing.
# --------------------------------------------------------------------------------------------------
def test_missing_sources_degrade_gracefully():
    # Only PKSmart present.
    molecules = [("A", [pksmart_rec(cl=30.0, fold_error=2.0, low=15.0, high=60.0)])]
    res = aggregate(molecules)
    m = res.molecules[0]
    assert m.renal.present is False
    assert m.hepatic.present is False and m.hepatic.clint_candidates == []
    assert m.aggregate.present is True and m.aggregate.cl == 30.0
    assert any("no watanabe_renal" in n for n in m.renal.notes)
    assert any("no hepatic CLint candidate" in n for n in m.hepatic.notes)


def test_empty_input_yields_empty_result():
    res = aggregate([])
    assert res.molecules == []
    assert res.n_molecules == 0 and res.n_cl_ranked == 0


def test_no_cl_in_set_means_no_ranking():
    molecules = [("A", [admet_ai_rec(hepatocyte=10.0)]), ("B", [opera_clint_rec(clint=5.0)])]
    res = aggregate(molecules)
    assert res.n_cl_ranked == 0
    assert all(m.aggregate.cl_rank is None for m in res.molecules)
    assert any("no PKSmart CL in the set" in n for n in res.notes)


# --------------------------------------------------------------------------------------------------
# Input-shape normalization.
# --------------------------------------------------------------------------------------------------
def test_mapping_and_pair_inputs_agree():
    as_pairs = [full_mol("A", cl=20.0), full_mol("C", cl=90.0)]
    as_mapping = {mid: recs for mid, recs in as_pairs}
    r_pairs = aggregate(as_pairs)
    r_map = aggregate(as_mapping)
    assert [m.mol_id for m in r_pairs.molecules] == [m.mol_id for m in r_map.molecules]
    assert r_pairs.n_cl_ranked == r_map.n_cl_ranked


def test_bare_record_lists_get_positional_ids():
    bundle_a = [pksmart_rec(cl=20.0, fold_error=2.0)]
    bundle_b = [pksmart_rec(cl=90.0, fold_error=2.0)]
    res = aggregate([bundle_a, bundle_b])
    assert {m.mol_id for m in res.molecules} == {"mol_0", "mol_1"}


def test_dict_with_records_key_uses_declared_id():
    res = aggregate(
        [
            {"mol_id": "FTO-43", "records": full_mol("x", cl=89.6)[1]},
            {"id": "control", "records": full_mol("y", cl=20.0)[1]},
        ]
    )
    ids = {m.mol_id for m in res.molecules}
    assert "FTO-43" in ids and "control" in ids


def test_deferred_boundaries_are_flagged():
    res = aggregate([full_mol("A", cl=50.0)])
    joined = " ".join(res.deferred)
    assert "calibrat" in joined.lower()
    assert "F-14" in joined
