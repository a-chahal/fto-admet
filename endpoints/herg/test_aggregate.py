"""Tests for the hERG gate aggregator (task t52): harmonization shape + PROVISIONAL flag + DEFERRED marker.

Synthetic ``OutputRecord``-shaped inputs only (laptop, core env - no box, no GPU). They pin down what
this endpoint must guarantee (task t52, IO_SPEC §2 "hERG (GATE)" / §3 F-1, CLAUDE.md §4/§4a):

- HARMONIZATION SHAPE: each contributing read maps onto the common P(block) shape - BayeshERG /
  CardioTox net / ADMET-AI as identity probabilities (BayeshERG carrying alea/epis); CardioGenAI's
  "hERG pIC50" (literal space) through the PLACEHOLDER F-1 logistic.
- DEFERRED: the flag is PROVISIONAL/UNCALIBRATED - every threshold is a PLACEHOLDER_* constant, the
  result is marked ``deferred``, and the module carries an explicit DEFERRED marker.
"""

from __future__ import annotations

from pathlib import Path

from core.models import Endpoint, ModelName
from endpoints.herg.aggregate import (
    ADMET_AI_HERG_KEY,
    BAYESHERG_PBLOCK_KEY,
    CARDIOGENAI_PIC50_KEY,
    CARDIOTOX_PBLOCK_KEY,
    PLACEHOLDER_HIGH_MEAN,
    PLACEHOLDER_MEDIUM_MEAN,
    PLACEHOLDER_PIC50_CENTER,
    PLACEHOLDER_SPECIALIST_ALARM,
    HergFlag,
    ReadKind,
    _placeholder_pic50_to_pblock,
    aggregate,
)

PROV = {"model": "test"}


# --------------------------------------------------------------------------------------------------
# Synthetic record builders (one per contributing model), keyed exactly as each adapter writes.
# --------------------------------------------------------------------------------------------------
def bayesherg_rec(p_block, alea=None, epis=None) -> dict:
    return {
        "model": ModelName.bayesherg,
        "endpoint_values": {BAYESHERG_PBLOCK_KEY: p_block},
        "uncertainty": {"aleatoric": alea, "epistemic": epis},
        "raw": {},
        "provenance": PROV,
    }


def cardiotox_rec(p_block) -> dict:
    return {
        "model": ModelName.cardiotox_net,
        "endpoint_values": {CARDIOTOX_PBLOCK_KEY: p_block},
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }


def admet_ai_rec(p_block) -> dict:
    return {
        "model": ModelName.admet_ai,
        "endpoint_values": {ADMET_AI_HERG_KEY: p_block},
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }


def cardiogenai_rec(pic50) -> dict:
    return {
        "model": ModelName.cardiogenai,
        "endpoint_values": {CARDIOGENAI_PIC50_KEY: pic50},
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }


def _read_for(mol, model) -> object:
    matches = [r for r in mol.reads if r.model == model]
    assert len(matches) == 1, f"expected exactly one read for {model}, got {len(matches)}"
    return matches[0]


# --------------------------------------------------------------------------------------------------
# Harmonization shape: each read lands on the common shape correctly.
# --------------------------------------------------------------------------------------------------
def test_bayesherg_identity_pblock_and_carries_alea_epis():
    mol = aggregate({"m": [bayesherg_rec(0.42, alea=0.11, epis=0.07)]}).molecules[0]
    r = _read_for(mol, ModelName.bayesherg)
    assert r.kind is ReadKind.probability
    assert r.p_block == 0.42
    assert r.source_field == BAYESHERG_PBLOCK_KEY
    assert r.is_specialist is True
    assert r.aleatoric == 0.11 and r.epistemic == 0.07


def test_cardiotox_and_admet_ai_identity_pblock():
    mol = aggregate({"m": [cardiotox_rec(0.6), admet_ai_rec(0.3)]}).molecules[0]
    ct = _read_for(mol, ModelName.cardiotox_net)
    ai = _read_for(mol, ModelName.admet_ai)
    assert ct.kind is ReadKind.probability and ct.p_block == 0.6
    assert ai.kind is ReadKind.probability and ai.p_block == 0.3
    # ADMET-AI is a generalist pre-screen, not a specialist that can raise a solo alarm.
    assert ai.is_specialist is False


def test_cardiogenai_pic50_through_placeholder_logistic():
    """CardioGenAI's "hERG pIC50" (literal space) maps through the PLACEHOLDER F-1 logistic, not identity."""
    mol = aggregate({"m": [cardiogenai_rec(PLACEHOLDER_PIC50_CENTER)]}).molecules[0]
    r = _read_for(mol, ModelName.cardiogenai)
    assert r.kind is ReadKind.probability
    assert r.source_field == CARDIOGENAI_PIC50_KEY
    # anchor: pIC50 = 5.0 non-blocker cutoff -> exactly 0.5
    assert abs(r.p_block - 0.5) < 1e-9


