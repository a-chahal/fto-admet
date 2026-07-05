"""Tests for the distribution aggregator (task t44): passive penetration SEPARATE from efflux (F-4).

Synthetic ``OutputRecord``-shaped inputs only (laptop, core env - no box, no GPU). They exercise the
things this aggregator exists to guarantee (F-4, CLAUDE.md §4):

- the four passive signals sit on incompatible scales (0-6 desirability / probability / bool), and each
  is mapped to a categorical flag on its OWN scale, then voted - never averaged across scales;
- the vote resolves correctly (majority penetrant -> penetrant, majority non -> non, tie -> borderline);
- passive penetration and efflux come out as two SEPARATE fields, never merged into one score;
- the efflux read votes Pgp_Broccatelli (via the t28 derived-pgp helper) + Watanabe NER class, and
  surfaces Kp,uu,brain separately as the closest proxy to the real CNS answer;
- unmapped NER labels degrade to 'unknown' and do not vote (no-fabricate);
- the accepted input shapes normalize the same way; missing sources degrade gracefully.
"""

from __future__ import annotations

from core.models import Endpoint, ModelName
from endpoints.distribution.aggregate import (
    BORDERLINE,
    HIGH,
    KP_UU_PENETRANT,
    LOW,
    NON,
    PENETRANT,
    UNKNOWN,
    aggregate,
)

PROV = {"model": "test"}


def bbb_score_rec(score=None) -> dict:
    return {
        "model": ModelName.bbb_score,
        "endpoint_values": {"BBB_Score": score},
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }


def cns_mpo_rec(score=None) -> dict:
    return {
        "model": ModelName.cns_mpo,
        "endpoint_values": {"CNS_MPO": score},
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }


def admet_ai_rec(bbb_martins=None, pgp=None) -> dict:
    ev: dict = {"HIA_Hou": 0.98}  # an unrelated head that must be ignored
    if bbb_martins is not None:
        ev["BBB_Martins"] = bbb_martins
    if pgp is not None:
        ev["Pgp_Broccatelli"] = pgp
    return {
        "model": ModelName.admet_ai,
        "endpoint_values": ev,
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }


def boiled_egg_rec(bbb=None) -> dict:
    return {
        "model": ModelName.boiled_egg,
        "endpoint_values": {"HIA_boiled_egg": True, "BBB_boiled_egg": bbb},
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }


def watanabe_rec(ner=None, kp_uu=None, fu_brain=None) -> dict:
    return {
        "model": ModelName.watanabe_pgp_brain,
        "endpoint_values": {
            "pgp_brain_efflux": ner,
            "Kp_uu_brain": kp_uu,
            "fu_brain": fu_brain,
        },
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }


# --------------------------------------------------------------------------------------------------
# Passive penetration: each scale maps to a flag, then vote.
# --------------------------------------------------------------------------------------------------
def test_each_scale_maps_to_a_flag_on_its_own_scale():
    """Every passive signal is mapped to a categorical flag labeled with its native scale."""
    recs = [
        bbb_score_rec(5.0),        # 0-6, >= 4 -> penetrant
        cns_mpo_rec(1.0),          # 0-6, <= 2 -> non
        admet_ai_rec(bbb_martins=0.5),  # probability, in [0.4, 0.6) -> borderline
        boiled_egg_rec(True),      # bool True -> penetrant
    ]
    result = aggregate({"m": recs})
    passive = result.molecules[0].passive
    assert passive.present
    by_field = {v.field: v for v in passive.votes}
    assert by_field["BBB_Score"].scale == "0-6" and by_field["BBB_Score"].flag == PENETRANT
    assert by_field["CNS_MPO"].scale == "0-6" and by_field["CNS_MPO"].flag == NON
    assert by_field["BBB_Martins"].scale == "probability" and by_field["BBB_Martins"].flag == BORDERLINE
    assert by_field["BBB_boiled_egg"].scale == "bool" and by_field["BBB_boiled_egg"].flag == PENETRANT
    # counts reflect the four flags: 2 penetrant, 1 borderline, 1 non
    assert (passive.n_penetrant, passive.n_borderline, passive.n_non) == (2, 1, 1)


