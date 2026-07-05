"""Smoke test for the rdkit_crippen adapter - the canonical ``@pytest.mark.model`` template.

This is the shape every later model's smoke test copies (CLAUDE.md §5, SETTLED §8): the test itself runs
in the **core** env (it may import ``core`` + pytest), but it **shells out** to the model's ``run.py`` in
that model's **isolated pixi env** via ``pixi run --manifest-path``, exactly as ``core.dispatch`` does.
So the test can drive the adapter on the box AND validate its output against the real
``core.schemas.OutputRecord`` - the model env never imports ``core``; the test env does.

Marked ``model`` so it is excluded from the fast tier (``pytest -m 'not model'``) and only runs on the
box where the model env is installed (``pixi install`` under ``endpoints/lipophilicity/rdkit_crippen/``).

The assertion deliberately does NOT hard-code a logP value (the FTO-43 fixture SMILES is a documented
placeholder pending the live PubChem lookup): it asserts a finite float in a wide sane band, matching the
task's done-criteria.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.schemas import OutputRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO_ROOT / "endpoints" / "lipophilicity" / "rdkit_crippen"
MANIFEST = MODEL_DIR / "pixi.toml"
RUN_PY = MODEL_DIR / "run.py"

# Wide, non-value-asserting band for a small-molecule Crippen logP (log units). Real FTO-43 and the
# acetic-acid placeholder both sit well inside it; the point is finite + plausible sign/magnitude.
LOGP_LOW, LOGP_HIGH = -2.0, 8.0


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


@pytest.mark.model
def test_rdkit_crippen_smoke_fto43(fto43_input: dict[str, str], tmp_path: Path) -> None:
    """FTO-43 fixture -> the adapter -> a valid OutputRecord with a finite, sane logP_crippen + MR."""
    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps(fto43_input), encoding="utf-8")

    _run_adapter_on_box(in_path, out_path)

    assert out_path.exists(), "adapter exited 0 but wrote no output file"
    payload = json.loads(out_path.read_text(encoding="utf-8"))

    # Single input -> single OutputRecord object, validated against the real core schema.
    record = OutputRecord.model_validate(payload)
    assert record.model == "rdkit_crippen"
    assert record.uncertainty is None  # deterministic descriptor: no native uncertainty

    logp = record.endpoint_values["logP_crippen"]
    mr = record.endpoint_values["MR"]
    assert isinstance(logp, float) and logp == logp, f"logP_crippen not a finite float: {logp!r}"
    assert LOGP_LOW <= logp <= LOGP_HIGH, f"logP_crippen {logp} outside sane band [{LOGP_LOW}, {LOGP_HIGH}]"
    assert isinstance(mr, float) and mr > 0.0, f"MR not a positive finite float: {mr!r}"
