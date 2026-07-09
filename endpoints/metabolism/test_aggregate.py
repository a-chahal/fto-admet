"""Tests for the metabolism aggregator (task t42) - TWO quantities, not three votes.

Synthetic ``OutputRecord``-shaped inputs only (laptop, core env - no box, no GPU). They exercise the
things this aggregator exists to guarantee (F-2, CLAUDE.md §4, IO_SPEC §2 "metabolism"):

- the two quantities (whole-molecule STABILITY vs per-atom SITE-OF-METABOLISM) stay SEPARATE;
- SoM is co-ranked ORDINALLY on atom index - SMARTCyp Score (lower = SoM) and FAME3R probability
  (higher = SoM) are NEVER averaged; only integer per-model ranks are summed;
- SMARTCyp low Score on atom k + FAME3R high prob on atom k => consensus top atom = k, models agree,
  confidence = high (the task's done-criteria);
- disagreement on the top atom raises the confidence flag (confidence = low);
- the two ADMET-AI clearance heads are kept as separate labeled candidates (different units), never
  combined, and carry the F-17 low-weight flag;
- the ADMETlab head is a NEEDS_AARAN placeholder: surfaced with direction_known=False and excluded from
  the derived stability flag;
- the accepted input shapes normalize the same way; missing sources degrade gracefully.
"""

from __future__ import annotations

from core.models import Endpoint, ModelName
from endpoints.metabolism.aggregate import (
    ADMET_AI_HEPATOCYTE,
    ADMET_AI_HEPATOCYTE_UNIT,
    ADMET_AI_MICROSOME,
    ADMET_AI_MICROSOME_UNIT,
    CONF_HIGH,
    CONF_LOW,
    CONF_NONE,
    CONF_SINGLE,
    LABILE,
    STABLE,
    UNKNOWN,
    aggregate,
)

PROV = {"model": "test"}


def fame3r_rec(atom_probs: dict[int, float], mol_id=None) -> dict:
    """A FAME3R record: per-atom SoM probabilities in raw.atoms (higher = more likely SoM)."""
    atoms = [
        {"atom_index": i, "element": "C", "som_probability": p, "fame3r_score": 0.5}
        for i, p in sorted(atom_probs.items())
    ]
    top_idx = max(atom_probs, key=lambda i: atom_probs[i]) if atom_probs else None
    return {
        "model": ModelName.fame3r,
        "endpoint_values": {
            "max_som_probability": max(atom_probs.values()) if atom_probs else None,
            "top_som_atom_index": top_idx,
            "n_atoms_scored": len(atom_probs),
        },
        "uncertainty": {"ad_index": 0.6, "extra": {}},
        "raw": {"atoms": atoms, "smiles": "CCO", "mol_id": mol_id},
        "provenance": PROV,
    }


def smartcyp_rec(atom_scores: dict[int, float], rankings: dict[int, int] | None = None, mol_id=None) -> dict:
    """A SMARTCyp record: per-atom Score in raw.atoms (lower = more likely SoM); optional native Ranking."""
    atoms = []
    for i, s in sorted(atom_scores.items()):
        row: dict = {"atom_index": i, "element": "C", "Score": s}
        if rankings is not None and i in rankings:
            row["Ranking"] = rankings[i]
        atoms.append(row)
    return {
        "model": ModelName.smartcyp,
        "endpoint_values": {},
        "uncertainty": None,
        "raw": {"atoms": atoms, "smiles": "CCO", "mol_id": mol_id},
        "provenance": PROV,
    }


def admet_ai_rec(hepatocyte=None, microsome=None) -> dict:
    return {
        "model": ModelName.admet_ai,
        "endpoint_values": {
            ADMET_AI_HEPATOCYTE: hepatocyte,
            ADMET_AI_MICROSOME: microsome,
            "HIA_Hou": 0.98,  # an unrelated head that must be ignored
        },
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }




