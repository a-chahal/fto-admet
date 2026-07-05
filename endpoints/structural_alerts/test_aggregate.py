"""Tests for the structural_alerts aggregator (task t47): the UNION of PAINS / BRENK matches as a SOFT flag.

Synthetic ``OutputRecord``-shaped inputs only (laptop, core env - no box, no GPU). They exercise what this
aggregate-only endpoint exists to guarantee (task t47, IO_SPEC §1 #24):

- the matched list is the UNION over the named-alert screens, deduplicated by (catalog, name), with the
  reporting models and matched atoms merged;
- PAINS_count / BRENK_count are the distinct named alerts per catalog, and any_hit is a single boolean;
- count-only shortcuts (ADMET-AI PAINS_alert / BRENK_alert / NIH_alert) are surfaced APART (cross_check),
  cannot join the named union (no names), yet still count toward any_hit;
- the result is a SOFT flag, NEVER a pass/fail gate (soft_flag True, is_gate False);
- the accepted input shapes normalize the same way; a clean molecule and missing sources degrade gracefully.
"""

from __future__ import annotations

from core.models import Endpoint, ModelName
from endpoints.structural_alerts.aggregate import (
    BRENK,
    PAINS,
    aggregate,
)

PROV = {"model": "test"}


def pains_brenk_rec(pains=None, brenk=None, pains_matches=None, brenk_matches=None) -> dict:
    """A pains_brenk-shaped record: counts in endpoint_values, named matches ({name, atoms}) in raw."""
    return {
        "model": ModelName.pains_brenk,
        "endpoint_values": {
            "PAINS_hit": None if pains is None else pains > 0,
            "PAINS_count": pains,
            "BRENK_hit": None if brenk is None else brenk > 0,
            "BRENK_count": brenk,
        },
        "uncertainty": None,
        "raw": {
            "PAINS_matches": pains_matches or [],
            "BRENK_matches": brenk_matches or [],
            "soft_filter": True,
        },
        "provenance": PROV,
    }


def admet_ai_rec(pains_alert=None, brenk_alert=None, nih_alert=None) -> dict:
    """An ADMET-AI-shaped record: COUNT shortcuts in endpoint_values, no matched-alert names."""
    ev: dict = {}
    if pains_alert is not None:
        ev["PAINS_alert"] = pains_alert
    if brenk_alert is not None:
        ev["BRENK_alert"] = brenk_alert
    if nih_alert is not None:
        ev["NIH_alert"] = nih_alert
    return {
        "model": ModelName.admet_ai,
        "endpoint_values": ev,
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }


# --------------------------------------------------------------------------------------------------
# Named union: counts + matched list + any_hit.
# --------------------------------------------------------------------------------------------------
def test_named_matches_produce_counts_and_matched_list():
    recs = [
        pains_brenk_rec(
            pains=2,
            brenk=1,
            pains_matches=[
                {"name": "quinone_A", "atoms": [1, 2, 3]},
                {"name": "catechol_A", "atoms": [4, 5]},
            ],
            brenk_matches=[{"name": "michael_acceptor", "atoms": [0]}],
        )
    ]
    mol = aggregate({"m": recs}).molecules[0]
    assert mol.PAINS_count == 2
    assert mol.BRENK_count == 1
    assert mol.counts == {PAINS: 2, BRENK: 1}
    assert mol.any_hit is True
    names = {(a.catalog, a.name) for a in mol.matched}
    assert names == {(PAINS, "quinone_A"), (PAINS, "catechol_A"), (BRENK, "michael_acceptor")}


def test_clean_molecule_no_hits():
    """No named matches and no shortcut counts -> zero counts, empty union, any_hit False."""
    recs = [pains_brenk_rec(pains=0, brenk=0)]
    mol = aggregate({"m": recs}).molecules[0]
    assert (mol.PAINS_count, mol.BRENK_count) == (0, 0)
    assert mol.matched == []
    assert mol.any_hit is False


def test_union_dedupes_by_catalog_and_name_merging_models_and_atoms():
    """The SAME (catalog, name) alert from two models collapses to one entry; models and atoms merge."""
    rec_a = pains_brenk_rec(pains=1, pains_matches=[{"name": "quinone_A", "atoms": [1, 2]}])
    # A second source (reuse the pains_brenk shape but a different model) reports the same alert, more atoms.
    rec_b = {
        "model": ModelName.toxicophores,
        "endpoint_values": {},
        "uncertainty": None,
        "raw": {"PAINS_matches": [{"name": "quinone_A", "atoms": [2, 3]}]},
        "provenance": PROV,
    }
    mol = aggregate({"m": [rec_a, rec_b]}).molecules[0]
    assert mol.PAINS_count == 1  # ONE distinct alert, not two
    (alert,) = mol.matched
    assert alert.name == "quinone_A"
    assert alert.atoms == [1, 2, 3]  # union of the two atom sets, sorted
    assert set(alert.models) == {ModelName.pains_brenk, ModelName.toxicophores}


