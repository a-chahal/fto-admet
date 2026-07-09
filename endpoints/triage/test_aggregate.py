"""Tests for the triage aggregator: the funnel-entry generalist read-out. CONTEXT ONLY.

Synthetic ``OutputRecord``-shaped inputs (laptop, core env - no box, no GPU). Triage surfaces the
cross-cutting generalist (ADMET-AI) heads VERBATIM per molecule - no consensus, no uncertainty, no gate.
The only guard is F-17: the ``VDss_Lombardo`` / ``Half_Life_Obach`` heads never appear.
"""

from __future__ import annotations

from core.models import Endpoint, ModelName
from endpoints.triage.aggregate import EXCLUDED_R2_NEGATIVE, aggregate

PROV = {"model": "test"}


def admet_ai_rec(**heads) -> dict:
    """An ADMET-AI record whose endpoint_values are the given canonical heads."""
    return {
        "model": ModelName.admet_ai,
        "endpoint_values": dict(heads),
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }


def bayesherg_rec(**ev) -> dict:
    """A non-generalist record (triage must ignore it)."""
    return {
        "model": ModelName.bayesherg,
        "endpoint_values": dict(ev),
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }


def test_endpoint_identity_and_values_surfaced_verbatim():
    res = aggregate({"m": [admet_ai_rec(hERG=0.2, BBB_Martins=0.9, PPBR_AZ=66.0)]})
    assert res.endpoint == Endpoint.triage
    assert res.n_molecules == 1
    mol = res.molecules[0]
    assert mol.present is True
    # every head passes through unchanged - no scoring, no consensus, no flag
    assert mol.values == {"hERG": 0.2, "BBB_Martins": 0.9, "PPBR_AZ": 66.0}


def test_f17_heads_never_surface():
    """VDss_Lombardo / Half_Life_Obach are dropped even if a stray record carries them (F-17)."""
    mol = aggregate({"m": [admet_ai_rec(hERG=0.3, VDss_Lombardo=2.0, Half_Life_Obach=5.0)]}).molecules[0]
    assert set(mol.values) == {"hERG"}
    assert not (set(mol.values) & EXCLUDED_R2_NEGATIVE)


def test_no_generalist_record_is_absent():
    mol = aggregate({"m": [bayesherg_rec(P_block=0.5)]}).molecules[0]
    assert mol.present is False
    assert mol.values == {}


def test_non_generalist_records_are_ignored():
    """triage is generalist-only: a co-bundled bayesherg record contributes nothing."""
    mol = aggregate({"m": [admet_ai_rec(hERG=0.7), bayesherg_rec(P_block=0.9)]}).molecules[0]
    assert mol.present is True
    assert mol.values == {"hERG": 0.7}  # bayesherg's P_block is not surfaced


def test_non_numeric_and_bool_heads_pass_through_verbatim():
    mol = aggregate({"m": [admet_ai_rec(hERG=0.5, some_flag=True, some_label="x")]}).molecules[0]
    assert mol.values == {"hERG": 0.5, "some_flag": True, "some_label": "x"}


def test_multiple_molecules_independent():
    res = aggregate({"a": [admet_ai_rec(hERG=0.1)], "b": [admet_ai_rec(hERG=0.9)]})
    assert res.n_molecules == 2
    by = {m.mol_id: m for m in res.molecules}
    assert by["a"].values["hERG"] == 0.1
    assert by["b"].values["hERG"] == 0.9


def test_input_shapes_normalize_the_same():
    recs = [admet_ai_rec(hERG=0.4)]
    as_map = aggregate({"FTO-43": recs}).molecules[0]
    as_pairs = aggregate([("FTO-43", recs)]).molecules[0]
    as_dicts = aggregate([{"mol_id": "FTO-43", "records": recs}]).molecules[0]
    for m in (as_map, as_pairs, as_dicts):
        assert m.mol_id == "FTO-43"
        assert m.values == {"hERG": 0.4}


def test_result_is_context_no_gate_field():
    res = aggregate({"m": [admet_ai_rec(hERG=0.99)]})
    # the result + molecule schemas expose no consensus/gate/verdict field: context only
    result_fields = set(type(res).model_fields)
    assert result_fields == {"endpoint", "quantity", "molecules", "n_molecules"}
    mol_fields = set(type(res.molecules[0]).model_fields)
    assert mol_fields == {"mol_id", "present", "values"}
    assert not ((result_fields | mol_fields) & {"consensus", "gate", "verdict", "divergent", "confidence", "spread"})
