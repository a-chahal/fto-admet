"""Tests for the lipophilicity aggregator: one ``logD`` feature, fused across the harmonized lenses.

Synthetic ``OutputRecord``-shaped inputs (laptop, core env - no box, no GPU). They pin the science that
must survive the shape change:
- native logD lenses (OPERA, ADMET-AI) pass through unchanged (harmonized ``read`` == native, no ``raw``);
- logP lenses (RDKit Crippen, SwissADME) convert to logD via Henderson-Hasselbalch with the shared pKa
  (F-12) BEFORE joining the score; native logP kept in ``raw``;
- a logP lens with no shared pKa is carried with ``value=None`` (excluded from ``reads``, raw still visible);
- each model's native AD / confidence signals land in ``uncertainty`` (OPERA conf_index/AD, SwissADME spread).

Output shape (per feature): score, unit, interval[low,high], reads{model:harmonized}, raw{model:native},
uncertainty{model_type:value}. Exact fused values are pinned in tests/test_fusion.py.
"""

from __future__ import annotations

import math

from core.models import Endpoint, ModelName
from endpoints.lipophilicity.aggregate import FEATURE, aggregate, logp_to_logd

PROV = {"model": "test"}


def opera(logd: float | None = None, *, pka_b: float | None = None, conf: float | None = None,
          ad_in_domain: bool | None = None, ad_index: float | None = None) -> dict:
    ev: dict = {}
    if logd is not None:
        ev["LogD"] = logd
    if pka_b is not None:
        ev["pKa_b"] = pka_b
    unc: dict | None = None
    if conf is not None or ad_in_domain is not None or ad_index is not None:
        unc = {"conf_index": conf, "ad_in_domain": ad_in_domain, "ad_index": ad_index}
    return {"model": ModelName.opera, "endpoint_values": ev, "uncertainty": unc, "raw": {}, "provenance": PROV}


def admet_ai(logd: float) -> dict:
    return {"model": ModelName.admet_ai, "endpoint_values": {"Lipophilicity_AstraZeneca": logd},
            "uncertainty": None, "raw": {}, "provenance": PROV}


def crippen(logp: float) -> dict:
    return {"model": ModelName.rdkit_crippen, "endpoint_values": {"logP_crippen": logp},
            "uncertainty": None, "raw": {}, "provenance": PROV}


def swissadme(logp: float, *, spread_std: float | None = None) -> dict:
    unc = {"extra": {"spread_std": spread_std}} if spread_std is not None else None
    return {"model": ModelName.swissadme, "endpoint_values": {"Consensus_logP": logp},
            "uncertainty": unc, "raw": {}, "provenance": PROV}


def _feature(mol):
    assert len(mol.features) == 1
    f = mol.features[0]
    assert f.feature == FEATURE
    return f


# -------------------------------------------------------------------------- native logD passthrough
def test_native_logd_lenses_pass_through():
    f = _feature(aggregate({"m": [opera(1.17, conf=0.66), admet_ai(0.82)]}).molecules[0])
    assert f.reads == {"opera": 1.17, "admet_ai": 0.82}   # harmonized reads preserved
    assert f.raw == {}                                    # native logD: no transform, nothing in raw
    assert f.uncertainty["opera_conf_index"] == 0.66      # OPERA native confidence surfaced


def test_opera_ad_flags_land_in_uncertainty():
    f = _feature(aggregate({"m": [opera(1.17, conf=0.6, ad_in_domain=True, ad_index=0.9)]}).molecules[0])
    assert f.uncertainty["opera_conf_index"] == 0.6
    assert f.uncertainty["opera_ad_in_domain"] is True
    assert f.uncertainty["opera_ad_index"] == 0.9


# -------------------------------------------------------------------------- logP -> logD conversion (F-12)
def test_logp_lens_converts_to_logd_with_shared_pka_and_keeps_raw():
    # OPERA supplies the shared pKa_b; Crippen's raw logP is corrected to logD before entering the score.
    f = _feature(aggregate({"m": [opera(pka_b=9.56), crippen(2.5775)]}).molecules[0])
    expected = logp_to_logd(2.5775, 9.56, ph=7.4, kind="base")
    assert math.isclose(f.reads["rdkit_crippen"], expected)   # harmonized logD is the read
    assert f.raw["rdkit_crippen"] == 2.5775                   # native logP retained
    assert math.isclose(expected, 0.4146, abs_tol=1e-3)       # the real propranolol number


