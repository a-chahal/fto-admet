"""Smoke test for the aizynthfinder adapter (t32) - a ``@pytest.mark.model`` box test.

Same shape as the t11 pksmart / t30 cardiotox_net / t31 rascore smokes (CLAUDE.md 5, SETTLED 8): the test
runs in the **core** env (it may import ``core`` + pytest) but **shells out** to the model's ``run.py`` in
that model's **isolated pixi env** via ``pixi run --manifest-path``, exactly as ``core.dispatch`` does. So
it drives the adapter on the box AND validates the output against the real ``core.schemas.OutputRecord``.

Marked ``model`` so it is excluded from the fast tier (``pytest -m 'not model'``) and only runs on the box
where the isolated env is installed (``pixi install`` under ``endpoints/synthesizability/aizynthfinder/``)
AND the stock+policy config is cached (``$FTO_ADMET_ENV_CACHE/aizynth-data/config.yml``; see README).

The assertions do NOT hard-code a route (the FTO-43 fixture SMILES is a documented placeholder): they
assert AiZynthFinder returned the go/no-go key ``is_solved`` (the landmine key, NOT ``solved``) as a bool,
a finite ``top_score`` in [0, 1], integer step/route counts, single-in -> single-out, and null uncertainty.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.schemas import OutputRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO_ROOT / "endpoints" / "synthesizability" / "aizynthfinder"
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
def test_aizynthfinder_smoke_fto43(fto43_input: dict[str, str], tmp_path: Path) -> None:
    """FTO-43 fixture -> the adapter -> a valid OutputRecord with is_solved + a finite top_score."""
    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps(fto43_input), encoding="utf-8")

    _run_adapter_on_box(in_path, out_path)

    assert out_path.exists(), "adapter exited 0 but wrote no output file"
    payload = json.loads(out_path.read_text(encoding="utf-8"))

    # Single input -> single OutputRecord object.
    assert isinstance(payload, dict), "a single input must yield a single record, not a list"
    record = OutputRecord.model_validate(payload)
    assert record.model == "aizynthfinder"

    values = record.endpoint_values

    # LANDMINE: the go/no-go key is is_solved (NOT solved). A route search that ran returns a real bool.
    assert "is_solved" in values, "endpoint_values must carry the is_solved key (the landmine key)"
    assert isinstance(values["is_solved"], bool), f"is_solved not a bool: {values['is_solved']!r}"

    # top_score: score of the top-ranked route, a finite probability-scale value in [0, 1], UP = better.
    top_score = values["top_score"]
    assert isinstance(top_score, float) and top_score == top_score, f"top_score not a finite float: {top_score!r}"
    assert 0.0 <= top_score <= 1.0, f"top_score={top_score} outside [0, 1]"

    # Route / step counts are integers.
    for key in ("number_of_steps", "number_of_routes", "number_of_precursors_in_stock"):
        assert isinstance(values[key], int), f"{key} not an int: {values[key]!r}"

    # A route search emits no native aleatoric/epistemic split.
    assert record.uncertainty is None, "AiZynthFinder emits no native uncertainty; must be null"
