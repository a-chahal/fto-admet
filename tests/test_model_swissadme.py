"""Smoke test for the swissadme adapter - the in-code SwissADME lipophilicity consensus.

Same shape as the t10 rdkit_crippen / t11 pksmart smokes (CLAUDE.md §5, SETTLED §8): the test runs in
the **core** env (it may import ``core`` + pytest) but **shells out** to the model's ``run.py`` in that
model's **isolated pixi env** via ``pixi run --manifest-path``, exactly as ``core.dispatch`` does. So it
drives the adapter on the box AND validates the output against the real ``core.schemas.OutputRecord``.

Marked ``model`` so it is excluded from the fast tier (``pytest -m 'not model'``) and only runs on the
box where the model env is installed (``pixi install`` under ``endpoints/lipophilicity/swissadme/``).

The assertions do NOT hard-code logP values (the FTO-43 fixture SMILES is a documented placeholder, and
SwissADME is a consensus-of-lenses tool anyway): they assert the reproduced lenses are finite and in a
wide sane band, that the direction/units land where the schema expects them, that ``Consensus_logP`` is
the mean of the reproduced lenses, and that the INDIRECT spread-based uncertainty is populated. The test
tolerates both the 2-lens build (no XLOGP3 binary) and a 3-lens build (binary present).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.schemas import OutputRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO_ROOT / "endpoints" / "lipophilicity" / "swissadme"
MANIFEST = MODEL_DIR / "pixi.toml"
RUN_PY = MODEL_DIR / "run.py"

# A wide, non-value-asserting band for each logP lens: finite + plausible magnitude, not a point value.
LOGP_BAND = (-15.0, 15.0)


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
def test_swissadme_smoke_fto43(fto43_input: dict[str, str], tmp_path: Path) -> None:
    """FTO-43 fixture -> the adapter -> a valid OutputRecord with reproduced lenses + consensus + spread."""
    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps(fto43_input), encoding="utf-8")

    _run_adapter_on_box(in_path, out_path)

    assert out_path.exists(), "adapter exited 0 but wrote no output file"
    payload = json.loads(out_path.read_text(encoding="utf-8"))

    # Single input -> single OutputRecord object, validated against the real core schema.
    record = OutputRecord.model_validate(payload)
    assert record.model == "swissadme"

    ev = record.endpoint_values

    # WLOGP and MLOGP are always reproduced; XLOGP3 only when a binary is present.
    reproduced = ["WLOGP", "MLOGP"] + (["XLOGP3"] if "XLOGP3" in ev else [])
    lo, hi = LOGP_BAND
    for lens in reproduced:
        val = ev[lens]
        assert isinstance(val, float) and val == val, f"{lens} not a finite float: {val!r}"
        assert lo <= val <= hi, f"{lens}={val} outside sane logP band [{lo}, {hi}]"

    # Consensus is the mean of exactly the reproduced lenses.
    consensus = ev["Consensus_logP"]
    assert isinstance(consensus, float) and consensus == consensus, f"Consensus_logP not finite: {consensus!r}"
    expected = sum(ev[lens] for lens in reproduced) / len(reproduced)
    assert abs(consensus - expected) < 1e-9, f"Consensus_logP {consensus} != mean of lenses {expected}"

    # INDIRECT uncertainty: the lens spread must be populated in extra (the first-class fields stay null
    # because mapping spread -> calibrated confidence is the DEFERRED AD policy).
    assert record.uncertainty is not None, "spread-based uncertainty must be populated"
    extra = record.uncertainty.extra
    assert extra.get("n_lenses") == len(reproduced), f"n_lenses {extra.get('n_lenses')} != {len(reproduced)}"
    assert set(extra.get("lens_values", {})) == set(reproduced), "lens_values must list exactly the reproduced lenses"
    assert isinstance(extra.get("spread_range"), float) and extra["spread_range"] >= 0.0
    assert isinstance(extra.get("spread_std"), float) and extra["spread_std"] >= 0.0
