"""Smoke + consistency tests for the lipinski_veber_qed adapter (drug-likeness context rule), following t10/t18.

Like every ``@pytest.mark.model`` test (CLAUDE.md §5, SETTLED §8): the test itself runs in the **core**
env (it may import ``core`` + pytest), but it **shells out** to the model's ``run.py`` in that model's
**isolated pixi env** via ``pixi run --manifest-path``, exactly as ``core.dispatch`` does. So the test can
drive the adapter on the box AND validate its output against the real ``core.schemas.OutputRecord`` - the
model env never imports ``core``; the test env does.

Marked ``model`` so it is excluded from the fast tier (``pytest -m 'not model'``) and only runs on the box
where the model env is installed (``pixi install`` under ``endpoints/druglikeness/lipinski_veber_qed/``).

What is checked (the task's done-criteria):
1. **Smoke on FTO-43**: a valid OutputRecord with the three endpoint fields (``Lipinski_violations`` /
   ``Veber_pass`` / ``QED``), each of the right type and range (violations int 0-4, Veber bool, QED in
   [0, 1]). It does NOT hard-code the numeric result (the fixture SMILES is a documented placeholder).
2. **A known drug-like molecule** (aspirin) passes all four Ro5 rules (0 violations), passes Veber, and
   yields a QED in (0, 1) - proving the descriptors + QED are actually computed, not stubbed.
3. **A known Ro5 violator** (a long lipophilic alkane) records at least one Lipinski violation and a QED
   below the aspirin case, proving the violation logic responds to the descriptors.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.schemas import OutputRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO_ROOT / "endpoints" / "druglikeness" / "lipinski_veber_qed"
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


def _assert_types_and_ranges(record: OutputRecord) -> None:
    """The three flags must have the documented types and ranges (docs §30)."""
    ev = record.endpoint_values
    assert set(ev) == {"Lipinski_violations", "Veber_pass", "QED"}
    violations = ev["Lipinski_violations"]
    veber = ev["Veber_pass"]
    qed = ev["QED"]
    assert isinstance(violations, int) and not isinstance(violations, bool), f"Lipinski_violations not an int: {violations!r}"
    assert 0 <= violations <= 4, f"Lipinski_violations out of 0-4: {violations!r}"
    assert isinstance(veber, bool), f"Veber_pass not a bool: {veber!r}"
    assert isinstance(qed, float), f"QED not a float: {qed!r}"
    assert 0.0 <= qed <= 1.0, f"QED out of [0, 1]: {qed!r}"


@pytest.mark.model
def test_lipinski_veber_qed_smoke_fto43(fto43_input: dict[str, str], tmp_path: Path) -> None:
    """FTO-43 fixture -> the adapter -> a valid OutputRecord with the three well-typed context flags."""
    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps(fto43_input), encoding="utf-8")

    _run_adapter_on_box(in_path, out_path)

    assert out_path.exists(), "adapter exited 0 but wrote no output file"
    record = OutputRecord.model_validate(json.loads(out_path.read_text(encoding="utf-8")))
    assert record.model == "lipinski_veber_qed"
    assert record.uncertainty is None  # rule: deterministic
    _assert_types_and_ranges(record)
    assert record.raw.get("context_only") is True  # POINTER / not a gate (docs §30)
    # the six underlying descriptors are carried for auditability
    assert set(record.raw["descriptors"]) == {"MW", "HBD", "HBA", "RotB", "TPSA", "logP"}


@pytest.mark.model
def test_lipinski_veber_qed_druglike_aspirin(tmp_path: Path) -> None:
    """Aspirin is a small drug-like acid: 0 Ro5 violations, Veber pass, QED in (0, 1)."""
    record = _predict("CC(=O)Oc1ccccc1C(=O)O", tmp_path)  # aspirin
    _assert_types_and_ranges(record)
    assert record.endpoint_values["Lipinski_violations"] == 0, "aspirin should violate no Ro5 rule"
    assert record.endpoint_values["Veber_pass"] is True, "aspirin should pass Veber"
    assert 0.0 < record.endpoint_values["QED"] < 1.0


@pytest.mark.model
def test_lipinski_veber_qed_ro5_violator(tmp_path: Path) -> None:
    """A long lipophilic alkane (C30) blows the logP<=5 rule: >= 1 Lipinski violation, low QED."""
    record = _predict("CCCCCCCCCCCCCCCCCCCCCCCCCCCCCC", tmp_path)  # triacontane, very high logP
    _assert_types_and_ranges(record)
    assert record.endpoint_values["Lipinski_violations"] >= 1, "high-logP alkane should violate Ro5"
    # far less drug-like than aspirin: QED should sit low
    assert record.endpoint_values["QED"] < 0.5
