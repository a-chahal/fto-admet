"""Tests for the lipophilicity logD-consensus aggregator (task t40).

Synthetic ``OutputRecord``-shaped inputs only (laptop, core env - no box, no GPU). They exercise:
- a tight cluster -> low spread flag + a consensus near the measured anchor + trust;
- a scattered set -> high spread flag;
- that logP lenses (RDKit Crippen WLOGP, SwissADME consensus) are CONVERTED to logD before entering the
  consensus, and are excluded (never averaged raw) when no shared pKa is available (F-12);
- the shared pKa placeholder is read from OPERA ``pKa_b`` (F-13) and can be injected;
- the Henderson-Hasselbalch conversion math (the F-16 placeholder);
- a consensus far from measured logD ~= 1 lowers trust even when the spread is low (task t40).
"""

from __future__ import annotations

import math

import pytest

from core.models import Endpoint, ModelName
from endpoints.lipophilicity.aggregate import (
    ANCHOR_TOLERANCE,
    DEFAULT_PH,
    MEASURED_LOGD_ANCHOR,
    aggregate,
    logp_to_logd,
)

PROV = {"model": "test"}


def one(records, **kw):
    """Score a single molecule and return its per-molecule result (aggregate() returns a `.molecules` batch)."""
    return aggregate(records, **kw).molecules[0]


def crippen(logp: float) -> dict:
    return {
        "model": ModelName.rdkit_crippen,
        "endpoint_values": {"logP_crippen": logp, "MR": 90.0},
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }


def swissadme(consensus_logp: float) -> dict:
    return {
        "model": ModelName.swissadme,
        "endpoint_values": {"WLOGP": consensus_logp, "MLOGP": consensus_logp, "Consensus_logP": consensus_logp},
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }


def opera_logd(logd: float, conf: float | None = 0.74) -> dict:
    return {
        "model": ModelName.opera,
        "endpoint_values": {"LogD": logd},
        "uncertainty": {"conf_index": conf} if conf is not None else None,
        "raw": {},
        "provenance": PROV,
    }


def opera_pka_b(pka_b: float) -> dict:
    return {
        "model": ModelName.opera,
        "endpoint_values": {"pKa_b": pka_b},
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }


# --------------------------------------------------------------------------------------------------
# Henderson-Hasselbalch conversion (the F-16 placeholder).
# --------------------------------------------------------------------------------------------------
def test_logp_to_logd_base_and_acid():
    # base: logD = logP - log10(1 + 10**(pKa - pH))
    expected_base = 3.0 - math.log10(1 + 10 ** (9.0 - 7.4))
    assert logp_to_logd(3.0, 9.0, ph=7.4, kind="base") == pytest.approx(expected_base)
    # acid: logD = logP - log10(1 + 10**(pH - pKa))
    expected_acid = 3.0 - math.log10(1 + 10 ** (7.4 - 4.0))
    assert logp_to_logd(3.0, 4.0, ph=7.4, kind="acid") == pytest.approx(expected_acid)
    # a basic center well above pH is essentially fully ionized -> logD << logP
    assert logp_to_logd(3.0, 9.0, kind="base") < 3.0 - 1.0


def test_logp_to_logd_rejects_bad_kind():
    with pytest.raises(ValueError):
        logp_to_logd(1.0, 7.0, kind="zwitterion")


# --------------------------------------------------------------------------------------------------
# Tight cluster -> low spread, trust, consensus near the anchor.
# --------------------------------------------------------------------------------------------------
def test_tight_cluster_low_spread_and_trust():
    pka = 8.9  # base; conversion subtracts ~1.51 log units
    drop = math.log10(1 + 10 ** (pka - DEFAULT_PH))
    records = [crippen(2.5), swissadme(2.6), opera_logd(1.0)]

    res = one(records, pka=pka)

    assert res.endpoint == Endpoint.lipophilicity
    assert res.n_lenses == 3
    assert res.spread_flag == "low"
    assert res.trust is True
    assert res.recommend_measured_anchor is False
    # consensus = mean of [2.5-drop, 2.6-drop, 1.0]
    expected = ((2.5 - drop) + (2.6 - drop) + 1.0) / 3
    assert res.consensus == pytest.approx(expected)
    assert res.spread_range <= 1.0
    # near the measured anchor
    assert abs(res.consensus - MEASURED_LOGD_ANCHOR) <= ANCHOR_TOLERANCE


# --------------------------------------------------------------------------------------------------
# Scattered set -> high spread flag.
# --------------------------------------------------------------------------------------------------
def test_scattered_set_high_spread():
    pka = 8.9
    records = [crippen(6.0), swissadme(1.0), opera_logd(1.0)]

    res = one(records, pka=pka)

    assert res.n_lenses == 3
    assert res.spread_flag == "high"
    assert res.trust is False
    assert res.recommend_measured_anchor is True
    assert res.spread_range > 1.0


