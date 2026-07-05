"""Tests for the permeability aggregator (task t46): a permeability flag SEPARATE from an absorption flag.

Synthetic ``OutputRecord``-shaped inputs only (laptop, core env - no box, no GPU). They exercise the
things this aggregate-only endpoint exists to guarantee (task t46, IO_SPEC §1 #23):

- the contributing signals sit on incompatible scales (log Papp / probability / bool), and each is
  mapped to a categorical flag on its OWN scale, then voted - never averaged across scales;
- the vote resolves correctly (majority permeable -> permeable, majority non -> non, tie -> borderline);
- permeability and absorption come out as two SEPARATE fields, never merged into one scalar;
- ``Bioavailability_Ma`` / %F is WEAK: it is flagged/surfaced but DOWN-WEIGHTED out of the absorption
  vote so it can never dominate the consensus;
- efflux (Pgp_Broccatelli) is surfaced apart from the passive-permeability vote (a different axis);
- the accepted input shapes normalize the same way; missing sources degrade gracefully.
"""

from __future__ import annotations

from core.models import Endpoint, ModelName
from endpoints.permeability.aggregate import (
    ABSORBED,
    BORDERLINE,
    HIGH,
    LOW,
    NON,
    PERMEABLE,
    UNKNOWN,
    aggregate,
)

PROV = {"model": "test"}


def admet_ai_rec(caco2=None, pampa=None, hia=None, bioavail=None, pgp=None) -> dict:
    ev: dict = {}
    if caco2 is not None:
        ev["Caco2_Wang"] = caco2
    if pampa is not None:
        ev["PAMPA_NCATS"] = pampa
    if hia is not None:
        ev["HIA_Hou"] = hia
    if bioavail is not None:
        ev["Bioavailability_Ma"] = bioavail
    if pgp is not None:
        ev["Pgp_Broccatelli"] = pgp
    return {
        "model": ModelName.admet_ai,
        "endpoint_values": ev,
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }


def boiled_egg_rec(hia=None) -> dict:
    return {
        "model": ModelName.boiled_egg,
        "endpoint_values": {"HIA_boiled_egg": hia, "BBB_boiled_egg": False},
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }


# --------------------------------------------------------------------------------------------------
# Permeability read: each scale maps to a flag, then vote; efflux surfaced apart.
# --------------------------------------------------------------------------------------------------
def test_each_permeability_scale_maps_to_a_flag_on_its_own_scale():
    """Every passive-permeability signal is mapped to a flag labeled with its native scale."""
    recs = [admet_ai_rec(caco2=-4.5, pampa=0.5)]  # log Papp >= -5.15 -> permeable; prob 0.5 -> borderline
    perm = aggregate({"m": recs}).molecules[0].permeability
    assert perm.present
    by_field = {v.field: v for v in perm.votes}
    assert by_field["Caco2_Wang"].scale == "log Papp" and by_field["Caco2_Wang"].flag == PERMEABLE
    assert by_field["PAMPA_NCATS"].scale == "probability" and by_field["PAMPA_NCATS"].flag == BORDERLINE
    assert (perm.n_permeable, perm.n_borderline, perm.n_non) == (1, 1, 0)


def test_permeability_vote_permeable_majority():
    recs = [admet_ai_rec(caco2=-4.5, pampa=0.9)]  # both permeable
    perm = aggregate({"m": recs}).molecules[0].permeability
    assert perm.consensus == PERMEABLE


def test_permeability_vote_non_majority():
    recs = [admet_ai_rec(caco2=-6.5, pampa=0.1)]  # log Papp <= -6.0 -> non; prob 0.1 -> non
    perm = aggregate({"m": recs}).molecules[0].permeability
    assert perm.consensus == NON


def test_permeability_vote_tie_is_borderline():
    recs = [admet_ai_rec(caco2=-4.0, pampa=0.1)]  # 1 permeable vs 1 non -> tie -> borderline
    perm = aggregate({"m": recs}).molecules[0].permeability
    assert perm.consensus == BORDERLINE


def test_caco2_borderline_band():
    recs = [admet_ai_rec(caco2=-5.5)]  # between -6.0 and -5.15 -> borderline
    perm = aggregate({"m": recs}).molecules[0].permeability
    assert perm.votes[0].flag == BORDERLINE
    assert perm.consensus == BORDERLINE


