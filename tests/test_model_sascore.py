"""Smoke + consistency tests for the sascore adapter (synthetic-accessibility rule), following t10/t19.

Like every ``@pytest.mark.model`` test (CLAUDE.md §5, SETTLED §8): the test itself runs in the **core**
env (it may import ``core`` + pytest), but it **shells out** to the model's ``run.py`` in that model's
**isolated pixi env** via ``pixi run --manifest-path``, exactly as ``core.dispatch`` does. So the test can
drive the adapter on the box AND validate its output against the real ``core.schemas.OutputRecord`` - the
model env never imports ``core``; the test env does.

Marked ``model`` so it is excluded from the fast tier (``pytest -m 'not model'``) and only runs on the box
where the model env is installed (``pixi install`` under ``endpoints/synthesizability/sascore/``) and the
vendored RDKit-Contrib ``sascorer.py`` + ``fpscores.pkl.gz`` are present.

What is checked (the task's done-criteria):
1. **Smoke on FTO-43**: a valid OutputRecord with a finite ``SAscore`` in [1, 10]. It does NOT hard-code
   the numeric result (the fixture SMILES is a documented placeholder).
2. **Direction sanity** (the landmine, LOWER = easier): a trivially simple molecule (ethanol) scores
   LOWER than a stereochemically dense, fused-ring natural product-like scaffold, proving the score
   responds to complexity in the documented direction and is not stubbed.
"""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

import pytest

from core.schemas import OutputRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO_ROOT / "endpoints" / "synthesizability" / "sascore"
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
    tmp_path.mkdir(parents=True, exist_ok=True)  # callers may pass a per-case subdir
    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps({"smiles": smiles, "mol_id": "case"}), encoding="utf-8")
    _run_adapter_on_box(in_path, out_path)
    assert out_path.exists(), "adapter exited 0 but wrote no output file"
    return OutputRecord.model_validate(json.loads(out_path.read_text(encoding="utf-8")))


def _assert_finite_sascore(record: OutputRecord) -> float:
    """SAscore must be a finite float on the documented 1-10 scale (docs §25)."""
    ev = record.endpoint_values
    assert set(ev) == {"SAscore"}
    sascore = ev["SAscore"]
    assert isinstance(sascore, float), f"SAscore not a float: {sascore!r}"
    assert math.isfinite(sascore), f"SAscore not finite: {sascore!r}"
    assert 1.0 <= sascore <= 10.0, f"SAscore out of [1, 10]: {sascore!r}"
    return sascore


@pytest.mark.model
def test_sascore_smoke_fto43(fto43_input: dict[str, str], tmp_path: Path) -> None:
    """FTO-43 fixture -> the adapter -> a valid OutputRecord with a finite SAscore in [1, 10]."""
    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps(fto43_input), encoding="utf-8")

    _run_adapter_on_box(in_path, out_path)

    assert out_path.exists(), "adapter exited 0 but wrote no output file"
    record = OutputRecord.model_validate(json.loads(out_path.read_text(encoding="utf-8")))
    assert record.model == "sascore"
    assert record.uncertainty is None  # rule: deterministic
    _assert_finite_sascore(record)
    # the direction/scale is carried in raw for downstream auditability (LOWER = easier)
    assert record.raw["scale"]["direction"] == "lower = easier to synthesize"


@pytest.mark.model
def test_sascore_direction_simple_below_complex(tmp_path: Path) -> None:
    """LOWER = easier (the landmine): a trivial molecule scores below a complex fused-ring scaffold.

    Ethanol is about as easy to make as a molecule gets; a stereochemically dense polycyclic scaffold
    (here a morphinan-like fragment) is much harder. So SAscore(ethanol) < SAscore(complex), proving the
    score tracks complexity in the documented direction and is not a stub.
    """
    easy = _assert_finite_sascore(_predict("CCO", tmp_path / "easy"))  # ethanol
    hard = _assert_finite_sascore(
        _predict("CN1CCC23c4c5ccc(O)c4OC2C(O)C=CC3C1C5", tmp_path / "hard")  # morphine-like polycycle
    )
    assert easy < hard, f"expected SAscore(ethanol)={easy} < SAscore(complex)={hard} (lower = easier)"
