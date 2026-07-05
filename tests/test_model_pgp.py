"""Unit tests for the DERIVED ``pgp`` efflux-flag helper (t28).

``pgp`` is a virtual / DERIVED model: no env, no ``run.py``, no subprocess (IO_SPEC §1 #16). Its whole
"run" surface is ``endpoints/distribution/pgp/pgp.py``, a pure helper that reads the ``Pgp_Broccatelli``
head off an already-collected generalist ``OutputRecord`` and normalizes it to an efflux flag in
``[0, 1]`` (UP = more efflux liability). So this suite is **laptop-only, no ``@pytest.mark.model``, no
box**: it exercises the helper against both a real ``core.schemas.OutputRecord`` and its plain-dict form.

The helper lives outside any importable package (there is no ``endpoints/__init__.py``), so it is loaded
by file path via ``importlib`` - the same way an aggregator would vendor it - rather than imported.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from core.models import ModelName
from core.schemas import OutputRecord

_PGP_PATH = (
    Path(__file__).resolve().parent.parent
    / "endpoints" / "distribution" / "pgp" / "pgp.py"
)


def _load_pgp():
    spec = importlib.util.spec_from_file_location("pgp_helper", _PGP_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so the frozen ``@dataclass`` can resolve its own module (PgpFlag uses
    # ``from __future__ import annotations``; dataclasses looks the module up in ``sys.modules``).
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pgp = _load_pgp()


def _admet_ai_record(pgp_value):
    """A synthetic ADMET-AI ``OutputRecord`` carrying (only) a ``Pgp_Broccatelli`` head."""
    return OutputRecord(
        model=ModelName.admet_ai,
        endpoint_values={"BBB_Martins": 0.83, "Pgp_Broccatelli": pgp_value},
        provenance={"model": "admet_ai"},
    )


def test_extracts_pgp_from_output_record():
    """Given a real ADMET-AI ``OutputRecord`` with ``Pgp_Broccatelli``, the helper returns that flag."""
    rec = _admet_ai_record(0.44)
    assert pgp.extract_pgp_flag(rec) == pytest.approx(0.44)

    detailed = pgp.extract_pgp(rec)
    assert detailed.value == pytest.approx(0.44)
    assert detailed.source_key == "Pgp_Broccatelli"
    assert detailed.source_model == "admet_ai"


def test_extracts_pgp_from_plain_dict():
    """The collected plain-JSON form (dict) works identically - aggregators may hold either."""
    rec = {
        "model": "admet_ai",
        "endpoint_values": {"Pgp_Broccatelli": 0.9},
        "provenance": {"model": "admet_ai"},
    }
    assert pgp.extract_pgp_flag(rec) == pytest.approx(0.9)
    assert pgp.extract_pgp(rec).source_model == "admet_ai"


def test_direction_not_inverted():
    """``Pgp_Broccatelli`` is already UP = more efflux liability: the flag is passed through, not flipped."""
    low = pgp.extract_pgp_flag(_admet_ai_record(0.1))
    high = pgp.extract_pgp_flag(_admet_ai_record(0.9))
    assert low == pytest.approx(0.1)
    assert high == pytest.approx(0.9)
    assert high > low  # more efflux stays the larger number


@pytest.mark.parametrize("boundary", [0.0, 1.0])
def test_accepts_probability_boundaries(boundary):
    """The inclusive ``[0, 1]`` range is accepted at both ends."""
    assert pgp.extract_pgp_flag(_admet_ai_record(boundary)) == pytest.approx(boundary)


def test_missing_head_returns_none():
    """No P-gp head present (e.g. a model that does not emit one) -> ``None``, not a raise."""
    rec = OutputRecord(
        model=ModelName.admet_ai,
        endpoint_values={"BBB_Martins": 0.83},
        provenance={"model": "admet_ai"},
    )
    assert pgp.extract_pgp_flag(rec) is None
    assert pgp.extract_pgp(rec).source_key is None


def test_null_head_returns_none():
    """A present-but-null head (bad SMILES -> null endpoint_values) -> ``None``."""
    assert pgp.extract_pgp_flag(_admet_ai_record(None)) is None


def test_non_numeric_string_returns_none():
    """A non-numeric string head (``str`` is a valid ``endpoint_values`` type) -> ``None``, not a raise."""
    assert pgp.extract_pgp_flag(_admet_ai_record("not-a-number")) is None


@pytest.mark.parametrize("bad", [object(), [0.4], {"p": 0.4}])
def test_non_numeric_dict_returns_none(bad):
    """The plain-dict path may carry arbitrary JSON junk (no schema guard): rejected as ``None``."""
    rec = {"model": "admet_ai", "endpoint_values": {"Pgp_Broccatelli": bad}}
    assert pgp.extract_pgp_flag(rec) is None


@pytest.mark.parametrize("out_of_range", [-0.01, 1.5, 42.0])
def test_out_of_range_rejected_not_clamped(out_of_range):
    """Numeric but outside ``[0, 1]``: rejected (``None``), never silently clamped to a fake probability."""
    assert pgp.extract_pgp_flag(_admet_ai_record(out_of_range)) is None


def test_bool_is_not_a_probability():
    """A bool sneaking into the head is not treated as 0/1 - it is rejected."""
    assert pgp.extract_pgp_flag(_admet_ai_record(True)) is None


def test_empty_record_dict_returns_none():
    """A record with no ``endpoint_values`` at all -> ``None``, no KeyError."""
    assert pgp.extract_pgp_flag({}) is None
    assert pgp.extract_pgp_flag({"model": "admet_ai"}) is None