def test_efflux_surfaced_apart_from_permeability_vote():
    """Pgp_Broccatelli is recorded as its own efflux signal, not folded into the permeability consensus."""
    recs = [admet_ai_rec(caco2=-4.5, pampa=0.9, pgp=0.8)]  # permeable AND effluxed
    perm = aggregate({"m": recs}).molecules[0].permeability
    # permeability vote unaffected by efflux
    assert perm.consensus == PERMEABLE
    assert (perm.n_permeable, perm.n_non) == (2, 0)
    # efflux lives in its own field
    assert len(perm.efflux) == 1
    assert perm.efflux[0].field == "Pgp_Broccatelli"
    assert perm.efflux[0].flag == HIGH
    assert perm.efflux_consensus == HIGH
    # the Pgp probability is NOT one of the permeability votes
    assert "Pgp_Broccatelli" not in {v.field for v in perm.votes}


def test_efflux_low_liability():
    recs = [admet_ai_rec(caco2=-4.5, pgp=0.2)]
    perm = aggregate({"m": recs}).molecules[0].permeability
    assert perm.efflux_consensus == LOW


def test_efflux_out_of_range_probability_rejected():
    # the t28 helper rejects a non-[0,1] value rather than clamping, so it contributes no efflux signal
    perm = aggregate({"m": [admet_ai_rec(caco2=-4.5, pgp=1.7)]}).molecules[0].permeability
    assert perm.efflux == []
    assert perm.efflux_consensus == UNKNOWN
    # the permeability vote still resolves on Caco2
    assert perm.consensus == PERMEABLE


def test_no_permeability_signal_is_unknown_and_absent():
    perm = aggregate({"m": [boiled_egg_rec(hia=True)]}).molecules[0].permeability
    assert perm.present is False
    assert perm.consensus == UNKNOWN
    assert perm.efflux_consensus == UNKNOWN


# --------------------------------------------------------------------------------------------------
# Absorption read: HIA_Hou + BOILED-Egg vote; %F is suspect and does not vote.
# --------------------------------------------------------------------------------------------------
def test_absorption_votes_hia_and_boiled_egg():
    recs = [admet_ai_rec(hia=0.9), boiled_egg_rec(hia=True)]
    absn = aggregate({"m": recs}).molecules[0].absorption
    by_field = {v.field: v for v in absn.votes}
    assert by_field["HIA_Hou"].scale == "probability" and by_field["HIA_Hou"].flag == ABSORBED
    assert by_field["HIA_boiled_egg"].scale == "bool" and by_field["HIA_boiled_egg"].flag == ABSORBED
    assert absn.consensus == ABSORBED
    assert (absn.n_absorbed, absn.n_non) == (2, 0)


def test_absorption_non_majority():
    recs = [admet_ai_rec(hia=0.1), boiled_egg_rec(hia=False)]
    absn = aggregate({"m": recs}).molecules[0].absorption
    assert absn.consensus == NON


def test_absorption_tie_is_borderline():
    recs = [admet_ai_rec(hia=0.9), boiled_egg_rec(hia=False)]  # 1 absorbed vs 1 non
    absn = aggregate({"m": recs}).molecules[0].absorption
    assert absn.consensus == BORDERLINE


def test_bioavailability_is_suspect_and_does_not_vote():
    """%F is flagged/surfaced but DOWN-WEIGHTED out of the vote so it cannot dominate (task t46 landmine)."""
    # %F strongly says "absorbed" (0.99) but the two trusted signals say non; %F must NOT flip the vote.
    recs = [admet_ai_rec(hia=0.1, bioavail=0.99), boiled_egg_rec(hia=False)]
    absn = aggregate({"m": recs}).molecules[0].absorption
    # trusted vote: 2 non -> non, unmoved by the suspect %F
    assert absn.consensus == NON
    assert (absn.n_absorbed, absn.n_non) == (0, 2)
    # %F is surfaced in its own suspect list, flagged, and marked suspect
    assert len(absn.suspect_signals) == 1
    sus = absn.suspect_signals[0]
    assert sus.field == "Bioavailability_Ma"
    assert sus.suspect is True
    assert sus.flag == ABSORBED
    assert sus.raw_value == 0.99
    # it is NOT among the counted votes
    assert "Bioavailability_Ma" not in {v.field for v in absn.votes}