# --------------------------------------------------------------------------------------------------
# logP lenses are CONVERTED before entering the consensus (F-12).
# --------------------------------------------------------------------------------------------------
def test_logp_lenses_are_converted_before_consensus():
    pka = 8.9
    res = one([crippen(2.5), swissadme(2.6), opera_logd(1.0)], pka=pka)

    by_model = {l.model: l for l in res.lenses}
    crip = by_model[ModelName.rdkit_crippen]
    swiss = by_model[ModelName.swissadme]
    op = by_model[ModelName.opera]

    # logP lenses: raw_kind logP, converted True, logd == the H-H value (NOT the raw logP)
    assert crip.raw_kind == "logP" and crip.converted is True
    assert crip.logd == pytest.approx(logp_to_logd(2.5, pka, kind="base"))
    assert crip.logd != pytest.approx(crip.raw_value)
    assert swiss.raw_kind == "logP" and swiss.converted is True
    # native logD lens: passes through, carries OPERA's Conf_index_LogD
    assert op.raw_kind == "logD" and op.converted is False
    assert op.logd == pytest.approx(1.0)
    assert op.confidence == pytest.approx(0.74)


# --------------------------------------------------------------------------------------------------
# No shared pKa: raw logP lenses are kept OUT of the logD consensus (never averaged raw), F-12.
# --------------------------------------------------------------------------------------------------
def test_no_pka_excludes_logp_lenses_from_consensus():
    # rdkit (logP) + opera (native logD), and NO pKa anywhere.
    res = one([crippen(4.0), opera_logd(1.05)])

    assert res.pka_used is None
    # only the native logD lens reaches the axis
    assert res.n_lenses == 1
    assert res.consensus == pytest.approx(1.05)
    crip = next(l for l in res.lenses if l.model == ModelName.rdkit_crippen)
    assert crip.converted is False and crip.logd is None
    assert any("kept OUT of the logD consensus" in n for n in res.notes)


def test_no_lens_at_all_yields_undefined_consensus():
    # only logP lenses, no pKa -> nothing reaches the logD axis
    res = one([crippen(4.0), swissadme(3.5)])
    assert res.consensus is None
    assert res.n_lenses == 0
    assert res.spread_flag == "high"
    assert res.recommend_measured_anchor is True


# --------------------------------------------------------------------------------------------------
# Shared pKa placeholder is read from OPERA pKa_b (F-13) when not injected.
# --------------------------------------------------------------------------------------------------
def test_pka_resolved_from_opera_pka_b_record():
    pka = 8.9
    records = [crippen(2.5), opera_pka_b(pka), opera_logd(1.0)]

    res = one(records)  # no injected pka

    assert res.pka_used == pytest.approx(pka)
    assert res.pka_source == "opera:pKa_b"
    assert res.pka_kind == "base"
    crip = next(l for l in res.lenses if l.model == ModelName.rdkit_crippen)
    assert crip.converted is True
    assert crip.logd == pytest.approx(logp_to_logd(2.5, pka, kind="base"))


def test_injected_pka_overrides_records():
    records = [crippen(2.5), opera_pka_b(5.0)]
    res = one(records, pka=8.9)
    assert res.pka_used == pytest.approx(8.9)
    assert res.pka_source == "injected"


# --------------------------------------------------------------------------------------------------
# A consensus far from measured logD ~= 1 lowers trust even when spread is low (task t40 anchor rule).
# --------------------------------------------------------------------------------------------------
def test_consensus_far_from_anchor_raises_flag_even_if_converged():
    # low basic pKa -> conversion is negligible, so the logP lenses stay high and tightly clustered.
    pka = 3.0
    records = [crippen(5.0), swissadme(5.05), opera_logd(5.0)]

    res = one(records, pka=pka)

    assert res.spread_flag == "low"  # they converge...
    assert res.trust is False        # ...but far from the measured anchor
    assert res.recommend_measured_anchor is True
    assert abs(res.consensus - MEASURED_LOGD_ANCHOR) > ANCHOR_TOLERANCE
    assert any("from measured logD" in r for r in res.flag_reasons)


def test_deferred_boundaries_are_flagged():
    res = one([opera_logd(1.05)])
    joined = " ".join(res.deferred)
    assert "F-13" in joined and "F-16" in joined


# --------------------------------------------------------------------------------------------------
# The shared contract: aggregate() takes {mol_id: records} and returns one result per molecule.
# --------------------------------------------------------------------------------------------------
def test_batch_scores_each_molecule_independently():
    res = aggregate({"A": [opera_logd(1.0)], "B": [opera_logd(2.0)]}, pka=8.9)
    assert res.n_molecules == 2
    assert [m.mol_id for m in res.molecules] == ["A", "B"]
    assert res.molecules[0].consensus == pytest.approx(1.0)
    assert res.molecules[1].consensus == pytest.approx(2.0)
