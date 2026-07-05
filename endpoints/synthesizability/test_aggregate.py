"""Tests for the synthesizability aggregator (task t48): an escalating-rigor TIER, never one scalar.

Synthetic ``OutputRecord``-shaped inputs only (laptop, core env - no box, no GPU). They exercise what
this ladder endpoint exists to guarantee (task t48, IO_SPEC §2 "synthesizability" / §25-27):

- the tier is the position on the ladder SAscore -> RAscore -> AiZynthFinder, decided by the highest rung
  reached (rung 3 route search is authoritative; else rung 2 RAscore; else rung 1 SAscore);
- the SAscore inversion is honored (LOWER SAscore = easier, so LOW score -> easy, HIGH score -> hard);
- the three scales are NEVER collapsed into one number: the raw ladder is surfaced with the tier and no
  fused/averaged scalar field exists anywhere;
- the AiZynthFinder go/no-go key is ``is_solved`` (not ``solved``);
- missing rungs surface as absent (None); the accepted input shapes normalize the same way.
"""

from __future__ import annotations

import pytest

from core.models import Endpoint, ModelName
from endpoints.synthesizability.aggregate import (
    IS_SOLVED_KEY,
    RASCORE_KEY,
    RASCORE_LIKELY_MIN,
    SASCORE_EASY_MAX,
    SASCORE_KEY,
    TOP_SCORE_KEY,
    Tier,
    aggregate,
)

PROV = {"model": "test"}


def sa_rec(sascore=None) -> dict:
    """A sascore-shaped record (rung 1): SAscore in endpoint_values."""
    ev: dict = {}
    if sascore is not None:
        ev[SASCORE_KEY] = sascore
    return {"model": ModelName.sascore, "endpoint_values": ev, "uncertainty": None, "raw": {}, "provenance": PROV}


def ra_rec(rascore=None) -> dict:
    """A rascore-shaped record (rung 2): RAscore in endpoint_values."""
    ev: dict = {}
    if rascore is not None:
        ev[RASCORE_KEY] = rascore
    return {"model": ModelName.rascore, "endpoint_values": ev, "uncertainty": None, "raw": {}, "provenance": PROV}


def azf_rec(is_solved=None, top_score=None) -> dict:
    """An aizynthfinder-shaped record (rung 3): is_solved + top_score in endpoint_values."""
    ev: dict = {}
    if is_solved is not None:
        ev[IS_SOLVED_KEY] = is_solved
    if top_score is not None:
        ev[TOP_SCORE_KEY] = top_score
    return {"model": ModelName.aizynthfinder, "endpoint_values": ev, "uncertainty": None, "raw": {}, "provenance": PROV}


# --------------------------------------------------------------------------------------------------
# Top of the ladder: a real route search confirms -> confirmed (the task's worked example).
# --------------------------------------------------------------------------------------------------
def test_low_sascore_high_rascore_solved_is_top_tier_confirmed():
    """low SAscore + high RAscore + is_solved -> the top tier (the task's example)."""
    recs = [sa_rec(sascore=2.1), ra_rec(rascore=0.95), azf_rec(is_solved=True, top_score=0.88)]
    mol = aggregate({"m": recs}).molecules[0]
    assert mol.tier is Tier.confirmed
    # every raw rung is surfaced unchanged alongside the tier.
    assert mol.SAscore == 2.1
    assert mol.RAscore == 0.95
    assert mol.is_solved is True
    assert mol.top_score == 0.88


def test_route_search_is_authoritative_even_when_lower_rungs_disagree():
    """rung 3 is the gold standard: is_solved=True -> confirmed even if SAscore/RAscore look poor."""
    recs = [sa_rec(sascore=9.0), ra_rec(rascore=0.05), azf_rec(is_solved=True, top_score=0.7)]
    mol = aggregate({"m": recs}).molecules[0]
    assert mol.tier is Tier.confirmed
    # the disagreeing rungs are still surfaced raw, not overwritten.
    assert mol.SAscore == 9.0 and mol.RAscore == 0.05


