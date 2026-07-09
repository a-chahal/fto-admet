"""Unit tests for core.models (the Endpoint / ModelName primary-key enums).

These enums are the contract every later module keys off (CLAUDE.md §2), so the tests pin the exact
membership, counts, values, and string behavior, and assert the dropped upstreams stay absent. Gate:
``pytest tests/test_models.py``. Laptop / core env, no box, no GPU.
"""

from enum import StrEnum

from core.models import Endpoint, ModelName

EXPECTED_ENDPOINTS = {
    "triage",
    "herg",
    "metabolism",
    "clearance",
    "distribution",
    "ppb",
    "solubility",
    "lipophilicity",
    "permeability",
    "structural_alerts",
    "synthesizability",
    "toxicity",
    "druglikeness",
}

EXPECTED_MODELS = {
    "admet_ai",
    "bayesherg",
    "cardiotox_net",
    "ctoxpred2",
    "cardiogenai",
    "smartcyp",
    "fame3r",
    "watanabe_renal",
    "pksmart",
    "pbpk",
    "bbb_score",
    "boiled_egg",
    "cns_mpo",
    "pgp",
    "watanabe_pgp_brain",
    "ochem_ppb",
    "sfi",
    "rdkit_crippen",
    "opera",
    "swissadme",
    "pains_brenk",
    "sascore",
    "rascore",
    "aizynthfinder",
    "toxicophores",
    "protox",
    "lipinski_veber_qed",
}

# Dropped or replaced upstreams that must never reappear (CLAUDE.md §4).
DROPPED = {"deephit", "spielvogel", "cardiodpi", "fame3"}


def test_both_are_str_enums():
    assert issubclass(Endpoint, StrEnum)
    assert issubclass(ModelName, StrEnum)


def test_endpoint_count_is_thirteen():
    assert len(Endpoint) == 13


def test_model_count_is_twentyseven():
    assert len(ModelName) == 27


def test_endpoint_membership_is_exact():
    assert {e.value for e in Endpoint} == EXPECTED_ENDPOINTS
    assert {e.name for e in Endpoint} == EXPECTED_ENDPOINTS


def test_model_membership_is_exact():
    assert {m.value for m in ModelName} == EXPECTED_MODELS
    assert {m.name for m in ModelName} == EXPECTED_MODELS


def test_each_value_equals_lowercased_name():
    for e in Endpoint:
        assert e.value == e.name.lower()
    for m in ModelName:
        assert m.value == m.name.lower()


def test_no_duplicate_values():
    # StrEnum aliases would collapse to a single canonical member; distinct-value check catches that.
    assert len({e.value for e in Endpoint}) == len(Endpoint)
    assert len({m.value for m in ModelName}) == len(ModelName)


def test_lookup_by_string_returns_the_member():
    assert ModelName("pksmart") is ModelName.pksmart
    assert Endpoint("herg") is Endpoint.herg


def test_member_compares_equal_to_its_string():
    assert ModelName.pksmart == "pksmart"
    assert Endpoint.herg == "herg"


def test_dropped_names_are_absent():
    values = {m.value for m in ModelName}
    names = {m.name for m in ModelName}
    for dropped in DROPPED:
        assert dropped not in values
        assert dropped not in names


def test_permeability_is_endpoint_only_no_model():
    assert "permeability" in {e.value for e in Endpoint}
    assert "permeability" not in {m.value for m in ModelName}
