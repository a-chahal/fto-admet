"""Tests for the triage aggregator (task t51): the funnel-entry generalist flag table. FLAGS ONLY.

Synthetic ``OutputRecord``-shaped inputs only (laptop, core env - no box, no GPU). They exercise the
guarantees this endpoint exists to provide (task t51, IO_SPEC §1 #1-#3, SETTLED §7):

- the generalist (ADMET-AI v2) is summarized into a per-property flag table, keyed by canonical property;
- uncertainty = CROSS-MODEL SPREAD (dormant with one generalist): the spread flag fires only when
  two generalists share a property and diverge;
- a SINGLE generalist is never authority: a lone read is marked ``single_source``, not "ok";
- FLAGS ONLY - there is no gate/kill anywhere (every ``is_gate`` is False; no promote/reject verdict);
- ADMET-AI's excluded VDss/half-life heads stay absent and are never resurrected (F-17);
- the accepted input shapes normalize the same way; missing generalists degrade gracefully.
"""

from __future__ import annotations

from core.models import Endpoint, ModelName
from endpoints.triage.aggregate import (
    CONF_SINGLE,
    EXCLUDED_R2_NEGATIVE,
    aggregate,
)

PROV = {"model": "test"}


def admet_ai_rec(**heads) -> dict:
    """An ADMET-AI record whose endpoint_values are the given canonical heads (probabilities/regressions)."""
    return {
        "model": ModelName.admet_ai,
        "endpoint_values": dict(heads),
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }


def _prop(mol, name):
    """Fetch a single PropertyFlag row by canonical name."""
    for p in mol.properties:
        if p.property == name:
            return p
    raise AssertionError(f"property {name!r} not in flag table: {[p.property for p in mol.properties]}")


# --------------------------------------------------------------------------------------------------
# Shape / endpoint identity.
# --------------------------------------------------------------------------------------------------
def test_endpoint_identity_and_flag_table_shape():
    res = aggregate({"m": [admet_ai_rec(hERG=0.2, BBB_Martins=0.9)]})
    assert res.endpoint == Endpoint.triage
    assert res.n_molecules == 1
    mol = res.molecules[0]
    assert mol.present is True
    assert {p.property for p in mol.properties} == {"hERG", "BBB_Martins"}
    assert mol.n_properties == 2


# --------------------------------------------------------------------------------------------------
# Single generalist (with admetlab3 removed, this is every property's state). The cross-model spread
# machinery is dormant until a second independent generalist is added.
# --------------------------------------------------------------------------------------------------
def test_single_generalist_is_never_authority():
    """A property reported by exactly one generalist is single_source (not cross-checked), never ok/low."""
    hERG = _prop(aggregate({"m": [admet_ai_rec(hERG=0.05)]}).molecules[0], "hERG")
    assert hERG.n_models == 1
    assert hERG.divergent is False
    assert hERG.spread is None
    assert hERG.confidence == CONF_SINGLE


# --------------------------------------------------------------------------------------------------
# FLAGS ONLY - no kill / gate anywhere.
# --------------------------------------------------------------------------------------------------
def test_flags_only_never_a_gate():
    """Every property flag is explicitly non-gating; the result carries no promote/reject/pass-fail field."""
    res = aggregate({"m": [admet_ai_rec(hERG=0.99, AMES=0.99)]})
    mol = res.molecules[0]
    assert all(p.is_gate is False for p in mol.properties)
    # The result schema deliberately has no kill/verdict/promote field.
    fields = set(type(res).model_fields)
    assert not (fields & {"kill", "verdict", "promote", "reject", "pass_", "gate", "advance"})


# --------------------------------------------------------------------------------------------------
# Exclusions (F-17): VDss / half-life never appear.
# --------------------------------------------------------------------------------------------------
def test_excluded_heads_stay_absent_even_if_a_stray_record_carries_them():
    """A guard against resurrection: even if a record wrongly carried VDss/half-life, triage drops them."""
    rec = admet_ai_rec(hERG=0.3, VDss_Lombardo=2.0, Half_Life_Obach=5.0)
    mol = aggregate({"m": [rec]}).molecules[0]
    names = {p.property for p in mol.properties}
    assert names == {"hERG"}
    assert not (names & EXCLUDED_R2_NEGATIVE)


# --------------------------------------------------------------------------------------------------
# Input-shape normalization + graceful degradation.
# --------------------------------------------------------------------------------------------------
def test_input_shapes_normalize_the_same():
    recs = [admet_ai_rec(hERG=0.1)]
    as_map = aggregate({"FTO-43": recs}).molecules[0]
    as_pairs = aggregate([("FTO-43", recs)]).molecules[0]
    as_dicts = aggregate([{"mol_id": "FTO-43", "records": recs}]).molecules[0]
    as_bare = aggregate([recs]).molecules[0]
    assert as_map.mol_id == as_pairs.mol_id == as_dicts.mol_id == "FTO-43"
    assert as_bare.mol_id == "mol_0"
    for m in (as_map, as_pairs, as_dicts, as_bare):
        assert _prop(m, "hERG").confidence == CONF_SINGLE


def test_no_generalist_reads_degrades_gracefully():
    """A molecule with no generalist record is present=False with an empty table, not an error."""
    other = {
        "model": ModelName.bayesherg,
        "endpoint_values": {"score": 0.5},
        "uncertainty": None,
        "raw": {},
        "provenance": PROV,
    }
    mol = aggregate({"m": [other]}).molecules[0]
    assert mol.present is False
    assert mol.properties == []
    assert mol.n_properties == 0