def test_placeholder_pic50_mapping_direction_and_anchor():
    assert abs(_placeholder_pic50_to_pblock(5.0) - 0.5) < 1e-9
    # higher pIC50 = stronger block = higher P(block); lower = lower.
    assert _placeholder_pic50_to_pblock(8.0) > 0.5
    assert _placeholder_pic50_to_pblock(2.0) < 0.5


def test_ensemble_mean_and_spread_over_probability_reads():
    recs = [bayesherg_rec(0.2), cardiotox_rec(0.6), admet_ai_rec(0.4)]
    mol = aggregate({"m": recs}).molecules[0]
    assert mol.n_probability_reads == 3
    assert abs(mol.ensemble_mean - 0.4) < 1e-9
    assert abs(mol.ensemble_spread - 0.4) < 1e-9  # 0.6 - 0.2


# --------------------------------------------------------------------------------------------------
# Provisional flag: sensitivity-leaning, all thresholds are placeholders.
# --------------------------------------------------------------------------------------------------
def test_flag_high_on_mean_at_threshold():
    mol = aggregate({"m": [bayesherg_rec(0.5), cardiotox_rec(0.5)]}).molecules[0]
    assert mol.ensemble_mean >= PLACEHOLDER_HIGH_MEAN
    assert mol.provisional_flag is HergFlag.HIGH


def test_flag_high_on_single_specialist_alarm_even_if_mean_low():
    """A single specialist >= 0.7 trips HIGH even when the mean is low (sensitivity-leaning)."""
    recs = [bayesherg_rec(0.9), admet_ai_rec(0.05)]  # mean = 0.475 < 0.5 but specialist alarm fires
    mol = aggregate({"m": recs}).molecules[0]
    assert mol.ensemble_mean < PLACEHOLDER_HIGH_MEAN
    assert any(r.is_specialist and r.p_block >= PLACEHOLDER_SPECIALIST_ALARM for r in mol.reads)
    assert mol.provisional_flag is HergFlag.HIGH


def test_flag_medium_on_mid_mean():
    mol = aggregate({"m": [bayesherg_rec(0.35), cardiotox_rec(0.35)]}).molecules[0]
    assert PLACEHOLDER_MEDIUM_MEAN <= mol.ensemble_mean < PLACEHOLDER_HIGH_MEAN
    assert mol.provisional_flag is HergFlag.MEDIUM


def test_flag_low_on_low_mean_no_alarm():
    mol = aggregate({"m": [bayesherg_rec(0.1), cardiotox_rec(0.15)]}).molecules[0]
    assert mol.ensemble_mean < PLACEHOLDER_MEDIUM_MEAN
    assert mol.provisional_flag is HergFlag.LOW


def test_spread_biases_low_up_to_medium_toward_caution():
    """Wide disagreement (spread) biases one level UP even when the mean would read LOW."""
    # mean = 0.25 (LOW band) but spread 0.5 - 0.0 = 0.5 >= 0.4 caution threshold -> bump to MEDIUM.
    recs = [bayesherg_rec(0.0), cardiotox_rec(0.5)]
    mol = aggregate({"m": recs}).molecules[0]
    assert mol.ensemble_mean < PLACEHOLDER_MEDIUM_MEAN
    assert mol.ensemble_spread >= 0.4
    assert mol.provisional_flag is HergFlag.MEDIUM


def test_empty_bundle_is_unknown_not_a_fabricated_verdict():
    mol = aggregate({"m": []}).molecules[0]
    assert mol.provisional_flag is HergFlag.UNKNOWN
    assert mol.ensemble_mean is None


# --------------------------------------------------------------------------------------------------
# DEFERRED contract: the endpoint RUNS but the calibrated gate is explicitly deferred.
# --------------------------------------------------------------------------------------------------
def test_result_is_marked_deferred_and_is_a_gate_but_uncalibrated():
    res = aggregate({"m": [bayesherg_rec(0.5)]})
    assert res.endpoint is Endpoint.herg
    assert res.deferred is True
    mol = res.molecules[0]
    assert mol.is_gate is True        # hERG IS the primary gate,
    assert mol.calibrated is False    # but this specific call is not the calibrated one.


def test_flag_reasons_label_the_call_provisional():
    mol = aggregate({"m": [bayesherg_rec(0.9)]}).molecules[0]
    assert any("PROVISIONAL" in r or "UNCALIBRATED" in r for r in mol.flag_reasons)


def test_module_carries_explicit_deferred_marker():
    """The gate verifier requires an explicit DEFERRED marker in aggregate.py."""
    src = (Path(__file__).parent / "aggregate.py").read_text()
    assert "DEFERRED" in src
    assert "PLACEHOLDER_" in src


def test_multiple_molecules_stay_independent():
    res = aggregate(
        {
            "safe": [bayesherg_rec(0.05), cardiotox_rec(0.1)],
            "risky": [bayesherg_rec(0.95), cardiotox_rec(0.9)],
        }
    )
    assert res.n_molecules == 2
    by_id = {m.mol_id: m for m in res.molecules}
    assert by_id["safe"].provisional_flag is HergFlag.LOW
    assert by_id["risky"].provisional_flag is HergFlag.HIGH