def test_only_bioavailability_present_is_present_but_unknown_consensus():
    # if %F is the ONLY absorption signal, the read is present (it is surfaced) but the vote is UNKNOWN
    absn = aggregate({"m": [admet_ai_rec(bioavail=0.9)]}).molecules[0].absorption
    assert absn.present is True
    assert absn.votes == []
    assert absn.consensus == UNKNOWN
    assert len(absn.suspect_signals) == 1


def test_no_absorption_signal_is_unknown_and_absent():
    absn = aggregate({"m": [admet_ai_rec(caco2=-4.5)]}).molecules[0].absorption
    assert absn.present is False
    assert absn.consensus == UNKNOWN


# --------------------------------------------------------------------------------------------------
# Two separate flags; no combined scalar; no cross-scale averaging.
# --------------------------------------------------------------------------------------------------
def test_permeability_and_absorption_are_separate_fields():
    recs = [admet_ai_rec(caco2=-4.5, pampa=0.9, hia=0.9, pgp=0.8), boiled_egg_rec(hia=True)]
    mol = aggregate({"m": recs}).molecules[0]
    assert mol.permeability.present and mol.absorption.present
    assert mol.permeability.consensus == PERMEABLE
    assert mol.absorption.consensus == ABSORBED
    # two separate reads; nothing merges them into a single scalar
    assert hasattr(mol, "permeability") and hasattr(mol, "absorption")


def test_no_combined_scalar_or_cross_scale_average():
    """The result carries per-signal raw values and categorical flags only - never a mean across scales."""
    recs = [admet_ai_rec(caco2=-4.5, pampa=0.0), boiled_egg_rec(hia=True)]
    mol = aggregate({"m": recs}).molecules[0]
    raws = {v.field: v.raw_value for v in mol.permeability.votes}
    assert raws["Caco2_Wang"] == -4.5
    assert raws["PAMPA_NCATS"] == 0.0
    # no averaged scalar field anywhere on either read or the molecule
    for obj in (mol, mol.permeability, mol.absorption):
        assert not hasattr(obj, "mean")
        assert not hasattr(obj, "score")


# --------------------------------------------------------------------------------------------------
# Input-shape normalization + result envelope.
# --------------------------------------------------------------------------------------------------
def test_result_envelope_and_endpoint():
    result = aggregate({"a": [admet_ai_rec(caco2=-4.5)], "b": [boiled_egg_rec(hia=True)]})
    assert result.endpoint == Endpoint.permeability
    assert result.n_molecules == 2
    assert {m.mol_id for m in result.molecules} == {"a", "b"}
    assert result.deferred  # the calibrated gate policy is DEFERRED


def test_input_shapes_normalize_the_same():
    recs = [admet_ai_rec(caco2=-4.5, pampa=0.9)]
    as_map = aggregate({"m0": recs})
    as_pairs = aggregate([("m0", recs)])
    as_dicts = aggregate([{"mol_id": "m0", "records": recs}])
    as_bare = aggregate([recs])
    for res in (as_map, as_pairs, as_dicts):
        assert res.molecules[0].permeability.consensus == PERMEABLE
    assert as_bare.molecules[0].mol_id == "mol_0"
    assert as_bare.molecules[0].permeability.consensus == PERMEABLE


def test_multiple_molecules_independent():
    good = [admet_ai_rec(caco2=-4.0, pampa=0.95, hia=0.95), boiled_egg_rec(hia=True)]
    bad = [admet_ai_rec(caco2=-6.5, pampa=0.05, hia=0.05), boiled_egg_rec(hia=False)]
    result = aggregate({"good": good, "bad": bad})
    by_id = {m.mol_id: m for m in result.molecules}
    assert by_id["good"].permeability.consensus == PERMEABLE
    assert by_id["good"].absorption.consensus == ABSORBED
    assert by_id["bad"].permeability.consensus == NON
    assert by_id["bad"].absorption.consensus == NON
