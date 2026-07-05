"""Smoke + consistency tests for the pains_brenk adapter (PAINS + BRENK rule), following t10/t16.

Like every ``@pytest.mark.model`` test (CLAUDE.md §5, SETTLED §8): the test itself runs in the **core**
env (it may import ``core`` + pytest), but it **shells out** to the model's ``run.py`` in that model's
**isolated pixi env** via ``pixi run --manifest-path``, exactly as ``core.dispatch`` does. So the test can
drive the adapter on the box AND validate its output against the real ``core.schemas.OutputRecord`` - the
model env never imports ``core``; the test env does.

Marked ``model`` so it is excluded from the fast tier (``pytest -m 'not model'``) and only runs on the box
where the model env is installed (``pixi install`` under ``endpoints/structural_alerts/pains_brenk/``).

What is checked (the task's done-criteria):
1. **Smoke on FTO-43**: a valid OutputRecord with the four endpoint fields (``PAINS_hit``/``PAINS_count``/
   ``BRENK_hit``/``BRENK_count``), each of the right type, and **counts consistent with the booleans**
   (``hit`` iff ``count > 0``), and the matched-entry lists in ``raw`` whose lengths match the counts. It
   does NOT hard-code whether FTO-43 flags (the fixture SMILES is a documented placeholder).
2. **A known alerting molecule** (nitrobenzene, a BRENK ``nitro_group``; catechol, a PAINS ``catechol``)
   returns ``hit=True`` with a non-empty matched-entry list carrying names + matched-atom substructure -
   proving the catalogs are actually loaded and matching, not silently empty.
3. **A clean molecule** (ethane) returns both ``hit=False`` and both ``count == 0`` with empty match lists.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.schemas import OutputRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO_ROOT / "endpoints" / "structural_alerts" / "pains_brenk"
MANIFEST = MODEL_DIR / "pixi.toml"
RUN_PY = MODEL_DIR / "run.py"


def _run_adapter_on_box(input_path: Path, output_path: Path) -> None:
    """Invoke the model's run.py in its OWN pixi env, the same command core.dispatch builds."""
    cmd = [
        "pixi", "run", "--manifest-path", str(MANIFEST),
        "python", str(RUN_PY),
        "--input", str(input_path),
        "--output", str(output_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, f"adapter exited {proc.returncode}: {proc.stderr.strip()[:1000]}"


def _predict(smiles: str, tmp_path: Path) -> OutputRecord:
    """Drive the adapter on one SMILES and return the validated OutputRecord."""
    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps({"smiles": smiles, "mol_id": "case"}), encoding="utf-8")
    _run_adapter_on_box(in_path, out_path)
    assert out_path.exists(), "adapter exited 0 but wrote no output file"
    return OutputRecord.model_validate(json.loads(out_path.read_text(encoding="utf-8")))


def _assert_consistent(record: OutputRecord) -> None:
    """The four fields must be self-consistent: hit iff count > 0, and raw match-list length == count."""
    for catalog in ("PAINS", "BRENK"):
        hit = record.endpoint_values[f"{catalog}_hit"]
        count = record.endpoint_values[f"{catalog}_count"]
        assert isinstance(hit, bool), f"{catalog}_hit not a bool: {hit!r}"
        assert isinstance(count, int) and count >= 0, f"{catalog}_count not a non-negative int: {count!r}"
        assert hit == (count > 0), f"{catalog}_hit ({hit}) inconsistent with {catalog}_count ({count})"
        matches = record.raw[f"{catalog}_matches"]
        assert isinstance(matches, list) and len(matches) == count, (
            f"{catalog}_matches length {len(matches)} != {catalog}_count {count}"
        )
        for entry in matches:
            assert entry["name"], f"{catalog} matched entry missing a name: {entry!r}"
            assert isinstance(entry["atoms"], list), f"{catalog} matched entry missing atom list: {entry!r}"


@pytest.mark.model
def test_pains_brenk_smoke_fto43(fto43_input: dict[str, str], tmp_path: Path) -> None:
    """FTO-43 fixture -> the adapter -> a valid OutputRecord with the four consistent fields."""
    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps(fto43_input), encoding="utf-8")

    _run_adapter_on_box(in_path, out_path)

    assert out_path.exists(), "adapter exited 0 but wrote no output file"
    record = OutputRecord.model_validate(json.loads(out_path.read_text(encoding="utf-8")))
    assert record.model == "pains_brenk"
    assert record.uncertainty is None  # rule: deterministic
    assert set(record.endpoint_values) == {"PAINS_hit", "PAINS_count", "BRENK_hit", "BRENK_count"}
    _assert_consistent(record)
    assert record.raw.get("soft_filter") is True  # over-flags; look-closer, not auto-kill (docs §24)


@pytest.mark.model
def test_pains_brenk_brenk_positive_nitro(tmp_path: Path) -> None:
    """Nitrobenzene carries a BRENK ``nitro_group`` alert: BRENK_hit True, count >= 1, names + atoms present."""
    record = _predict("[O-][N+](=O)c1ccccc1", tmp_path)  # nitrobenzene
    assert record.endpoint_values["BRENK_hit"] is True, "nitro compound not flagged by BRENK (catalog not loaded?)"
    assert record.endpoint_values["BRENK_count"] >= 1
    _assert_consistent(record)
    names = [m["name"] for m in record.raw["BRENK_matches"]]
    assert any(name for name in names), "BRENK match carried no alert name"
    assert any(m["atoms"] for m in record.raw["BRENK_matches"]), "BRENK match carried no matched atoms"


@pytest.mark.model
def test_pains_brenk_pains_positive_catechol(tmp_path: Path) -> None:
    """Catechol is a documented PAINS scaffold (assay interference): PAINS_hit True with a named entry."""
    record = _predict("Oc1ccccc1O", tmp_path)  # catechol
    assert record.endpoint_values["PAINS_hit"] is True, "catechol not flagged by PAINS (catalog not loaded?)"
    assert record.endpoint_values["PAINS_count"] >= 1
    _assert_consistent(record)
    assert all(m["name"] for m in record.raw["PAINS_matches"]), "a PAINS match carried no alert name"


@pytest.mark.model
def test_pains_brenk_clean_molecule(tmp_path: Path) -> None:
    """A small inert molecule (ethane) trips neither catalog: both hits False, both counts 0, empty lists."""
    record = _predict("CC", tmp_path)  # ethane
    assert record.endpoint_values["PAINS_hit"] is False and record.endpoint_values["PAINS_count"] == 0
    assert record.endpoint_values["BRENK_hit"] is False and record.endpoint_values["BRENK_count"] == 0
    _assert_consistent(record)
    assert record.raw["PAINS_matches"] == [] and record.raw["BRENK_matches"] == []
