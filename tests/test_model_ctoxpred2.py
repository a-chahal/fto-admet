"""Smoke test for the ctoxpred2 adapter - a ``@pytest.mark.model`` test (t23).

Same shape as the t11 pksmart smoke (CLAUDE.md §5, SETTLED §8): the test runs in the **core** env (it may
import ``core`` + pytest) but **shells out** to the model's ``run.py`` in that model's **isolated pixi
env** via ``pixi run --manifest-path``, exactly as ``core.dispatch`` does. So it drives the adapter on the
box AND validates the output against the real ``core.schemas.OutputRecord``.

Marked ``model`` so it is excluded from the fast tier (``pytest -m 'not model'``) and only runs on the box
where the model env is installed (``pixi install`` under ``endpoints/herg/ctoxpred2/`` + the weights
decompressed under ``vendor/CToxPred2/models``).

The assertions deliberately do NOT hard-code channel calls (the FTO-43 fixture SMILES is a documented
placeholder, and the votes are model outputs): they assert the LANDMINE contract holds - three 0/1 integer
VOTES in ``endpoint_values`` and three confidences PARSED from the upstream ``"{:.1%}"`` percent strings to
floats in [0, 1] (hERG in ``uncertainty.confidence``, NaV1.5/CaV1.2 in ``uncertainty.extra``).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.schemas import OutputRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO_ROOT / "endpoints" / "herg" / "ctoxpred2"
MANIFEST = MODEL_DIR / "pixi.toml"
RUN_PY = MODEL_DIR / "run.py"

VOTE_KEYS = ("hERG_vote", "NaV1.5_vote", "CaV1.2_vote")


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
def test_ctoxpred2_smoke_fto43(fto43_input: dict[str, str], tmp_path: Path) -> None:
    """FTO-43 fixture -> the adapter -> a valid OutputRecord with three 0/1 votes + three parsed confidences."""
    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps(fto43_input), encoding="utf-8")

    _run_adapter_on_box(in_path, out_path)

    assert out_path.exists(), "adapter exited 0 but wrote no output file"
    payload = json.loads(out_path.read_text(encoding="utf-8"))

    # Single input -> single OutputRecord object, validated against the real core schema.
    record = OutputRecord.model_validate(payload)
    assert record.model == "ctoxpred2"

    # LANDMINE (1): each channel is a 0/1 integer VOTE, not a probability.
    for key in VOTE_KEYS:
        vote = record.endpoint_values[key]
        assert vote in (0, 1), f"{key}={vote!r} is not a 0/1 vote"
        assert isinstance(vote, int) and not isinstance(vote, bool), f"{key} must be an int vote, got {type(vote)}"

    # LANDMINE (2): confidences are PARSED from the upstream "{:.1%}" strings to floats in [0, 1].
    assert record.uncertainty is not None, "CToxPred2 emits confidences; Uncertainty must be populated"
    herg_conf = record.uncertainty.confidence
    assert isinstance(herg_conf, float) and 0.0 <= herg_conf <= 1.0, f"hERG confidence not a [0,1] float: {herg_conf!r}"

    extra = record.uncertainty.extra
    for k in ("nav15_confidence", "cav12_confidence"):
        val = extra[k]
        assert isinstance(val, float) and 0.0 <= val <= 1.0, f"{k} not a [0,1] float: {val!r}"

    # The verbatim upstream percent-STRING export is preserved in raw (so the parse is auditable) and
    # parsing it must reproduce the stored float confidence.
    assert record.raw["hERG_confidence"].endswith("%"), "raw hERG_confidence should be the upstream percent string"
    assert abs(float(record.raw["hERG_confidence"].rstrip("%")) / 100.0 - herg_conf) < 1e-9
