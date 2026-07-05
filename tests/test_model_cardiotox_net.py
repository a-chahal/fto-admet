"""Smoke test for the cardiotox_net adapter (t30) - a ``@pytest.mark.model`` box test.

Same shape as the t11 pksmart / t29 bayesherg smokes (CLAUDE.md 5, SETTLED 8): the test runs in the
**core** env (it may import ``core`` + pytest) but **shells out** to the model's ``run.py`` in that
model's **isolated legacy pixi env** via ``pixi run --manifest-path``, exactly as ``core.dispatch`` does.
So it drives the adapter on the box AND validates the output against the real ``core.schemas.OutputRecord``.

Marked ``model`` so it is excluded from the fast tier (``pytest -m 'not model'``) and only runs on the box
where the legacy env is installed (``pixi install`` under ``endpoints/herg/cardiotox_net/``).

The assertions do NOT hard-code a hERG probability (the FTO-43 fixture SMILES is a documented
placeholder): they assert ``P_block`` is a finite probability in [0, 1], that it is aligned POSITIONALLY
to the input (the bare-array landmine - a single input yields a single scored record), and that the
Morgan-on-bit applicability-domain flag is computed and internally consistent.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.schemas import OutputRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO_ROOT / "endpoints" / "herg" / "cardiotox_net"
MANIFEST = MODEL_DIR / "pixi.toml"
RUN_PY = MODEL_DIR / "run.py"

MORGAN_ONBIT_LIMIT = 93


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
def test_cardiotox_net_smoke_fto43(fto43_input: dict[str, str], tmp_path: Path) -> None:
    """FTO-43 fixture -> the adapter -> a valid OutputRecord with a hERG P_block + the AD flag."""
    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps(fto43_input), encoding="utf-8")

    _run_adapter_on_box(in_path, out_path)

    assert out_path.exists(), "adapter exited 0 but wrote no output file"
    payload = json.loads(out_path.read_text(encoding="utf-8"))

    # Single input -> single OutputRecord object (positional alignment: one in, one out).
    assert isinstance(payload, dict), "a single input must yield a single record, not a list"
    record = OutputRecord.model_validate(payload)
    assert record.model == "cardiotox_net"

    # P_block is P(hERG block): a finite probability in [0, 1], direction UP = more likely blocker.
    p_block = record.endpoint_values["P_block"]
    assert isinstance(p_block, float) and p_block == p_block, f"P_block not a finite float: {p_block!r}"
    assert 0.0 <= p_block <= 1.0, f"P_block={p_block} outside [0, 1]"

    # The applicability-domain flag must be computed (Morgan on-bit count vs the <= 93 limit) and
    # internally consistent: ad_in_domain == (on-bits <= limit). It is the reserved AD signal so the gate
    # can down-weight an out-of-range molecule; native alea/epis are INDIRECT here (None).
    assert record.uncertainty is not None, "the applicability-domain flag must be populated"
    extra = record.uncertainty.extra
    onbits = extra["morgan_onbits"]
    assert isinstance(onbits, int) and onbits >= 0, f"morgan_onbits not a non-negative int: {onbits!r}"
    assert extra["morgan_onbit_limit"] == MORGAN_ONBIT_LIMIT
    expected_in_domain = onbits <= MORGAN_ONBIT_LIMIT
    assert record.uncertainty.ad_in_domain is expected_in_domain
    assert extra["in_applicability_domain"] is expected_in_domain
