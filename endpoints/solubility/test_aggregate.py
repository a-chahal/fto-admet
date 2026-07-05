"""Tests for the solubility relative-rank aggregator (task t41).

Synthetic ``OutputRecord``-shaped inputs only (laptop, core env - no box, no GPU). They exercise:
- the direction inversion (landmine): SFI LOWER = better vs log S HIGHER = better must be reconciled so
  a low-SFI molecule AND a high-log S molecule both rank as MORE soluble, never less;
- ``sfi_soluble_score`` negates SFI so the two lenses point the same way;
- co-ranking is ordinal, never a raw average of the two incompatible scales;
- a large SFI-vs-generalist rank gap raises the per-molecule discrepancy flag, while agreement does not;
- the accepted input shapes (mapping / (id, records) pairs / bare record-lists) normalize the same way;
- molecules missing a lens degrade gracefully (no primary rank, or no discrepancy).
"""

from __future__ import annotations

from core.models import Endpoint, ModelName
from endpoints.solubility.aggregate import (
    DISCREPANCY_PCT_FLAG,
    aggregate,
    sfi_soluble_score,
)

PROV = {"model": "test"}


def sfi_rec(sfi: float | None) -> dict:
    return {
        "model": ModelName.sfi,
        "endpoint_values": {"SFI": sfi, "cLogD_7.4": None if sfi is None else sfi - 1.0, "n_aromatic_rings": 1},
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }


def admet_ai_rec(logs: float | None) -> dict:
    return {
        "model": ModelName.admet_ai,
        "endpoint_values": {"Solubility_AqSolDB": logs, "HIA_Hou": 0.98},
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }


def mol(mol_id: str, sfi: float | None, logs: float | None) -> tuple[str, list[dict]]:
    recs = []
    if sfi is not None:
        recs.append(sfi_rec(sfi))
    if logs is not None:
        recs.append(admet_ai_rec(logs))
    return mol_id, recs


# --------------------------------------------------------------------------------------------------
# Direction harmonization: -SFI points the same way as log S.
# --------------------------------------------------------------------------------------------------
def test_sfi_soluble_score_negates():
    # lower SFI (more soluble) -> higher soluble score
    assert sfi_soluble_score(2.0) > sfi_soluble_score(8.0)
    assert sfi_soluble_score(3.0) == -3.0


# --------------------------------------------------------------------------------------------------
# The inversion is handled: a low-SFI molecule and a high-log S molecule both rank as MORE soluble.
# --------------------------------------------------------------------------------------------------
def test_low_sfi_and_high_logs_rank_more_soluble():
    # A: low SFI + high log S -> most soluble by BOTH lenses
    # B: middle
    # C: high SFI + low log S -> least soluble by BOTH lenses
    molecules = [
        mol("A", sfi=2.0, logs=-2.0),
        mol("B", sfi=5.0, logs=-4.0),
        mol("C", sfi=8.0, logs=-7.0),
    ]

    res = aggregate(molecules)

    assert res.endpoint == Endpoint.solubility
    assert res.n_molecules == 3
    assert res.n_ranked == 3
    # ordered most -> least soluble: the LOW-SFI / HIGH-logS molecule is first (inversion handled;
    # a naive sort on raw SFI ascending would still work, but a raw AVERAGE of SFI and logS would put
    # C above A because -7 log S drags the mean down - the point of ordinal co-ranking).
    assert [m.mol_id for m in res.ranking] == ["A", "B", "C"]
    top, bottom = res.ranking[0], res.ranking[-1]
    assert top.mol_id == "A" and bottom.mol_id == "C"
    # primary rank 1 = most soluble = lowest SFI; and the harmonized score points the right way.
    assert top.primary_rank == 1 and bottom.primary_rank == 3
    assert top.sfi_soluble_score > bottom.sfi_soluble_score
    # cross-check agrees (highest log S is most soluble)
    assert top.crosscheck_rank == 1 and bottom.crosscheck_rank == 3
    # they agree -> no discrepancy flags
    assert res.n_discrepant == 0
    assert all(m.discrepancy_flag is False for m in res.ranking)


# --------------------------------------------------------------------------------------------------
# A large SFI-vs-generalist gap raises the discrepancy flag.
# --------------------------------------------------------------------------------------------------
def test_large_sfi_vs_generalist_gap_flags_discrepancy():
    # P: SFI says MOST soluble (lowest SFI) but log S says LEAST soluble (lowest log S) -> opposite ends.
    # Q: agrees in the middle.
    # R: SFI says least soluble but log S says most soluble -> also opposite ends.
    molecules = [
        mol("P", sfi=1.0, logs=-8.0),
        mol("Q", sfi=5.0, logs=-5.0),
        mol("R", sfi=9.0, logs=-2.0),
    ]

    res = aggregate(molecules)

    by_id = {m.mol_id: m for m in res.ranking}
    p, q, r = by_id["P"], by_id["Q"], by_id["R"]

    # P: primary position 0.0 (most soluble by SFI), cross-check 1.0 (least by log S) -> gap 1.0
    assert p.primary_pct == 0.0 and p.crosscheck_pct == 1.0
    assert p.discrepancy == 1.0 and p.discrepancy_flag is True
    # R: the mirror image -> also flagged
    assert r.primary_pct == 1.0 and r.crosscheck_pct == 0.0
    assert r.discrepancy == 1.0 and r.discrepancy_flag is True
    # Q: the two lenses agree -> no flag
    assert q.discrepancy == 0.0 and q.discrepancy_flag is False
    assert res.n_discrepant == 2
    # discrepancy note carried on the flagged molecule
    assert any("SFI-vs-generalist discrepancy" in n for n in p.notes)