# --------------------------------------------------------------------------------------------------
# Count-only shortcuts: surfaced apart, count toward any_hit, never join the named union.
# --------------------------------------------------------------------------------------------------
def test_count_shortcuts_surface_apart_and_do_not_join_named_union():
    recs = [admet_ai_rec(pains_alert=2, brenk_alert=0, nih_alert=1)]
    mol = aggregate({"m": recs}).molecules[0]
    # No named matches -> named counts are zero and the matched union is empty ...
    assert (mol.PAINS_count, mol.BRENK_count) == (0, 0)
    assert mol.matched == []
    # ... but the shortcuts are surfaced in cross_check, including NIH which no named source provides.
    by_cat = {sig.catalog: sig.count for sig in mol.cross_check}
    assert by_cat == {"PAINS": 2, "BRENK": 0, "NIH": 1}
    # A shortcut count > 0 is still a real alert -> any_hit is True even with no named match.
    assert mol.any_hit is True


def test_shortcut_all_zero_is_not_a_hit():
    mol = aggregate({"m": [admet_ai_rec(pains_alert=0, brenk_alert=0, nih_alert=0)]}).molecules[0]
    assert mol.any_hit is False


def test_named_and_shortcut_discrepancy_both_visible():
    """pains_brenk finds 0 named PAINS, ADMET-AI shortcut says 2: both surfaced, discrepancy visible."""
    recs = [pains_brenk_rec(pains=0, brenk=0), admet_ai_rec(pains_alert=2)]
    mol = aggregate({"m": recs}).molecules[0]
    assert mol.PAINS_count == 0            # named union: nothing named
    assert mol.any_hit is True             # but the shortcut count makes it a look-closer
    assert any(s.catalog == "PAINS" and s.count == 2 for s in mol.cross_check)


# --------------------------------------------------------------------------------------------------
# Soft-flag guarantee and result shape.
# --------------------------------------------------------------------------------------------------
def test_result_is_a_soft_flag_never_a_gate():
    recs = [pains_brenk_rec(pains=3, brenk=0, pains_matches=[
        {"name": "a", "atoms": [0]}, {"name": "b", "atoms": [1]}, {"name": "c", "atoms": [2]},
    ])]
    result = aggregate({"m": recs})
    assert result.endpoint == Endpoint.structural_alerts
    mol = result.molecules[0]
    assert mol.soft_flag is True
    assert mol.is_gate is False
    # No field on the result reads as a pass/fail verdict; the payload is counts + list + boolean only.
    assert mol.any_hit is True and mol.PAINS_count == 3


def test_malformed_match_entries_are_skipped_not_raised():
    """An entry missing a name, or with non-list atoms, is skipped; a valid sibling still lands."""
    recs = [pains_brenk_rec(
        pains=1,
        pains_matches=[
            {"name": "", "atoms": [1]},          # empty name -> skipped
            {"atoms": [2]},                       # no name -> skipped
            {"name": "real_alert", "atoms": "x"},  # bad atoms -> kept, atoms empties out
            {"name": "with_atoms", "atoms": [7, 7, 8]},
        ],
    )]
    mol = aggregate({"m": recs}).molecules[0]
    by_name = {a.name: a for a in mol.matched}
    assert set(by_name) == {"real_alert", "with_atoms"}
    assert by_name["real_alert"].atoms == []
    assert by_name["with_atoms"].atoms == [7, 8]  # deduped + sorted


# --------------------------------------------------------------------------------------------------
# Input-shape normalization and multiple molecules.
# --------------------------------------------------------------------------------------------------
def test_accepted_input_shapes_normalize_the_same():
    rec = pains_brenk_rec(pains=1, pains_matches=[{"name": "q", "atoms": [0]}])
    as_map = aggregate({"molA": [rec]}).molecules[0]
    as_pairs = aggregate([("molA", [rec])]).molecules[0]
    as_dicts = aggregate([{"mol_id": "molA", "records": [rec]}]).molecules[0]
    as_bare = aggregate([[rec]]).molecules[0]
    for m in (as_map, as_pairs, as_dicts):
        assert m.mol_id == "molA"
    assert as_bare.mol_id == "mol_0"
    for m in (as_map, as_pairs, as_dicts, as_bare):
        assert m.PAINS_count == 1 and m.any_hit is True


def test_multiple_molecules_are_independent():
    hit = pains_brenk_rec(pains=1, pains_matches=[{"name": "q", "atoms": [0]}])
    clean = pains_brenk_rec(pains=0, brenk=0)
    result = aggregate({"hit": [hit], "clean": [clean]})
    assert result.n_molecules == 2
    by_id = {m.mol_id: m for m in result.molecules}
    assert by_id["hit"].any_hit is True
    assert by_id["clean"].any_hit is False


def test_empty_bundle_is_a_clean_no_hit():
    mol = aggregate({"m": []}).molecules[0]
    assert (mol.PAINS_count, mol.BRENK_count) == (0, 0)
    assert mol.matched == [] and mol.cross_check == [] and mol.any_hit is False
