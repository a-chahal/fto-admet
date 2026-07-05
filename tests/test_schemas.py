"""Unit tests for core.schemas (the shared pydantic I/O envelope).

These pin the contract the dispatcher validates against before/after every model run (CLAUDE.md §2/§3):
the input record rejects empty SMILES, the uncertainty envelope is fully optional (reserve-not-decide),
and an output record round-trips through serialize -> parse unchanged, including a native fold-error and
a per-atom table carried verbatim in ``raw``. Gate: ``pytest tests/test_schemas.py``. Laptop / core env,
no box, no GPU.
"""

import pytest
from pydantic import ValidationError

from core.models import ModelName
from core.schemas import (
    InputRecord,
    OutputRecord,
    Uncertainty,
    validate_input,
    validate_output,
)

# FTO-43 lead (PubChem CID 164886650) as a stand-in canonical SMILES fixture.
FTO43_SMILES = "O=C(Nc1ccc(cc1)S(=O)(=O)N)c1cc2ccccc2[nH]1"


# --- InputRecord -----------------------------------------------------------------------------------


def test_input_accepts_canonical_smiles_only():
    rec = InputRecord(smiles=FTO43_SMILES)
    assert rec.smiles == FTO43_SMILES
    assert rec.mol_id is None
    assert rec.standardized is False
    assert rec.standardizer is None


def test_input_accepts_id_and_standardization_fields():
    rec = InputRecord(
        smiles=FTO43_SMILES,
        mol_id="FTO-43",
        standardized=True,
        standardizer="placeholder-canonical-v0",
    )
    assert rec.mol_id == "FTO-43"
    assert rec.standardized is True
    assert rec.standardizer == "placeholder-canonical-v0"


@pytest.mark.parametrize("bad", ["", "   ", "\t", "\n  \n"])
def test_input_rejects_empty_or_whitespace_smiles(bad):
    with pytest.raises(ValidationError):
        InputRecord(smiles=bad)


def test_input_strips_surrounding_whitespace():
    rec = InputRecord(smiles=f"  {FTO43_SMILES}  ")
    assert rec.smiles == FTO43_SMILES


def test_input_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        InputRecord(smiles=FTO43_SMILES, protonation="dication")


# --- Uncertainty -----------------------------------------------------------------------------------


def test_uncertainty_instantiates_with_zero_fields():
    unc = Uncertainty()
    assert unc.confidence is None
    assert unc.ad_in_domain is None
    assert unc.extra == {}


def test_uncertainty_with_fold_error_interval():
    unc = Uncertainty(fold_error_low=0.4, fold_error_high=2.6)
    assert unc.fold_error_low == 0.4
    assert unc.fold_error_high == 2.6


def test_uncertainty_with_aleatoric_and_epistemic():
    unc = Uncertainty(aleatoric=0.12, epistemic=0.07)
    assert unc.aleatoric == 0.12
    assert unc.epistemic == 0.07


def test_uncertainty_carries_opera_ad_signals():
    # OPERA-style AD flag + AD_index + Conf_index folded into the one envelope.
    unc = Uncertainty(ad_in_domain=True, ad_index=0.83, conf_index=0.71)
    assert unc.ad_in_domain is True
    assert unc.ad_index == 0.83
    assert unc.conf_index == 0.71


def test_uncertainty_extra_holds_model_specific_signals():
    unc = Uncertainty(extra={"admetlab_confidence": "high", "FAME3RScore": 0.42})
    assert unc.extra["admetlab_confidence"] == "high"


@pytest.mark.parametrize("field", ["confidence", "ad_index", "conf_index"])
@pytest.mark.parametrize("bad", [-0.01, 1.01])
def test_uncertainty_bounded_fields_reject_out_of_range(field, bad):
    with pytest.raises(ValidationError):
        Uncertainty(**{field: bad})


def test_uncertainty_forbids_unknown_fields():
    # An unnamed native signal must go through `extra`, not a silently-accepted new attribute.
    with pytest.raises(ValidationError):
        Uncertainty(some_new_signal=0.5)


# --- OutputRecord ----------------------------------------------------------------------------------


def test_output_embeds_optional_uncertainty_defaulting_none():
    out = OutputRecord(model=ModelName.admet_ai, provenance={"upstream_commit": "abc123"})
    assert out.uncertainty is None
    assert out.endpoint_values == {}
    assert out.raw == {}


def test_output_accepts_model_name_by_string():
    out = OutputRecord(model="pksmart", provenance={})
    assert out.model is ModelName.pksmart


def test_output_with_fold_error_round_trips_unchanged():
    out = OutputRecord(
        model=ModelName.pksmart,
        endpoint_values={"human_CL_mL_min_kg": 12.3, "human_fup": 0.08},
        uncertainty=Uncertainty(fold_error_low=0.5, fold_error_high=2.1),
        raw={"human_thalf": 4.2},
        provenance={"upstream_commit": "deadbeef", "env_lock_hash": "PLACEHOLDER"},
    )
    dumped = out.model_dump()
    parsed = OutputRecord.model_validate(dumped)
    assert parsed == out
    assert parsed.uncertainty.fold_error_low == 0.5
    assert parsed.uncertainty.fold_error_high == 2.1

    # JSON-mode round-trip too (enum -> string -> enum).
    parsed_json = OutputRecord.model_validate_json(out.model_dump_json())
    assert parsed_json == out


def test_output_raw_preserves_per_atom_list_without_loss():
    # SMARTCyp / FAME3R site-of-metabolism tables are per-atom; they live in `raw`, not endpoint_values.
    atoms = [
        {"atom": 0, "ranking": 1, "score": 41.2, "som_prob": 0.71},
        {"atom": 3, "ranking": 2, "score": 55.8, "som_prob": 0.42},
    ]
    out = OutputRecord(
        model=ModelName.smartcyp,
        raw={"per_atom": atoms},
        provenance={"upstream_commit": "cafef00d"},
    )
    parsed = OutputRecord.model_validate(out.model_dump())
    assert parsed.raw["per_atom"] == atoms
    assert parsed.endpoint_values == {}


def test_output_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        OutputRecord(model=ModelName.opera, provenance={}, bogus=1)


def test_output_requires_provenance():
    with pytest.raises(ValidationError):
        OutputRecord(model=ModelName.opera)


# --- validate_input / validate_output dispatcher entry points --------------------------------------


def test_validate_input_from_dict():
    rec = validate_input({"smiles": FTO43_SMILES, "mol_id": "FTO-43"})
    assert isinstance(rec, InputRecord)
    assert rec.mol_id == "FTO-43"


def test_validate_input_rejects_empty():
    with pytest.raises(ValidationError):
        validate_input({"smiles": "  "})


def test_validate_output_from_dict():
    out = validate_output(
        {
            "model": "admet_ai",
            "endpoint_values": {"hERG": 0.31, "BBB_Martins": 0.88},
            "provenance": {"upstream_commit": "abc"},
        }
    )
    assert isinstance(out, OutputRecord)
    assert out.model is ModelName.admet_ai
    assert out.endpoint_values["hERG"] == 0.31