def test_passive_vote_resolves_penetrant_majority():
    recs = [bbb_score_rec(5.5), cns_mpo_rec(4.5), admet_ai_rec(bbb_martins=0.9), boiled_egg_rec(False)]
    passive = aggregate({"m": recs}).molecules[0].passive
    # 3 penetrant vs 1 non -> penetrant
    assert passive.consensus == PENETRANT


def test_passive_vote_resolves_non_majority():
    recs = [bbb_score_rec(1.0), cns_mpo_rec(0.5), admet_ai_rec(bbb_martins=0.1), boiled_egg_rec(True)]
    passive = aggregate({"m": recs}).molecules[0].passive
    # 3 non vs 1 penetrant -> non
    assert passive.consensus == NON


def test_passive_vote_tie_is_borderline():
    recs = [bbb_score_rec(5.0), boiled_egg_rec(False)]
    passive = aggregate({"m": recs}).molecules[0].passive
    # 1 penetrant vs 1 non -> tie -> borderline
    assert passive.consensus == BORDERLINE


def test_passive_borderline_dominated_set_is_borderline():
    recs = [admet_ai_rec(bbb_martins=0.5), cns_mpo_rec(3.0)]  # both borderline
    passive = aggregate({"m": recs}).molecules[0].passive
    assert passive.consensus == BORDERLINE


def test_no_passive_signal_is_unknown_and_absent():
    passive = aggregate({"m": [watanabe_rec(ner="Low")]}).molecules[0].passive
    assert passive.present is False
    assert passive.consensus == UNKNOWN


# --------------------------------------------------------------------------------------------------
# Efflux: separate read, its own vote, Kp,uu surfaced apart.
# --------------------------------------------------------------------------------------------------
def test_efflux_is_a_separate_field_from_passive():
    recs = [bbb_score_rec(5.0), admet_ai_rec(bbb_martins=0.9, pgp=0.8), watanabe_rec(ner="High", kp_uu=0.1)]
    mol = aggregate({"m": recs}).molecules[0]
    # both reads present, in their own fields, and there is no combined distribution scalar
    assert mol.passive.present and mol.efflux.present
    assert mol.passive.consensus == PENETRANT
    assert mol.efflux.consensus == HIGH
    # the two live in separate attributes; nothing merges them
    assert hasattr(mol, "passive") and hasattr(mol, "efflux")


def test_efflux_votes_pgp_and_ner():
    recs = [admet_ai_rec(pgp=0.75), watanabe_rec(ner="High", kp_uu=0.2)]
    efflux = aggregate({"m": recs}).molecules[0].efflux
    flags = {(s.model, s.field): s.flag for s in efflux.signals}
    assert flags[(ModelName.admet_ai, "Pgp_Broccatelli")] == HIGH
    assert flags[(ModelName.watanabe_pgp_brain, "pgp_brain_efflux")] == HIGH
    assert efflux.consensus == HIGH
    assert (efflux.n_high, efflux.n_low) == (2, 0)


def test_efflux_low_liability():
    recs = [admet_ai_rec(pgp=0.2), watanabe_rec(ner="Low", kp_uu=0.8)]
    efflux = aggregate({"m": recs}).molecules[0].efflux
    assert efflux.consensus == LOW


def test_kp_uu_surfaced_separately_not_folded_into_vote():
    recs = [watanabe_rec(ner="Low", kp_uu=0.8)]
    efflux = aggregate({"m": recs}).molecules[0].efflux
    assert efflux.kp_uu_brain == 0.8
    assert efflux.kp_uu_penetrant is True  # >= 0.5
    # only the NER class voted; Kp,uu did not add a signal
    assert len(efflux.signals) == 1
    assert efflux.signals[0].field == "pgp_brain_efflux"


def test_kp_uu_below_threshold_not_penetrant():
    efflux = aggregate({"m": [watanabe_rec(ner="High", kp_uu=0.3)]}).molecules[0].efflux
    assert efflux.kp_uu_brain == 0.3
    assert efflux.kp_uu_penetrant is False
    assert KP_UU_PENETRANT == 0.5