def test_route_search_no_route_is_hard():
    """is_solved=False (route search found no route in budget) -> hard, whatever the lower rungs say."""
    recs = [sa_rec(sascore=2.0), ra_rec(rascore=0.9), azf_rec(is_solved=False)]
    mol = aggregate({"m": recs}).molecules[0]
    assert mol.tier is Tier.hard
    assert mol.is_solved is False


# --------------------------------------------------------------------------------------------------
# Middle rung: no route-search verdict -> RAscore decides likely vs hard at its 0.5 boundary.
# --------------------------------------------------------------------------------------------------
def test_rascore_above_threshold_is_likely_when_no_route_search():
    recs = [sa_rec(sascore=4.0), ra_rec(rascore=0.8)]
    mol = aggregate({"m": recs}).molecules[0]
    assert mol.tier is Tier.likely
    assert mol.is_solved is None  # rung 3 did not run


def test_rascore_below_threshold_is_hard_when_no_route_search():
    recs = [sa_rec(sascore=3.0), ra_rec(rascore=0.2)]
    mol = aggregate({"m": recs}).molecules[0]
    # low SAscore (easy triage) does NOT rescue a low RAscore: the higher rung reached decides.
    assert mol.tier is Tier.hard


def test_rascore_exactly_at_threshold_is_likely():
    """RASCORE_LIKELY_MIN is inclusive (>=): a route is predicted findable at the boundary."""
    recs = [ra_rec(rascore=RASCORE_LIKELY_MIN)]
    mol = aggregate({"m": recs}).molecules[0]
    assert mol.tier is Tier.likely


# --------------------------------------------------------------------------------------------------
# Bottom rung: only SAscore -> the inversion (LOWER = easier) must be honored.
# --------------------------------------------------------------------------------------------------
def test_only_low_sascore_is_easy_inversion_handled():
    """LOW SAscore = easy to synthesize (inverted scale). Only rung 1 available -> easy, not confirmed."""
    mol = aggregate({"m": [sa_rec(sascore=2.5)]}).molecules[0]
    assert mol.tier is Tier.easy


def test_only_high_sascore_is_hard_inversion_handled():
    """HIGH SAscore = hard to synthesize. The inversion is the whole point of this rung."""
    mol = aggregate({"m": [sa_rec(sascore=8.5)]}).molecules[0]
    assert mol.tier is Tier.hard


def test_sascore_exactly_at_threshold_is_easy():
    """SASCORE_EASY_MAX is inclusive (<=): a score right at the boundary reads as easy."""
    mol = aggregate({"m": [sa_rec(sascore=SASCORE_EASY_MAX)]}).molecules[0]
    assert mol.tier is Tier.easy


# --------------------------------------------------------------------------------------------------
# No fused scalar: the three scales are never collapsed into one number.
# --------------------------------------------------------------------------------------------------
def test_no_single_fused_scalar_only_tier_plus_raw_rungs():
    result = aggregate({"m": [sa_rec(sascore=3.0), ra_rec(rascore=0.7), azf_rec(is_solved=True)]})
    mol = result.molecules[0]
    fields = set(mol.model_dump().keys())
    assert fields == {"mol_id", "present", "tier", "SAscore", "RAscore", "is_solved", "top_score", "notes"}
    # no averaged/fused/consensus synthesizability number exists anywhere on the molecule.
    assert not (fields & {"score", "value", "consensus", "mean", "combined", "synthesizability", "scalar"})
    # tier is a category (a Tier enum / str), not a numeric fusion of the rungs.
    assert isinstance(mol.tier, Tier)
    assert mol.tier == Tier.confirmed


def test_ladder_disagreement_stays_visible():
    """When rungs disagree, both the tier and every raw rung are reported so the reader sees the conflict."""
    # SAscore says easy (2.0) but RAscore says a route is unlikely (0.1): the raw values must both survive.
    mol = aggregate({"m": [sa_rec(sascore=2.0), ra_rec(rascore=0.1)]}).molecules[0]
    assert mol.tier is Tier.hard        # the higher rung reached (RAscore) decides
    assert mol.SAscore == 2.0           # the disagreeing easy triage is still surfaced
    assert mol.RAscore == 0.1


