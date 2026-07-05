"""Smoke + axis-convention tests for the boiled_egg adapter (BOILED-Egg rule), following t10/t14/t15.

Like every ``@pytest.mark.model`` test (CLAUDE.md §5, SETTLED §8): the test itself runs in the **core**
env (it may import ``core`` + pytest), but it **shells out** to the model's ``run.py`` in that model's
**isolated pixi env** via ``pixi run --manifest-path``, exactly as ``core.dispatch`` does. So the test can
drive the adapter on the box AND validate its output against the real ``core.schemas.OutputRecord`` - the
model env never imports ``core``; the test env does.

Marked ``model`` so it is excluded from the fast tier (``pytest -m 'not model'``) and only runs on the box
where the model env is installed (``pixi install`` under ``endpoints/distribution/boiled_egg/``).

What is checked (the task's done-criteria):
1. **Smoke on FTO-43**: a valid OutputRecord whose two endpoint values (``HIA_boiled_egg`` /
   ``BBB_boiled_egg``) are booleans. It does NOT hard-code which way they land (the fixture SMILES is a
   documented placeholder).
2. **Axis convention (F-9, the landmine)**: a point KNOWN to sit inside the yolk must return ``BBB=True``,
   and a point known to sit outside the yolk (but far in TPSA) must return ``BBB=False`` while still
   ``HIA=True`` - this pins ``(x=TPSA, y=WLOGP)`` and fails loudly if the axes were swapped. A point far
   outside both regions returns both ``False``. Because the coordinate is derived purely from a SMILES via
   RDKit, the test drives the adapter on real molecules chosen to fall in each region.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.schemas import OutputRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO_ROOT / "endpoints" / "distribution" / "boiled_egg"
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


@pytest.mark.model
def test_boiled_egg_smoke_fto43(fto43_input: dict[str, str], tmp_path: Path) -> None:
    """FTO-43 fixture -> the adapter -> a valid OutputRecord with two boolean endpoint values."""
    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps(fto43_input), encoding="utf-8")

    _run_adapter_on_box(in_path, out_path)

    assert out_path.exists(), "adapter exited 0 but wrote no output file"
    record = OutputRecord.model_validate(json.loads(out_path.read_text(encoding="utf-8")))
    assert record.model == "boiled_egg"
    assert record.uncertainty is None  # rule: deterministic

    hia = record.endpoint_values["HIA_boiled_egg"]
    bbb = record.endpoint_values["BBB_boiled_egg"]
    assert isinstance(hia, bool), f"HIA_boiled_egg not a bool: {hia!r}"
    assert isinstance(bbb, bool), f"BBB_boiled_egg not a bool: {bbb!r}"
    # The yolk is a strict subset of the white: nothing is brain-penetrant but not GI-absorbed.
    if bbb:
        assert hia, "BBB=True but HIA=False - the yolk must lie inside the white (region nesting broken)"
    # The (TPSA, WLOGP) coordinates are echoed for audit.
    assert isinstance(record.raw["TPSA"], float) and isinstance(record.raw["WLOGP"], float)


@pytest.mark.model
def test_boiled_egg_in_yolk_is_bbb_true(tmp_path: Path) -> None:
    """A molecule KNOWN to fall in the yolk must return BBB=True (pins x=TPSA, y=WLOGP; F-9 landmine).

    Diazepam (TPSA ~= 32, WLOGP ~= 3) sits well inside the yolk; if the axes were swapped it would fall
    outside, so BBB would flip to False. It must also be HIA=True (yolk is inside the white).
    """
    record = _predict("CN1C(=O)CN=C(c2ccccc2)c2cc(Cl)ccc21", tmp_path)  # diazepam
    assert record.endpoint_values["BBB_boiled_egg"] is True, "in-yolk molecule not flagged BBB (axis inversion?)"
    assert record.endpoint_values["HIA_boiled_egg"] is True, "in-yolk molecule must also be HIA (region nesting)"


@pytest.mark.model
def test_boiled_egg_in_white_not_yolk(tmp_path: Path) -> None:
    """A molecule inside the white but outside the yolk: HIA=True, BBB=False (larger-TPSA region).

    Metronidazole (TPSA ~= 84, WLOGP ~= 0) sits past the yolk's TPSA reach (~79) but inside the white
    (which extends to ~142), so it is absorbed but not brain-penetrant.
    """
    record = _predict("Cc1ncc([N+](=O)[O-])n1CCO", tmp_path)  # metronidazole
    assert record.endpoint_values["HIA_boiled_egg"] is True, "in-white molecule not flagged HIA"
    assert record.endpoint_values["BBB_boiled_egg"] is False, "molecule beyond the yolk still flagged BBB"


@pytest.mark.model
def test_boiled_egg_outside_both(tmp_path: Path) -> None:
    """A large, very polar molecule falls outside both regions: HIA=False, BBB=False.

    Sucrose (TPSA ~= 190, WLOGP < 0) is far beyond the white's TPSA reach, so neither region contains it.
    """
    record = _predict("OCC1OC(OC2(CO)OC(CO)C(O)C2O)C(O)C(O)C1O", tmp_path)  # sucrose
    assert record.endpoint_values["HIA_boiled_egg"] is False, "very polar molecule wrongly flagged HIA"
    assert record.endpoint_values["BBB_boiled_egg"] is False, "very polar molecule wrongly flagged BBB"