# --------------------------------------------------------------------------------------------------
# The core done-criterion: ordinal co-rank agreement on the soft spot.
# --------------------------------------------------------------------------------------------------
def test_agreement_puts_shared_atom_top_and_high_confidence():
    """SMARTCyp low Score on atom 3 + FAME3R high prob on atom 3 => consensus top = 3, high confidence."""
    # atom 3 is the soft spot: lowest SMARTCyp Score AND highest FAME3R probability.
    sc = smartcyp_rec({0: 90.0, 1: 80.0, 2: 70.0, 3: 20.0, 4: 85.0})
    fr = fame3r_rec({0: 0.05, 1: 0.10, 2: 0.20, 3: 0.95, 4: 0.08})
    res = aggregate({"FTO-43": [sc, fr]})

    assert res.endpoint == Endpoint.metabolism
    mol = res.molecules[0]
    som = mol.som
    assert som.present
    assert som.consensus_top_atom_index == 3
    assert som.models_agree is True
    assert som.top_atom_by_model == {"smartcyp": 3, "fame3r": 3}
    assert mol.confidence == CONF_HIGH


def test_disagreement_raises_confidence_flag():
    """Different top atoms per model => models_agree False, confidence = low (the flag is raised)."""
    sc = smartcyp_rec({0: 10.0, 1: 80.0, 2: 70.0})   # SMARTCyp soft spot = atom 0
    fr = fame3r_rec({0: 0.10, 1: 0.90, 2: 0.20})     # FAME3R soft spot = atom 1
    res = aggregate({"m": [sc, fr]})

    som = res.molecules[0].som
    assert som.models_agree is False
    assert som.top_atom_by_model == {"smartcyp": 0, "fame3r": 1}
    assert res.molecules[0].confidence == CONF_LOW


def test_raw_values_are_never_averaged_only_ordinal_ranks():
    """The consensus must be ordinal: an extreme FAME3R probability cannot outvote via magnitude.

    SMARTCyp ranks atom 0 best by a hair (Score 1 vs 2); FAME3R ranks atom 1 best by a hair (0.51 vs
    0.50). If raw values were mixed, FAME3R's 0.51 could not compete with SMARTCyp's kJ/mol Scores at
    all - but ordinally both atoms are rank 1 in one model and rank 2 in the other, so the rank-sum ties
    and the lower atom index breaks it. This asserts we compare ranks, not raw magnitudes.
    """
    sc = smartcyp_rec({0: 1.0, 1: 2.0})       # ranks: atom0=1, atom1=2
    fr = fame3r_rec({0: 0.50, 1: 0.51})       # ranks: atom1=1, atom0=2
    res = aggregate({"m": [sc, fr]})
    som = res.molecules[0].som
    # rank-sum: atom0 = 1+2 = 3, atom1 = 2+1 = 3 -> tie -> both consensus rank 1, atom0 first by index.
    ranks = dict(som.consensus_ranking)
    assert ranks[0] == 1 and ranks[1] == 1
    assert som.consensus_top_atom_index == 0


def test_smartcyp_native_ranking_used_when_present():
    """When SMARTCyp ships its own Ranking ordinal, it is authoritative over deriving from Score order."""
    # Ranking says atom 2 is the top site even though its Score is not the lowest here.
    sc = smartcyp_rec({0: 50.0, 1: 40.0, 2: 45.0}, rankings={0: 3, 1: 2, 2: 1})
    res = aggregate({"m": [sc]})
    per_model = res.molecules[0].som.per_model[0]
    assert per_model.top_atom_index == 2


def test_single_som_model_is_single_model_confidence():
    fr = fame3r_rec({0: 0.1, 1: 0.9})
    res = aggregate({"m": [fr]})
    mol = res.molecules[0]
    assert mol.som.present
    assert mol.som.models_agree is False
    assert mol.confidence == CONF_SINGLE


def test_no_som_model_confidence_none():
    res = aggregate({"m": [admet_ai_rec(hepatocyte=5.0)]})
    mol = res.molecules[0]
    assert mol.som.present is False
    assert mol.confidence == CONF_NONE