def test_threshold_boundary_not_flagged_at_or_below_cut():
    # Build a 3-molecule set where one molecule's gap equals exactly DISCREPANCY_PCT_FLAG (0.5):
    # positions available are {0.0, 0.5, 1.0}. Molecule M: SFI-position 0.0, logS-position 0.5 -> gap 0.5.
    molecules = [
        mol("M", sfi=1.0, logs=-5.0),  # SFI most soluble (0.0); logS middle (0.5)
        mol("N", sfi=5.0, logs=-2.0),  # SFI middle (0.5); logS most soluble (0.0)
        mol("O", sfi=9.0, logs=-8.0),  # SFI least (1.0); logS least (1.0)
    ]
    res = aggregate(molecules)
    m = next(x for x in res.ranking if x.mol_id == "M")
    assert m.discrepancy == DISCREPANCY_PCT_FLAG
    # strictly-greater-than test: a gap exactly at the cut does NOT flag
    assert m.discrepancy_flag is False


# --------------------------------------------------------------------------------------------------
# Graceful degradation when a lens is missing.
# --------------------------------------------------------------------------------------------------
def test_molecule_missing_logs_has_no_discrepancy_but_is_still_ranked():
    molecules = [
        mol("A", sfi=2.0, logs=-2.0),
        mol("B", sfi=6.0, logs=None),  # no generalist cross-check
    ]
    res = aggregate(molecules)
    b = next(m for m in res.ranking if m.mol_id == "B")
    assert b.primary_rank is not None          # still primary-ranked by SFI
    assert b.crosscheck_rank is None
    assert b.discrepancy is None and b.discrepancy_flag is False
    assert any("discrepancy cannot be computed" in n for n in b.notes)


def test_molecule_missing_sfi_falls_to_end_but_keeps_crosscheck():
    molecules = [
        mol("A", sfi=2.0, logs=-2.0),
        mol("Z", sfi=None, logs=-1.0),  # only the generalist; no primary SFI
    ]
    res = aggregate(molecules)
    # A has a primary rank so it sorts ahead of Z (which has no primary lens), regardless of log S.
    assert res.ranking[0].mol_id == "A"
    z = res.ranking[-1]
    assert z.mol_id == "Z"
    assert z.primary_rank is None and z.crosscheck_rank is not None
    assert res.n_ranked == 1
    assert any("not primary-ranked" in n for n in z.notes)


def test_set_with_no_sfi_falls_back_to_crosscheck_ranking():
    molecules = [
        mol("A", sfi=None, logs=-2.0),
        mol("B", sfi=None, logs=-6.0),
    ]
    res = aggregate(molecules)
    assert res.n_ranked == 0
    # ordered by the log S cross-check: higher log S (A) is more soluble -> first
    assert [m.mol_id for m in res.ranking] == ["A", "B"]
    assert any("falls back to the log S cross-check" in n for n in res.notes)


# --------------------------------------------------------------------------------------------------
# Input-shape normalization: mapping / (id, records) pairs / bare record-lists agree.
# --------------------------------------------------------------------------------------------------
def test_mapping_and_pair_inputs_agree():
    as_pairs = [
        mol("A", sfi=2.0, logs=-2.0),
        mol("C", sfi=8.0, logs=-7.0),
    ]
    as_mapping = {mid: recs for mid, recs in as_pairs}

    r_pairs = aggregate(as_pairs)
    r_map = aggregate(as_mapping)

    assert [m.mol_id for m in r_pairs.ranking] == [m.mol_id for m in r_map.ranking]
    assert r_pairs.n_discrepant == r_map.n_discrepant


def test_bare_record_lists_get_positional_ids():
    bundle_a = [sfi_rec(2.0), admet_ai_rec(-2.0)]
    bundle_b = [sfi_rec(8.0), admet_ai_rec(-7.0)]
    res = aggregate([bundle_a, bundle_b])
    assert {m.mol_id for m in res.ranking} == {"mol_0", "mol_1"}


def test_dict_with_records_key_uses_declared_id():
    res = aggregate(
        [
            {"mol_id": "FTO-43", "records": [sfi_rec(3.0), admet_ai_rec(-3.0)]},
            {"id": "control", "records": [sfi_rec(9.0), admet_ai_rec(-8.0)]},
        ]
    )
    ids = [m.mol_id for m in res.ranking]
    assert "FTO-43" in ids and "control" in ids
    # FTO-43 (lower SFI) ranks more soluble than the control
    assert ids[0] == "FTO-43"


def test_empty_input_yields_empty_ranking():
    res = aggregate([])
    assert res.ranking == []
    assert res.n_molecules == 0 and res.n_ranked == 0 and res.n_discrepant == 0


def test_deferred_boundaries_are_flagged():
    res = aggregate([mol("A", sfi=2.0, logs=-2.0)])
    joined = " ".join(res.deferred)
    assert "calibrat" in joined.lower()
    assert "F-13" in joined and "F-16" in joined
