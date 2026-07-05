"""Parser tests for the opera adapter - the OUT-OF-BAND (MATLAB MCR + Java) template.

OPERA is not a pixi model: its runtime (MATLAB Compiler Runtime + Java/PaDEL) is isolated OUTSIDE pixi
(CLAUDE.md §4) and it is never driven through ``core.dispatch`` (``env_manifest is None``). The code
deliverable is therefore a PARSER (``run.py`` :func:`parse_preds`) that turns an already-computed OPERA
``preds.txt`` into ``core.schemas.OutputRecord``-shaped records. Because the parser is pure stdlib, these
tests run on the LAPTOP fast tier - no box, no MCR needed (task done-criterion). ``run.py`` is imported
directly by path (it has no pixi env to shell into, unlike every other model test).

The ``preds_sample.txt`` fixture is a format-faithful SYNTHETIC OPERA output: its header matches the
VERIFIED source columns (``<X>_pred`` / ``AD_<X>`` / ``AD_index_<X>`` / ``Conf_index_<X>``; IO_SPEC §1
#21) and its values are placeholders, NOT a real OPERA run (a real capture on FTO-43 is the ``needs_aaran``
residue once the MCR is installed). The tests assert PARSING and SHAPE, never chemical values.

What is checked (the done-criteria):
1. The sample parses to one valid OutputRecord per (molecule, endpoint) with ``endpoint_values`` = the
   ``_pred`` value and ``uncertainty`` carrying ``ad_in_domain`` / ``ad_index`` / ``conf_index``.
2. ``Conf_index`` is populated as a DIRECT uncertainty on every record, not discarded (CLAUDE.md §4).
3. Out-of-domain rows (``AD_<X>`` = 0) map to ``ad_in_domain`` False, and a ``NaN`` prediction maps to a
   null value - one bad cell never crashes the parse.
4. Header-robustness: a build that emits an extra ``_predRange`` column (or verbose neighbour columns) is
   tolerated - the range is preserved in ``uncertainty.extra``, unknown columns in ``raw`` - so the parser
   is correct on both the verified no-range build and the range-emitting build.
5. The out-of-band ``run_OPERA.sh`` command is assembled correctly, and the CLI ``--preds`` mode writes a
   valid output file end to end.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

from core.schemas import OutputRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO_ROOT / "endpoints" / "lipophilicity" / "opera"
RUN_PY = MODEL_DIR / "run.py"
SAMPLE = MODEL_DIR / "fixtures" / "preds_sample.txt"

# The seven output endpoints the sample requests (pKa expands to pKa_a + pKa_b).
EXPECTED_ENDPOINTS = {"LogP", "LogD", "pKa_a", "pKa_b", "FuB", "Clint", "Caco2"}


def _load_run():
    """Import the out-of-band parser module directly by path (it has no pixi env / package to import)."""
    spec = importlib.util.spec_from_file_location("opera_run", RUN_PY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run = _load_run()


def _records() -> list[dict]:
    return run.parse_preds(SAMPLE.read_text(encoding="utf-8"))


def _by_mol_endpoint(records: list[dict]) -> dict[tuple[str, str], dict]:
    return {(r["raw"]["molecule_id"], r["raw"]["endpoint"]): r for r in records}


def test_sample_parses_to_valid_output_records() -> None:
    """Every parsed record validates against the real core schema; 2 molecules x 7 endpoints = 14 records."""
    records = _records()
    assert len(records) == 14, f"expected 2 molecules x 7 endpoints, got {len(records)}"
    for rec in records:
        model = OutputRecord.model_validate(rec)  # raises on any schema / range violation
        assert model.model == "opera"
        assert len(model.endpoint_values) == 1, "one endpoint per OPERA record"

    got_endpoints = {r["raw"]["endpoint"] for r in records}
    assert got_endpoints == EXPECTED_ENDPOINTS, got_endpoints


def test_pred_values_and_uncertainty_mapped() -> None:
    """A representative record carries the _pred value + AD/AD_index/Conf_index in Uncertainty."""
    rec = _by_mol_endpoint(_records())[("FTO-43", "LogP")]
    model = OutputRecord.model_validate(rec)
    assert model.endpoint_values["LogP"] == pytest.approx(3.42)
    assert model.uncertainty is not None
    assert model.uncertainty.ad_in_domain is True          # AD_LogP = 1
    assert model.uncertainty.ad_index == pytest.approx(0.88)
    assert model.uncertainty.conf_index == pytest.approx(0.79)


def test_conf_index_is_direct_uncertainty_on_every_record() -> None:
    """Conf_index is a DIRECT uncertainty (landmine): populated on every record, in [0, 1], never dropped."""
    for rec in _records():
        model = OutputRecord.model_validate(rec)
        assert model.uncertainty is not None
        ci = model.uncertainty.conf_index
        assert ci is not None and 0.0 <= ci <= 1.0, f"missing/out-of-range Conf_index: {ci!r}"
        assert model.uncertainty.ad_index is not None
        assert model.uncertainty.ad_in_domain is not None


def test_out_of_domain_and_nan_handling() -> None:
    """AD_<X>=0 -> ad_in_domain False; a NaN prediction -> null value (one bad cell never crashes)."""
    by = _by_mol_endpoint(_records())

    # FTO-43 Clint is flagged out of domain (AD_Clint = 0) but still has a value + confidence.
    clint = OutputRecord.model_validate(by[("FTO-43", "Clint")])
    assert clint.uncertainty.ad_in_domain is False
    assert clint.endpoint_values["Clint"] == pytest.approx(15.4)

    # MOL-2 acidic pKa is NaN in the sample -> null value, and its AD flag is 0.
    pka = OutputRecord.model_validate(by[("MOL-2", "pKa_a")])
    assert pka.endpoint_values["pKa_a"] is None
    assert pka.uncertainty.ad_in_domain is False


def test_units_recorded_in_raw() -> None:
    """The verified per-endpoint units are surfaced in raw so a downstream consumer never guesses them."""
    by = _by_mol_endpoint(_records())
    assert "uL/min/10^6 cells" in by[("FTO-43", "Clint")]["raw"]["units"]
    assert "logPapp" in by[("FTO-43", "Caco2")]["raw"]["units"]
    assert "fraction unbound" in by[("FTO-43", "FuB")]["raw"]["units"]


def test_classify_column_ordering() -> None:
    """AD_index_ / Conf_index_ are classified before the bare AD_ prefix; _predRange distinct from _pred."""
    assert run.classify_column("LogP_pred") == ("LogP", "pred")
    assert run.classify_column("AD_LogP") == ("LogP", "ad_in_domain")
    assert run.classify_column("AD_index_LogP") == ("LogP", "ad_index")
    assert run.classify_column("Conf_index_LogP") == ("LogP", "conf_index")
    assert run.classify_column("LogP_predRange") == ("LogP", "pred_range")
    assert run.classify_column("CAS") is None


def test_tolerates_predrange_and_verbose_columns() -> None:
    """A range-emitting / verbose OPERA build is parsed correctly: range -> extra, unknown cols -> raw.

    The VERIFIED source version has NO _predRange column (CLAUDE.md §4); a different build adds one plus
    nearest-neighbour columns under higher verbosity. The header-driven parser must handle both without
    dropping the prediction or the native range.
    """
    text = (
        "MoleculeID,LogP_pred,LogP_predRange,AD_LogP,AD_index_LogP,Conf_index_LogP,CAS\n"
        "X1,2.50,2.1-2.9,1,0.70,0.60,50-00-0\n"
    )
    records = run.parse_preds(text)
    assert len(records) == 1
    model = OutputRecord.model_validate(records[0])
    assert model.endpoint_values["LogP"] == pytest.approx(2.50)
    assert model.uncertainty.conf_index == pytest.approx(0.60)
    assert model.uncertainty.extra["pred_range"] == "2.1-2.9"
    assert records[0]["raw"]["extra_columns"]["CAS"] == "50-00-0"


def test_build_opera_command_shape() -> None:
    """The out-of-band run_OPERA.sh argv matches the documented recipe (IO_SPEC §1 #21)."""
    cmd = run.build_opera_command(
        Path("/opt/OPERA"), Path("/opt/mcr/v912"),
        Path("in.smi"), Path("preds.txt"), ("LogP", "LogD", "pKa"),
    )
    assert cmd[0] == "/opt/OPERA/run_OPERA.sh"
    assert cmd[1] == "/opt/mcr/v912"
    assert "-s" in cmd and "in.smi" in cmd
    assert "-o" in cmd and "preds.txt" in cmd
    e = cmd.index("-e")
    assert cmd[e + 1 : e + 4] == ["LogP", "LogD", "pKa"]
    assert cmd[-2:] == ["-v", "1"]


def test_cli_preds_mode_writes_valid_output(tmp_path: Path) -> None:
    """The uniform CLI in --preds mode (offline/transcription path) parses a preds.txt to valid records."""
    in_smi = tmp_path / "in.smi"
    in_smi.write_text("CCO\tethanol\n", encoding="utf-8")
    out_path = tmp_path / "out.json"

    rc = run.main(["--input", str(in_smi), "--output", str(out_path), "--preds", str(SAMPLE)])
    assert rc == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert isinstance(payload, list) and len(payload) == 14
    for rec in payload:
        OutputRecord.model_validate(rec)


@pytest.mark.model
def test_opera_box_smoke_fto43(fto43_input: dict[str, str], tmp_path: Path) -> None:
    """Real OPERA run on the box, IF the out-of-band MCR runtime is installed; skipped otherwise.

    OPERA is out-of-band (no pixi env), so this does not shell into a pixi env - it runs run.py directly
    (stdlib) which invokes run_OPERA.sh under $OPERA_HOME / $MCR_ROOT. Until the MCR is installed the task
    is needs_aaran, so this test SKIPS rather than fails when the runtime is absent.
    """
    if not os.environ.get("OPERA_HOME") or not os.environ.get("MCR_ROOT"):
        pytest.skip("OPERA MCR runtime not installed ($OPERA_HOME / $MCR_ROOT unset); parser is done, MCR is the residue")

    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps(fto43_input), encoding="utf-8")

    rc = run.main(["--input", str(in_path), "--output", str(out_path)])
    assert rc == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert isinstance(payload, list) and payload
    for rec in payload:
        OutputRecord.model_validate(rec)
