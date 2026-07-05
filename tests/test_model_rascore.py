"""Smoke test for the rascore adapter (t31) - a ``@pytest.mark.model`` box test.

Same shape as the t11 pksmart / t30 cardiotox_net smokes (CLAUDE.md 5, SETTLED 8): the test runs in the
**core** env (it may import ``core`` + pytest) but **shells out** to the model's ``run.py`` in that
model's **isolated legacy pixi env** via ``pixi run --manifest-path``, exactly as ``core.dispatch`` does.
So it drives the adapter on the box AND validates the output against the real ``core.schemas.OutputRecord``.

Marked ``model`` so it is excluded from the fast tier (``pytest -m 'not model'``) and only runs on the box
where the legacy env is installed (``pixi install`` under ``endpoints/synthesizability/rascore/``).

The assertions do NOT hard-code a probability (the FTO-43 fixture SMILES is a documented placeholder):
they assert ``RAscore`` is a finite probability in [0, 1] (UP = more likely synthesizable), single-in ->
single-out, and that ``uncertainty`` is null (RAscore is a single-probability classifier).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.schemas import OutputRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO_ROOT / "endpoints" / "synthesizability" / "rascore"
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


@pytest.mark.model
def test_rascore_smoke_fto43(fto43_input: dict[str, str], tmp_path: Path) -> None:
    """FTO-43 fixture -> the adapter -> a valid OutputRecord with a finite RAscore in [0, 1]."""
    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps(fto43_input), encoding="utf-8")

    _run_adapter_on_box(in_path, out_path)

    assert out_path.exists(), "adapter exited 0 but wrote no output file"
    payload = json.loads(out_path.read_text(encoding="utf-8"))

    # Single input -> single OutputRecord object.
    assert isinstance(payload, dict), "a single input must yield a single record, not a list"
    record = OutputRecord.model_validate(payload)
    assert record.model == "rascore"

    # RAscore is P(a synthetic route is findable): a finite probability in [0, 1], UP = more synthesizable.
    rascore = record.endpoint_values["RAscore"]
    assert isinstance(rascore, float) and rascore == rascore, f"RAscore not a finite float: {rascore!r}"
    assert 0.0 <= rascore <= 1.0, f"RAscore={rascore} outside [0, 1]"

    # RAscore is a single-probability classifier: no native aleatoric/epistemic split.
    assert record.uncertainty is None, "RAscore emits a single probability; uncertainty must be null"
