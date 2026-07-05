"""Tests for the druglikeness aggregator (task t50): three CONTEXT flags surfaced as-is, NEVER a gate.

Synthetic ``OutputRecord``-shaped inputs only (laptop, core env - no box, no GPU). They exercise what this
context-only endpoint exists to guarantee (task t50, IO_SPEC §30 / §2 "druglikeness"):

- the three flags (Lipinski_violations, Veber_pass, QED) pass through UNCHANGED from the model record;
- there is NO gate/kill logic: no threshold, no consensus, no pass/fail verdict; is_gate is always False;
- missing flags surface as absent (None), never coerced to a default that could read as a verdict;
- the accepted input shapes normalize the same way; multiple molecules stay independent.
"""

from __future__ import annotations

from core.models import Endpoint, ModelName
from endpoints.druglikeness.aggregate import (
    LIPINSKI_KEY,
    QED_KEY,
    VEBER_KEY,
    aggregate,
)

PROV = {"model": "test"}


def lvq_rec(lipinski=None, veber=None, qed=None) -> dict:
    """A lipinski_veber_qed-shaped record: the three context flags in endpoint_values."""
    ev: dict = {}
    if lipinski is not None:
        ev[LIPINSKI_KEY] = lipinski
    if veber is not None:
        ev[VEBER_KEY] = veber
    if qed is not None:
        ev[QED_KEY] = qed
    return {
        "model": ModelName.lipinski_veber_qed,
        "endpoint_values": ev,
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }


# --------------------------------------------------------------------------------------------------
# Pass-through: the three flags come out exactly as they went in.
# --------------------------------------------------------------------------------------------------
def test_three_flags_pass_through_unchanged():
    recs = [lvq_rec(lipinski=1, veber=True, qed=0.734)]
    mol = aggregate({"m": recs}).molecules[0]
    assert mol.present is True
    assert mol.Lipinski_violations == 1
    assert mol.Veber_pass is True
    assert mol.QED == 0.734


def test_flags_pass_through_with_zero_and_false_not_dropped():
    """0 violations and Veber False are meaningful values, not 'absent' - they must survive unchanged."""
    recs = [lvq_rec(lipinski=0, veber=False, qed=0.0)]
    mol = aggregate({"m": recs}).molecules[0]
    assert mol.present is True
    assert mol.Lipinski_violations == 0
    assert mol.Veber_pass is False
    assert mol.QED == 0.0


def test_four_violations_still_only_context_no_verdict():
    """Even the worst Lipinski score (4/4 violations) yields NO pass/fail field - it is context only."""
    recs = [lvq_rec(lipinski=4, veber=False, qed=0.05)]
    mol = aggregate({"m": recs}).molecules[0]
    assert mol.Lipinski_violations == 4
    assert mol.is_gate is False
    # The molecule object exposes no verdict/kill/promote field: only the three flags + context markers.
    fields = set(mol.model_dump().keys())
    assert fields == {"mol_id", "present", "Lipinski_violations", "Veber_pass", "QED", "is_gate", "notes"}
    assert not (fields & {"pass", "fail", "gate", "verdict", "kill", "promote", "reject", "consensus"})


# --------------------------------------------------------------------------------------------------
# Missing flags: surfaced as absent, never coerced to a default.
# --------------------------------------------------------------------------------------------------
def test_missing_flags_are_none_not_defaulted():
    recs = [lvq_rec(qed=0.5)]  # only QED present
    mol = aggregate({"m": recs}).molecules[0]
    assert mol.present is True
    assert mol.QED == 0.5
    assert mol.Lipinski_violations is None
    assert mol.Veber_pass is None


def test_empty_bundle_is_absent_not_a_verdict():
    mol = aggregate({"m": []}).molecules[0]
    assert mol.present is False
    assert (mol.Lipinski_violations, mol.Veber_pass, mol.QED) == (None, None, None)
    assert mol.is_gate is False


def test_explicit_none_valued_fields_treated_as_absent():
    """A record that carries the keys but with None values (the model's failed-parse shape) reads as absent."""
    rec = {
        "model": ModelName.lipinski_veber_qed,
        "endpoint_values": {LIPINSKI_KEY: None, VEBER_KEY: None, QED_KEY: None},
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }
    mol = aggregate({"m": [rec]}).molecules[0]
    assert mol.present is False
    assert (mol.Lipinski_violations, mol.Veber_pass, mol.QED) == (None, None, None)


# --------------------------------------------------------------------------------------------------
# No gate: the result carries no aggregation/threshold/verdict anywhere.
# --------------------------------------------------------------------------------------------------
def test_result_is_context_never_a_gate():
    result = aggregate({"m": [lvq_rec(lipinski=2, veber=True, qed=0.6)]})
    assert result.endpoint == Endpoint.druglikeness
    # The result object exposes no consensus/gate/verdict field: molecules + count + a context note only.
    result_fields = set(result.model_dump().keys())
    assert result_fields == {"endpoint", "quantity", "molecules", "n_molecules", "notes"}
    assert not (result_fields & {"consensus", "gate", "verdict", "pass", "fail", "kill"})
    mol = result.molecules[0]
    assert mol.is_gate is False
    assert any("context" in n.lower() and "not a gate" in n.lower() for n in mol.notes)


# --------------------------------------------------------------------------------------------------
# Input-shape normalization and multiple molecules.
# --------------------------------------------------------------------------------------------------
def test_accepted_input_shapes_normalize_the_same():
    rec = lvq_rec(lipinski=1, veber=True, qed=0.5)
    as_map = aggregate({"molA": [rec]}).molecules[0]
    as_pairs = aggregate([("molA", [rec])]).molecules[0]
    as_dicts = aggregate([{"mol_id": "molA", "records": [rec]}]).molecules[0]
    as_bare = aggregate([[rec]]).molecules[0]
    for m in (as_map, as_pairs, as_dicts):
        assert m.mol_id == "molA"
    assert as_bare.mol_id == "mol_0"
    for m in (as_map, as_pairs, as_dicts, as_bare):
        assert m.Lipinski_violations == 1 and m.Veber_pass is True and m.QED == 0.5


def test_multiple_molecules_are_independent():
    good = lvq_rec(lipinski=0, veber=True, qed=0.9)
    poor = lvq_rec(lipinski=3, veber=False, qed=0.1)
    result = aggregate({"good": [good], "poor": [poor]})
    assert result.n_molecules == 2
    by_id = {m.mol_id: m for m in result.molecules}
    assert (by_id["good"].Lipinski_violations, by_id["good"].QED) == (0, 0.9)
    assert (by_id["poor"].Lipinski_violations, by_id["poor"].QED) == (3, 0.1)


def test_first_non_none_value_wins_flags_never_combined():
    """If two records carry a flag, the first non-None value is surfaced as-is; flags are never averaged."""
    rec_a = lvq_rec(qed=0.4)                       # QED only
    rec_b = lvq_rec(lipinski=2, veber=True, qed=0.8)  # a second record also carrying QED
    mol = aggregate({"m": [rec_a, rec_b]}).molecules[0]
    assert mol.QED == 0.4                          # first non-None wins; NOT the mean of 0.4 and 0.8
    assert mol.Lipinski_violations == 2 and mol.Veber_pass is True