# --------------------------------------------------------------------------------------------------
# Absence and robustness.
# --------------------------------------------------------------------------------------------------
def test_empty_bundle_is_absent_no_tier():
    mol = aggregate({"m": []}).molecules[0]
    assert mol.present is False
    assert mol.tier is None
    assert (mol.SAscore, mol.RAscore, mol.is_solved, mol.top_score) == (None, None, None, None)


def test_null_valued_rungs_treated_as_absent():
    """A failed-parse record carries the keys with None values (the adapters' null shape) -> absent."""
    rec = {
        "model": ModelName.sascore,
        "endpoint_values": {SASCORE_KEY: None},
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }
    mol = aggregate({"m": [rec]}).molecules[0]
    assert mol.present is False
    assert mol.tier is None


def test_top_score_alone_does_not_make_present_or_a_tier():
    """top_score is context for the top route; without is_solved it is not a go/no-go rung by itself."""
    mol = aggregate({"m": [azf_rec(top_score=0.6)]}).molecules[0]
    assert mol.top_score == 0.6
    assert mol.is_solved is None
    assert mol.present is False   # no decision rung produced a value
    assert mol.tier is None


def test_is_solved_read_not_solved_key():
    """The go/no-go key is is_solved; a stray 'solved' key (internal per-node) must be ignored (F-11)."""
    rec = {
        "model": ModelName.aizynthfinder,
        "endpoint_values": {"solved": True},  # WRONG key on purpose
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }
    mol = aggregate({"m": [rec]}).molecules[0]
    assert mol.is_solved is None   # 'solved' is not read
    assert mol.tier is None


# --------------------------------------------------------------------------------------------------
# Result shape, input normalization, multiple molecules.
# --------------------------------------------------------------------------------------------------
def test_result_shape_is_tier_plus_ladder_no_gate_scalar():
    result = aggregate({"m": [sa_rec(sascore=3.0)]})
    assert result.endpoint == Endpoint.synthesizability
    result_fields = set(result.model_dump().keys())
    assert result_fields == {"endpoint", "quantity", "molecules", "n_molecules", "notes"}
    assert not (result_fields & {"consensus", "score", "mean", "combined", "scalar"})


def test_accepted_input_shapes_normalize_the_same():
    recs = [sa_rec(sascore=2.0), ra_rec(rascore=0.9), azf_rec(is_solved=True)]
    as_map = aggregate({"molA": recs}).molecules[0]
    as_pairs = aggregate([("molA", recs)]).molecules[0]
    as_dicts = aggregate([{"mol_id": "molA", "records": recs}]).molecules[0]
    as_bare = aggregate([recs]).molecules[0]
    for m in (as_map, as_pairs, as_dicts):
        assert m.mol_id == "molA"
    assert as_bare.mol_id == "mol_0"
    for m in (as_map, as_pairs, as_dicts, as_bare):
        assert m.tier is Tier.confirmed


def test_multiple_molecules_are_independent():
    easy = [sa_rec(sascore=2.0), ra_rec(rascore=0.9), azf_rec(is_solved=True)]
    hard = [sa_rec(sascore=9.0), azf_rec(is_solved=False)]
    result = aggregate({"good": easy, "bad": hard})
    assert result.n_molecules == 2
    by_id = {m.mol_id: m for m in result.molecules}
    assert by_id["good"].tier is Tier.confirmed
    assert by_id["bad"].tier is Tier.hard


def test_tier_ordering_reflects_ascending_confidence():
    """The four tiers order hard < easy < likely < confirmed (ascending confidence in synthesizability)."""
    order = [Tier.hard, Tier.easy, Tier.likely, Tier.confirmed]
    members = list(Tier)
    assert members == order


def test_first_non_none_rung_value_wins_never_combined():
    """If two records carry the same rung key, the first non-None value is surfaced; rungs are never fused."""
    mol = aggregate({"m": [ra_rec(rascore=0.9), ra_rec(rascore=0.1)]}).molecules[0]
    assert mol.RAscore == 0.9   # first non-None wins; NOT the mean of 0.9 and 0.1
    assert mol.tier is Tier.likely


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