def test_unmapped_ner_label_degrades_to_unknown_and_does_not_vote():
    # an unexpected class string is not guessed; it degrades to UNKNOWN and does not enter the vote
    recs = [watanabe_rec(ner="Nonsense", kp_uu=0.6), admet_ai_rec(pgp=0.8)]
    efflux = aggregate({"m": recs}).molecules[0].efflux
    ner_sig = next(s for s in efflux.signals if s.field == "pgp_brain_efflux")
    assert ner_sig.flag == UNKNOWN
    assert ner_sig.raw_class == "Nonsense"
    # only the Pgp signal counts -> HIGH
    assert efflux.consensus == HIGH


def test_no_efflux_signal_is_unknown_and_absent():
    efflux = aggregate({"m": [bbb_score_rec(5.0)]}).molecules[0].efflux
    assert efflux.present is False
    assert efflux.consensus == UNKNOWN
    assert efflux.kp_uu_brain is None


def test_pgp_out_of_range_probability_is_rejected():
    # the t28 helper rejects a non-[0,1] value rather than clamping, so it contributes no efflux signal
    efflux = aggregate({"m": [admet_ai_rec(pgp=1.7)]}).molecules[0].efflux
    assert efflux.present is False


# --------------------------------------------------------------------------------------------------
# No cross-scale averaging anywhere.
# --------------------------------------------------------------------------------------------------
def test_no_cross_scale_average_appears_in_result():
    """The result carries per-signal raw values and categorical flags only - never a mean across scales."""
    recs = [bbb_score_rec(6.0), admet_ai_rec(bbb_martins=0.0), boiled_egg_rec(True)]
    passive = aggregate({"m": recs}).molecules[0].passive
    raws = {v.field: v.raw_value for v in passive.votes}
    # the naive (wrong) cross-scale mean of {6.0, 0.0, True} would be ~2.33; it must appear nowhere.
    assert raws["BBB_Score"] == 6.0
    assert raws["BBB_Martins"] == 0.0
    assert raws["BBB_boiled_egg"] is True
    # the read exposes only categorical consensus + counts, no averaged scalar field
    assert not hasattr(passive, "mean")
    assert not hasattr(passive, "score")
    # 2 penetrant (BBB_Score, boiled_egg) vs 1 non (BBB_Martins) -> penetrant
    assert passive.consensus == PENETRANT


# --------------------------------------------------------------------------------------------------
# Input-shape normalization + result envelope.
# --------------------------------------------------------------------------------------------------
def test_result_envelope_and_endpoint():
    result = aggregate({"a": [bbb_score_rec(5.0)], "b": [cns_mpo_rec(1.0)]})
    assert result.endpoint == Endpoint.distribution
    assert result.n_molecules == 2
    assert {m.mol_id for m in result.molecules} == {"a", "b"}
    assert result.deferred  # the calibrated gate policy is DEFERRED


def test_input_shapes_normalize_the_same():
    recs = [bbb_score_rec(5.0), admet_ai_rec(bbb_martins=0.9)]
    as_map = aggregate({"m0": recs})
    as_pairs = aggregate([("m0", recs)])
    as_dicts = aggregate([{"mol_id": "m0", "records": recs}])
    as_bare = aggregate([recs])
    for res in (as_map, as_pairs, as_dicts):
        assert res.molecules[0].passive.consensus == PENETRANT
    # bare list gets a positional id but the same read
    assert as_bare.molecules[0].mol_id == "mol_0"
    assert as_bare.molecules[0].passive.consensus == PENETRANT


def test_multiple_molecules_independent():
    penetrant = [bbb_score_rec(6.0), cns_mpo_rec(5.0), admet_ai_rec(bbb_martins=0.95)]
    non = [bbb_score_rec(0.5), cns_mpo_rec(1.0), admet_ai_rec(bbb_martins=0.05)]
    result = aggregate({"good": penetrant, "bad": non})
    by_id = {m.mol_id: m for m in result.molecules}
    assert by_id["good"].passive.consensus == PENETRANT
    assert by_id["bad"].passive.consensus == NON
