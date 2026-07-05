"""Smoke test for the pksmart adapter - the second ``@pytest.mark.model`` template (first REAL env).

Same shape as the t10 rdkit_crippen smoke (CLAUDE.md §5, SETTLED §8): the test runs in the **core** env
(it may import ``core`` + pytest) but **shells out** to the model's ``run.py`` in that model's **isolated
pixi env** via ``pixi run --manifest-path``, exactly as ``core.dispatch`` does. So it drives the adapter on
the box AND validates the output against the real ``core.schemas.OutputRecord``.

Marked ``model`` so it is excluded from the fast tier (``pytest -m 'not model'``) and only runs on the box
where the model env is installed (``pixi install`` under ``endpoints/clearance/pksmart/``).

The assertions deliberately do NOT hard-code PK values (the FTO-43 fixture SMILES is a documented
placeholder pending the live PubChem lookup, and PKSmart CL is ranking-only anyway): they assert the five
human params are finite and in wide sane physiological bands, correct units/direction per the schema, and -
since PKSmart emits a native fold-error - that the CL fold-error interval populates ``Uncertainty``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.schemas import OutputRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO_ROOT / "endpoints" / "clearance" / "pksmart"
MANIFEST = MODEL_DIR / "pixi.toml"
RUN_PY = MODEL_DIR / "run.py"

# The five human PK params PKSmart emits, keyed as run.py emits them, each with a wide non-value-asserting
# physiological band (finite + plausible sign/magnitude; not a point value). fu is a fraction in [0, 1].
PARAM_BANDS: dict[str, tuple[float, float]] = {
    "CL_mL_min_kg": (0.0, 2000.0),
    "VDss_L_kg": (0.0, 100.0),
    "t_half_h": (0.0, 1000.0),
    "fu": (0.0, 1.0),
    "MRT_h": (0.0, 1000.0),
}


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
def test_pksmart_smoke_fto43(fto43_input: dict[str, str], tmp_path: Path) -> None:
    """FTO-43 fixture -> the adapter -> a valid OutputRecord with finite human PK + a CL fold-error."""
    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps(fto43_input), encoding="utf-8")

    _run_adapter_on_box(in_path, out_path)

    assert out_path.exists(), "adapter exited 0 but wrote no output file"
    payload = json.loads(out_path.read_text(encoding="utf-8"))

    # Single input -> single OutputRecord object, validated against the real core schema.
    record = OutputRecord.model_validate(payload)
    assert record.model == "pksmart"

    for key, (low, high) in PARAM_BANDS.items():
        val = record.endpoint_values[key]
        assert isinstance(val, float) and val == val, f"{key} not a finite float: {val!r}"
        assert low <= val <= high, f"{key}={val} outside sane band [{low}, {high}]"

    # PKSmart emits a native fold-error, so the reserved uncertainty envelope must be populated: the CL
    # prediction interval (lower/upper bounds) plus the per-parameter fold factors in extra.
    assert record.uncertainty is not None, "PKSmart emits a fold-error; Uncertainty must be populated"
    lo = record.uncertainty.fold_error_low
    hi = record.uncertainty.fold_error_high
    assert isinstance(lo, float) and isinstance(hi, float), f"CL fold-error bounds not floats: {lo!r}, {hi!r}"
    assert 0.0 <= lo <= hi, f"CL fold-error interval not ordered/positive: [{lo}, {hi}]"
    cl = record.endpoint_values["CL_mL_min_kg"]
    assert lo <= cl <= hi, f"CL {cl} not inside its own fold-error interval [{lo}, {hi}]"
    assert "cl_fold_error" in record.uncertainty.extra, "CL fold factor should be surfaced in extra"
