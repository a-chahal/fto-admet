"""Smoke test for the sfi adapter (Solubility Forecast Index rule), following the t10 template.

Like every ``@pytest.mark.model`` test (CLAUDE.md §5, SETTLED §8): the test itself runs in the **core**
env (it may import ``core`` + pytest), but it **shells out** to the model's ``run.py`` in that model's
**isolated pixi env** via ``pixi run --manifest-path``, exactly as ``core.dispatch`` does. So the test can
drive the adapter on the box AND validate its output against the real ``core.schemas.OutputRecord`` - the
model env never imports ``core``; the test env does.

Marked ``model`` so it is excluded from the fast tier (``pytest -m 'not model'``) and only runs on the box
where the model env is installed (``pixi install`` under ``endpoints/solubility/sfi/``).

The assertion does NOT hard-code an SFI value (the FTO-43 fixture SMILES is a documented placeholder
pending the live PubChem lookup, and the pKa is the F-13 placeholder): it asserts finite floats + an
integer, non-negative ring count in wide sane bands, matching the task's done-criteria. It also checks the
internal identity ``SFI == cLogD_7.4 + n_aromatic_rings`` so the rule's arithmetic is what shipped.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.schemas import OutputRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO_ROOT / "endpoints" / "solubility" / "sfi"
MANIFEST = MODEL_DIR / "pixi.toml"
RUN_PY = MODEL_DIR / "run.py"

# Wide, non-value-asserting bands. SFI = cLogD(7.4) + #aromatic rings; for small drug-like molecules cLogD
# sits in roughly [-6, 8] and aromatic rings in [0, ~8], so SFI comfortably fits this band. The point is
# finite + plausible magnitude, not a pinned number (placeholder SMILES + placeholder pKa).
SFI_LOW, SFI_HIGH = -12.0, 20.0
CLOGD_LOW, CLOGD_HIGH = -12.0, 12.0


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
def test_sfi_smoke_fto43(fto43_input: dict[str, str], tmp_path: Path) -> None:
    """FTO-43 fixture -> the adapter -> a valid OutputRecord with a finite, sane SFI / cLogD / ring count."""
    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps(fto43_input), encoding="utf-8")

    _run_adapter_on_box(in_path, out_path)

    assert out_path.exists(), "adapter exited 0 but wrote no output file"
    payload = json.loads(out_path.read_text(encoding="utf-8"))

    # Single input -> single OutputRecord object, validated against the real core schema.
    record = OutputRecord.model_validate(payload)
    assert record.model == "sfi"
    assert record.uncertainty is None  # rule: SFI-vs-generalist discrepancy is a downstream (t41) signal

    sfi = record.endpoint_values["SFI"]
    clogd = record.endpoint_values["cLogD_7.4"]
    n_aromatic = record.endpoint_values["n_aromatic_rings"]

    assert isinstance(sfi, float) and sfi == sfi, f"SFI not a finite float: {sfi!r}"
    assert SFI_LOW <= sfi <= SFI_HIGH, f"SFI {sfi} outside sane band [{SFI_LOW}, {SFI_HIGH}]"
    assert isinstance(clogd, float) and clogd == clogd, f"cLogD_7.4 not a finite float: {clogd!r}"
    assert CLOGD_LOW <= clogd <= CLOGD_HIGH, f"cLogD_7.4 {clogd} outside sane band [{CLOGD_LOW}, {CLOGD_HIGH}]"
    # Ring count is an integer >= 0 (bool is excluded: it is an int subclass but never a valid ring count).
    assert isinstance(n_aromatic, int) and not isinstance(n_aromatic, bool), f"ring count not an int: {n_aromatic!r}"
    assert n_aromatic >= 0, f"negative aromatic ring count: {n_aromatic}"

    # The rule's defining identity must hold on the shipped output (units + direction wired correctly).
    assert sfi == pytest.approx(clogd + n_aromatic), f"SFI {sfi} != cLogD {clogd} + rings {n_aromatic}"
