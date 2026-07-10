"""Tests for the lipophilicity aggregator: one ``logD`` feature, score = mean, uncertainty = std.

Synthetic ``OutputRecord``-shaped inputs (laptop, core env - no box, no GPU). They pin the science that
must survive the shape change:
- native logD lenses (OPERA, ADMET-AI) pass through unchanged;
- logP lenses (RDKit Crippen, SwissADME) convert to logD via Henderson-Hasselbalch with the shared pKa
  (F-12) BEFORE joining the score; native logP kept in ``raw``;
- a logP lens with no shared pKa is carried with ``value=None`` (excluded, never averaged raw);
- score = equally-weighted mean of the harmonized logD values, uncertainty = std over them.
"""

from __future__ import annotations

import math

from core.models import Endpoint, ModelName
from endpoints.lipophilicity.aggregate import FEATURE, aggregate, logp_to_logd

PROV = {"model": "test"}


def opera(logd: float | None = None, *, pka_b: float | None = None, conf: float | None = None) -> dict:
    ev: dict = {}
    if logd is not None:
        ev["LogD"] = logd
    if pka_b is not None:
        ev["pKa_b"] = pka_b
    unc = {"conf_index": conf} if conf is not None else None
    return {"model": ModelName.opera, "endpoint_values": ev, "uncertainty": unc, "raw": {}, "provenance": PROV}


def admet_ai(logd: float) -> dict:
    return {"model": ModelName.admet_ai, "endpoint_values": {"Lipophilicity_AstraZeneca": logd},
            "uncertainty": None, "raw": {}, "provenance": PROV}


def crippen(logp: float) -> dict:
    return {"model": ModelName.rdkit_crippen, "endpoint_values": {"logP_crippen": logp},
            "uncertainty": None, "raw": {}, "provenance": PROV}


def swissadme(logp: float) -> dict:
    return {"model": ModelName.swissadme, "endpoint_values": {"Consensus_logP": logp},
            "uncertainty": None, "raw": {}, "provenance": PROV}


def _feature(mol):
    assert len(mol.features) == 1
    f = mol.features[0]
    assert f.feature == FEATURE
    return f


def _src(feature, model):
    return next(s for s in feature.sources if s.model == model)


# -------------------------------------------------------------------------- native logD passthrough
def test_native_logd_lenses_pass_through():
    f = _feature(aggregate({"m": [opera(1.17, conf=0.66), admet_ai(0.82)]}).molecules[0])
    o, a = _src(f, "opera"), _src(f, "admet_ai")
    assert o.value == 1.17 and o.raw is None       # native: no transform, raw stays None
    assert a.value == 0.82
    assert "conf_index=0.66" in o.note


# -------------------------------------------------------------------------- logP -> logD conversion (F-12)
def test_logp_lens_converts_to_logd_with_shared_pka_and_keeps_raw():
    # OPERA supplies the shared pKa_b; Crippen's raw logP is corrected to logD before entering the score.
    f = _feature(aggregate({"m": [opera(pka_b=9.56), crippen(2.5775)]}).molecules[0])
    c = _src(f, "rdkit_crippen")
    expected = logp_to_logd(2.5775, 9.56, ph=7.4, kind="base")
    assert math.isclose(c.value, expected)
    assert (c.raw, c.raw_unit) == (2.5775, "logP")   # native logP retained
    assert math.isclose(expected, 0.4146, abs_tol=1e-3)  # the real propranolol number


def test_injected_pka_overrides_and_converts_swissadme():
    f = _feature(aggregate({"m": [swissadme(3.0)]}, pka=9.0).molecules[0])
    s = _src(f, "swissadme")
    assert math.isclose(s.value, logp_to_logd(3.0, 9.0))


def test_logp_lens_without_pka_is_excluded_but_raw_kept():
    # No OPERA pKa and no injection: the logP cannot be harmonized, so value=None (out of the score).
    f = _feature(aggregate({"m": [crippen(2.58)]}).molecules[0])
    c = _src(f, "rdkit_crippen")
    assert c.value is None and c.raw == 2.58
    assert f.score is None and f.n_sources == 1   # the read is carried (raw visible), just not scored


# -------------------------------------------------------------------------- score = mean, uncertainty = std
def test_score_is_mean_and_uncertainty_is_std_over_logd():
    f = _feature(aggregate({"m": [opera(1.17), admet_ai(0.82)]}).molecules[0])
    vals = [1.17, 0.82]
    mean = sum(vals) / 2
    var = sum((x - mean) ** 2 for x in vals) / 2
    assert f.n_sources == 2
    assert math.isclose(f.score, mean)
    assert math.isclose(f.uncertainty, math.sqrt(var))


def test_convergent_lenses_lower_uncertainty_than_divergent():
    tight = _feature(aggregate({"m": [opera(1.0), admet_ai(1.05)]}).molecules[0])
    wide = _feature(aggregate({"m": [opera(1.0), admet_ai(4.0)]}).molecules[0])
    assert tight.uncertainty < wide.uncertainty


# -------------------------------------------------------------------------- subsets / fallbacks
def test_single_source_has_score_but_no_uncertainty():
    f = _feature(aggregate({"m": [admet_ai(0.82)]}).molecules[0])
    assert f.score == 0.82 and f.uncertainty is None and f.n_sources == 1


def test_no_lipophilicity_source_yields_null_score():
    rec = {"model": ModelName.bayesherg, "endpoint_values": {"P_block": 0.5},
           "uncertainty": None, "raw": {}, "provenance": PROV}
    f = _feature(aggregate({"m": [rec]}).molecules[0])
    assert f.score is None and f.uncertainty is None and f.n_sources == 0


# -------------------------------------------------------------------------- shape / plumbing
def test_endpoint_identity_and_uniform_shape():
    res = aggregate({"m": [admet_ai(0.82)]})
    assert res.endpoint == Endpoint.lipophilicity and res.n_molecules == 1
    mol = res.molecules[0]
    assert mol.endpoint == Endpoint.lipophilicity and mol.mol_id == "m"
    assert set(type(mol).model_fields) == {"endpoint", "mol_id", "features"}
    assert set(type(mol.features[0]).model_fields) == {"feature", "score", "uncertainty", "unit", "n_sources", "sources"}


def test_full_four_lens_ensemble():
    recs = [opera(1.17, pka_b=9.56), admet_ai(0.82), crippen(2.5775), swissadme(2.98)]
    f = _feature(aggregate({"m": recs}).molecules[0])
    assert f.n_sources == 4               # all four reached the logD axis (pKa available)
    assert f.score is not None and f.uncertainty is not None
