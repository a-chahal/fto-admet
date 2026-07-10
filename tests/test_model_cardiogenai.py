"""Smoke test for the cardiogenai adapter - a ``@pytest.mark.model`` test (t24).

Same shape as the t11 pksmart smoke (CLAUDE.md §5, SETTLED §8): the test runs in the
**core** env (it may import ``core`` + pytest) but **shells out** to the model's ``run.py`` in that
model's **isolated pixi env** via ``pixi run --manifest-path``, exactly as ``core.dispatch`` does. So it
drives the adapter on the box AND validates the output against the real ``core.schemas.OutputRecord``.

Marked ``model`` so it is excluded from the fast tier (``pytest -m 'not model'``) and only runs on the box
where the model env is installed (``pixi install`` under ``endpoints/herg/cardiogenai/`` + the weights and
transformer-vocabulary CSV fetched under ``vendor/CardioGenAI/{model_parameters,data}``).

Two things are asserted:
  - The DISCRIMINATIVE path returns the three LANDMINE space-keyed pIC50 floats (``"hERG pIC50"``,
    ``"NaV1.5 pIC50"``, ``"CaV1.2 pIC50"``) in ``endpoint_values`` (a key without the space would miss).
  - The GENERATIVE stub refuses cleanly (non-zero exit) with the GATED message and emits no output file.

The assertions deliberately do NOT hard-code pIC50 values (the FTO-43 fixture SMILES is a documented
placeholder, and the numbers are model outputs): they assert the contract shape only.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.schemas import OutputRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO_ROOT / "endpoints" / "herg" / "cardiogenai"
MANIFEST = MODEL_DIR / "pixi.toml"
RUN_PY = MODEL_DIR / "run.py"

PIC50_KEYS = ("hERG pIC50", "NaV1.5 pIC50", "CaV1.2 pIC50")
GATED_MESSAGE = "GATED: needs Kunhuan binding/selectivity interface (not built)"


def _pixi_run(*run_args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the model's run.py in its OWN pixi env, the same command core.dispatch builds."""
    cmd = ["pixi", "run", "--manifest-path", str(MANIFEST), "python", str(RUN_PY), *run_args]
    return subprocess.run(cmd, capture_output=True, text=True)


@pytest.mark.model
def test_cardiogenai_discriminative_smoke_fto43(fto43_input: dict[str, str], tmp_path: Path) -> None:
    """FTO-43 fixture -> discriminative mode -> a valid OutputRecord with three space-keyed pIC50 floats."""
    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps(fto43_input), encoding="utf-8")

    proc = _pixi_run("--input", str(in_path), "--output", str(out_path))
    assert proc.returncode == 0, f"adapter exited {proc.returncode}: {proc.stderr.strip()[:1000]}"

    assert out_path.exists(), "adapter exited 0 but wrote no output file"
    payload = json.loads(out_path.read_text(encoding="utf-8"))

    # Single input -> single OutputRecord object, validated against the real core schema.
    record = OutputRecord.model_validate(payload)
    assert record.model == "cardiogenai"

    # LANDMINE (1): the three keys CONTAIN A SPACE and (2) each value is a regression pIC50 float, not a
    # probability. A valid FTO-43 fixture must score all three channels.
    for key in PIC50_KEYS:
        assert key in record.endpoint_values, f"missing space-keyed label {key!r}"
        val = record.endpoint_values[key]
        assert isinstance(val, float), f"{key}={val!r} is not a float pIC50"

    # CardioGenAI discriminative emits no native uncertainty signal.
    assert record.uncertainty is None


@pytest.mark.model
def test_cardiogenai_generative_stub_refuses(tmp_path: Path) -> None:
    """The generative mode is scaffold-only: it must refuse cleanly (GATED) and write no output."""
    out_path = tmp_path / "gen_output.json"
    proc = _pixi_run("--mode", "generative", "--output", str(out_path))

    assert proc.returncode != 0, "generative stub must refuse (non-zero exit), never emit candidates"
    assert GATED_MESSAGE in proc.stderr, f"generative stub must print the GATED message; got: {proc.stderr[:500]}"
    assert not out_path.exists(), "generative stub must not write any output file"
