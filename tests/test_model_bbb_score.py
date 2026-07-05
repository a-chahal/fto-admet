"""Smoke + reference test for the bbb_score adapter (Gupta 2019 BBB Score rule), following t10/t13.

Like every ``@pytest.mark.model`` test (CLAUDE.md §5, SETTLED §8): the test itself runs in the **core**
env (it may import ``core`` + pytest), but it **shells out** to the model's ``run.py`` in that model's
**isolated pixi env** via ``pixi run --manifest-path``, exactly as ``core.dispatch`` does. So the test can
drive the adapter on the box AND validate its output against the real ``core.schemas.OutputRecord`` - the
model env never imports ``core``; the test env does.

Marked ``model`` so it is excluded from the fast tier (``pytest -m 'not model'``) and only runs on the box
where the model env is installed (``pixi install`` under ``endpoints/distribution/bbb_score/``).

Two things are checked:
1. **Smoke on FTO-43** (placeholder SMILES + placeholder pKa): a finite ``BBB_Score`` in [0, 6]. It does
   NOT hard-code a value (the fixture SMILES is a documented placeholder and the pKa is the F-13
   placeholder), only that the output is a valid ``OutputRecord`` with a sane score.
2. **Reference agreement** (the task's "unit-test the formula against gkxiao/BBB-score"): two molecules
   with published reference scores - acetaminophen 4.43 (pKa 9.89) and cinnarizine 5.01 (pKa 8.1) - are
   run through the adapter with their pKa injected via ``--pka`` and the score must match within tolerance.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.schemas import OutputRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO_ROOT / "endpoints" / "distribution" / "bbb_score"
MANIFEST = MODEL_DIR / "pixi.toml"
RUN_PY = MODEL_DIR / "run.py"

# BBB_Score is on a fixed 0-6 scale by construction (max = 1 + 1 + 1.5 + 2 + 0.5). The smoke assertion is
# finite + in-range, not a pinned number (placeholder SMILES + placeholder pKa).
BBB_LOW, BBB_HIGH = 0.0, 6.0

# Published reference scores from the gkxiao/BBB-score port (which reproduces Gupta 2019). Each is a
# (SMILES, pKa, expected BBB_Score) triple; the port rounds to 2 decimals, so a small tolerance suffices.
REFERENCE = [
    ("CC(=O)Nc1ccc(O)cc1", 9.89, 4.43),  # acetaminophen
    (r"N1(CCN(C\C=C\c2ccccc2)CC1)C(c3ccccc3)c4ccccc4", 8.1, 5.01),  # cinnarizine
]
REF_TOL = 0.05


def _run_adapter_on_box(input_path: Path, output_path: Path, pka: float | None = None) -> None:
    """Invoke the model's run.py in its OWN pixi env, the same command core.dispatch builds."""
    cmd = [
        "pixi", "run", "--manifest-path", str(MANIFEST),
        "python", str(RUN_PY),
        "--input", str(input_path),
        "--output", str(output_path),
    ]
    if pka is not None:
        cmd += ["--pka", str(pka)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, f"adapter exited {proc.returncode}: {proc.stderr.strip()[:1000]}"


@pytest.mark.model
def test_bbb_score_smoke_fto43(fto43_input: dict[str, str], tmp_path: Path) -> None:
    """FTO-43 fixture -> the adapter -> a valid OutputRecord with a finite BBB_Score in [0, 6]."""
    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps(fto43_input), encoding="utf-8")

    _run_adapter_on_box(in_path, out_path)

    assert out_path.exists(), "adapter exited 0 but wrote no output file"
    payload = json.loads(out_path.read_text(encoding="utf-8"))

    # Single input -> single OutputRecord object, validated against the real core schema.
    record = OutputRecord.model_validate(payload)
    assert record.model == "bbb_score"
    assert record.uncertainty is None  # rule: deterministic given the injected pKa

    score = record.endpoint_values["BBB_Score"]
    assert isinstance(score, float) and score == score, f"BBB_Score not a finite float: {score!r}"
    assert BBB_LOW <= score <= BBB_HIGH, f"BBB_Score {score} outside the 0-6 scale"


@pytest.mark.model
@pytest.mark.parametrize("smiles,pka,expected", REFERENCE)
def test_bbb_score_matches_reference(smiles: str, pka: float, expected: float, tmp_path: Path) -> None:
    """The reimplemented Gupta formula reproduces the gkxiao/BBB-score reference scores within tolerance."""
    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps({"smiles": smiles, "mol_id": "ref"}), encoding="utf-8")

    _run_adapter_on_box(in_path, out_path, pka=pka)

    record = OutputRecord.model_validate(json.loads(out_path.read_text(encoding="utf-8")))
    score = record.endpoint_values["BBB_Score"]
    assert score == pytest.approx(expected, abs=REF_TOL), f"BBB_Score {score} != reference {expected}"