def test_injected_pka_overrides_and_converts_swissadme():
    f = _feature(aggregate({"m": [swissadme(3.0)]}, pka=9.0).molecules[0])
    assert math.isclose(f.reads["swissadme"], logp_to_logd(3.0, 9.0))
    assert f.raw["swissadme"] == 3.0


def test_swissadme_spread_std_lands_in_uncertainty():
    f = _feature(aggregate({"m": [swissadme(3.0, spread_std=0.42)]}, pka=9.0).molecules[0])
    assert f.uncertainty["swissadme_spread_std"] == 0.42


def test_logp_lens_without_pka_is_excluded_but_raw_kept():
    # No OPERA pKa and no injection: the logP cannot be harmonized, so value=None (out of the score).
    f = _feature(aggregate({"m": [crippen(2.58)]}).molecules[0])
    assert "rdkit_crippen" not in f.reads   # no harmonized read (excluded from the score)
    assert f.raw["rdkit_crippen"] == 2.58   # native logP still visible
    assert f.score is None and f.interval is None


# ------------------------------------------------------------- trained spec: sources gathered, score exists
def test_lenses_gathered_and_scored_via_trained_spec():
    # The trained logD spec calibrates admet_ai + crippen + swissadme (opera was dropped from the spec, so
    # it is carried as a read but not weighted). Exact fused value is pinned in tests/test_fusion.py; here
    # assert both reads are gathered on the logD axis and a calibrated score + interval are produced.
    f = _feature(aggregate({"m": [opera(1.17), admet_ai(0.82)]}).molecules[0])
    assert set(f.reads) == {"opera", "admet_ai"}
    assert f.score is not None and f.interval is not None


def test_convergent_and_divergent_both_yield_score_and_interval():
    # Under the trained spec the interval is the spec's conformal width (opera is not a spec source, so it
    # does not move the disagreement); both mixes still yield a calibrated score + interval.
    tight = _feature(aggregate({"m": [opera(1.0), admet_ai(1.05)]}).molecules[0])
    wide = _feature(aggregate({"m": [opera(1.0), admet_ai(4.0)]}).molecules[0])
    for f in (tight, wide):
        assert f.score is not None and f.interval is not None


# -------------------------------------------------------------------------- subsets / fallbacks
def test_single_source_yields_calibrated_score():
    # trained spec: the single admet_ai read is calibrated (not the raw 0.82 passthrough).
    f = _feature(aggregate({"m": [admet_ai(0.82)]}).molecules[0])
    assert f.score is not None and f.interval is not None and len(f.reads) == 1


def test_no_lipophilicity_source_yields_null_score():
    rec = {"model": ModelName.bayesherg, "endpoint_values": {"P_block": 0.5},
           "uncertainty": None, "raw": {}, "provenance": PROV}
    f = _feature(aggregate({"m": [rec]}).molecules[0])
    assert f.score is None and f.interval is None and f.reads == {}


# -------------------------------------------------------------------------- shape / plumbing
def test_endpoint_identity_and_uniform_shape():
    res = aggregate({"m": [admet_ai(0.82)]})
    assert res.endpoint == Endpoint.lipophilicity and res.n_molecules == 1
    mol = res.molecules[0]
    assert mol.endpoint == Endpoint.lipophilicity and mol.mol_id == "m"
    assert set(type(mol).model_fields) == {"endpoint", "mol_id", "features"}
    assert set(type(mol.features[0]).model_fields) == {
        "feature", "score", "unit", "interval", "reads", "raw", "uncertainty"}


def test_full_four_lens_ensemble():
    recs = [opera(1.17, pka_b=9.56), admet_ai(0.82), crippen(2.5775), swissadme(2.98)]
    f = _feature(aggregate({"m": recs}).molecules[0])
    assert set(f.reads) == {"opera", "admet_ai", "rdkit_crippen", "swissadme"}  # all four reached the axis
    assert f.score is not None and f.interval is not None