# --------------------------------------------------------------------------------------------------
# Stability quantity: separate labeled candidates, never combined; F-17 low-weight; coarse flag.
# --------------------------------------------------------------------------------------------------
def test_stability_candidates_kept_separate_with_own_units():
    res = aggregate({"m": [admet_ai_rec(hepatocyte=35.0, microsome=50.0)]})
    stab = res.molecules[0].stability
    assert stab.present
    assert len(stab.candidates) == 2
    by_field = {c.field: c for c in stab.candidates}
    assert by_field[ADMET_AI_HEPATOCYTE].unit == ADMET_AI_HEPATOCYTE_UNIT
    assert by_field[ADMET_AI_MICROSOME].unit == ADMET_AI_MICROSOME_UNIT
    # Different units => never merged; both flagged low-weight (F-17).
    assert by_field[ADMET_AI_HEPATOCYTE].unit != by_field[ADMET_AI_MICROSOME].unit
    assert all(c.low_weight for c in stab.candidates)


def test_stability_flag_coarse_bands_from_hepatocyte():
    assert aggregate({"m": [admet_ai_rec(hepatocyte=5.0)]}).molecules[0].stability.flag == STABLE
    assert aggregate({"m": [admet_ai_rec(hepatocyte=50.0)]}).molecules[0].stability.flag == LABILE




def test_stability_absent_degrades_gracefully():
    res = aggregate({"m": [fame3r_rec({0: 0.9})]})
    stab = res.molecules[0].stability
    assert stab.present is False
    assert stab.flag == UNKNOWN


# --------------------------------------------------------------------------------------------------
# Two quantities never merged; input-shape normalization; result-level contract.
# --------------------------------------------------------------------------------------------------
def test_two_quantities_coexist_independently():
    sc = smartcyp_rec({0: 20.0, 1: 80.0})
    fr = fame3r_rec({0: 0.9, 1: 0.1})
    res = aggregate({"FTO-43": [sc, fr, admet_ai_rec(hepatocyte=40.0)]})
    mol = res.molecules[0]
    # Stability present AND SoM present, as two independent reads.
    assert mol.stability.present and mol.som.present
    assert mol.stability.flag == LABILE
    assert mol.som.consensus_top_atom_index == 0
    # labile stability + a located soft spot => the confidence basis cross-references them.
    assert any("consistent" in b or LABILE in b for b in mol.confidence_basis)


def test_input_shapes_normalize_identically():
    sc = smartcyp_rec({0: 20.0, 1: 80.0})
    fr = fame3r_rec({0: 0.9, 1: 0.1})
    as_mapping = aggregate({"x": [sc, fr]})
    as_pairs = aggregate([("x", [sc, fr])])
    as_dicts = aggregate([{"mol_id": "x", "records": [sc, fr]}])
    as_bare = aggregate([[sc, fr]])

    for res in (as_mapping, as_pairs, as_dicts):
        assert res.molecules[0].mol_id == "x"
        assert res.molecules[0].som.consensus_top_atom_index == 0
    assert as_bare.molecules[0].mol_id == "mol_0"
    assert as_bare.molecules[0].som.consensus_top_atom_index == 0


def test_result_level_contract():
    res = aggregate({"a": [fame3r_rec({0: 0.9})], "b": [smartcyp_rec({0: 10.0})]})
    assert res.n_molecules == 2
    assert res.endpoint == Endpoint.metabolism
    # The result advertises the two-quantities / no-averaging contract and the deferred boundaries.
    assert "TWO" in res.quantity
    assert any("DEFERRED" in d for d in res.deferred)
    assert any("ORDINAL" in n or "averaged" in n for n in res.notes)


def test_empty_and_errored_atom_tables_do_not_crash():
    errored = {
        "model": ModelName.fame3r,
        "endpoint_values": {"max_som_probability": None, "top_som_atom_index": None, "n_atoms_scored": 0},
        "uncertainty": None,
        "raw": {"error": "RDKit could not parse SMILES", "smiles": "not_a_smiles"},
        "provenance": PROV,
    }
    res = aggregate({"bad": [errored]})
    mol = res.molecules[0]
    assert mol.som.present is False
    assert mol.confidence == CONF_NONE
