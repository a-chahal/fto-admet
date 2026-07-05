"""Smoke + formula tests for the cns_mpo adapter (Wager 2010/2016 CNS MPO rule), following t10/t13/t14.

Like every ``@pytest.mark.model`` test (CLAUDE.md §5, SETTLED §8): the test itself runs in the **core**
env (it may import ``core`` + pytest), but it **shells out** to the model's ``run.py`` in that model's
**isolated pixi env** via ``pixi run --manifest-path``, exactly as ``core.dispatch`` does. So the test can
drive the adapter on the box AND validate its output against the real ``core.schemas.OutputRecord`` - the
model env never imports ``core``; the test env does.

Marked ``model`` so it is excluded from the fast tier (``pytest -m 'not model'``) and only runs on the box
where the model env is installed (``pixi install`` under ``endpoints/distribution/cns_mpo/``).

Two things are checked (the task's done-criteria):
1. **Smoke on FTO-43**: a finite ``CNS_MPO`` in [0, 6], and the score equals the sum of its six component
   desirabilities (the "six-component sum is consistent" criterion). It does NOT hard-code a value (the
   fixture SMILES is a documented placeholder and the pKa is the F-13 placeholder).
2. **Six-component consistency across cases**: for several SMILES + pKa the reported ``CNS_MPO`` equals the
   sum of ``D_MW + D_cLogP + D_cLogD + D_HBD + D_pKa + D_TPSA``, each of which sits in [0, 1].
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.schemas import OutputRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO_ROOT / "endpoints" / "distribution" / "cns_mpo"
MANIFEST = MODEL_DIR / "pixi.toml"
RUN_PY = MODEL_DIR / "run.py"

# CNS_MPO is on a fixed 0-6 scale by construction (six equally-weighted desirabilities, each in [0,1]).
MPO_LOW, MPO_HIGH = 0.0, 6.0

# The six component desirability keys carried in ``raw`` (each in [0,1]); their sum is the score.
COMPONENT_KEYS = ["D_MW", "D_cLogP", "D_cLogD", "D_HBD", "D_pKa", "D_TPSA"]

# A few (SMILES, pKa) cases spanning the transforms, used only to check sum-consistency (not pinned scores).
CASES = [
    ("CC(=O)Nc1ccc(O)cc1", 9.89),  # acetaminophen
    ("c1ccccc1", 0.0),  # benzene (no basic center; pKa low)
    (r"N1(CCN(C\C=C\c2ccccc2)CC1)C(c3ccccc3)c4ccccc4", 8.1),  # cinnarizine
]
SUM_TOL = 1e-6


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
def test_cns_mpo_smoke_fto43(fto43_input: dict[str, str], tmp_path: Path) -> None:
    """FTO-43 fixture -> the adapter -> a valid OutputRecord with a finite CNS_MPO in [0, 6]."""
    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps(fto43_input), encoding="utf-8")

    _run_adapter_on_box(in_path, out_path)

    assert out_path.exists(), "adapter exited 0 but wrote no output file"
    payload = json.loads(out_path.read_text(encoding="utf-8"))

    # Single input -> single OutputRecord object, validated against the real core schema.
    record = OutputRecord.model_validate(payload)
    assert record.model == "cns_mpo"
    assert record.uncertainty is None  # rule: deterministic given the injected pKa

    score = record.endpoint_values["CNS_MPO"]
    assert isinstance(score, float) and score == score, f"CNS_MPO not a finite float: {score!r}"
    assert MPO_LOW <= score <= MPO_HIGH, f"CNS_MPO {score} outside the 0-6 scale"

    # The six-component sum must be consistent with the reported score.
    components = [record.raw[k] for k in COMPONENT_KEYS]
    assert all(0.0 <= c <= 1.0 for c in components), f"a component desirability left [0,1]: {components}"
    assert score == pytest.approx(sum(components), abs=SUM_TOL), "CNS_MPO != sum of its six components"


@pytest.mark.model
@pytest.mark.parametrize("smiles,pka", CASES)
def test_cns_mpo_sum_consistent(smiles: str, pka: float, tmp_path: Path) -> None:
    """For each case the reported CNS_MPO equals the sum of its six [0,1] component desirabilities."""
    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps({"smiles": smiles, "mol_id": "case"}), encoding="utf-8")

    _run_adapter_on_box(in_path, out_path, pka=pka)

    record = OutputRecord.model_validate(json.loads(out_path.read_text(encoding="utf-8")))
    score = record.endpoint_values["CNS_MPO"]
    components = [record.raw[k] for k in COMPONENT_KEYS]
    assert all(0.0 <= c <= 1.0 for c in components), f"a component desirability left [0,1]: {components}"
    assert MPO_LOW <= score <= MPO_HIGH, f"CNS_MPO {score} outside the 0-6 scale"
    assert score == pytest.approx(sum(components), abs=SUM_TOL), "CNS_MPO != sum of its six components"
