"""Smoke test for the bayesherg adapter (t29) - a ``@pytest.mark.model`` box test.

Same shape as the t11 pksmart smoke (CLAUDE.md 5, SETTLED 8): the test runs in the **core** env (it may
import ``core`` + pytest) but **shells out** to the model's ``run.py`` in that model's **isolated legacy
pixi env** via ``pixi run --manifest-path``, exactly as ``core.dispatch`` does. So it drives the adapter
on the box AND validates the output against the real ``core.schemas.OutputRecord``.

Marked ``model`` so it is excluded from the fast tier (``pytest -m 'not model'``) and only runs on the box
where the legacy env is installed (``pixi install`` under ``endpoints/herg/bayesherg/``).

The assertions do NOT hard-code a hERG probability (the FTO-43 fixture SMILES is a documented placeholder,
and the MC-dropout score is stochastic): they assert ``P_block`` is a finite probability in [0, 1] and -
since BayeshERG's whole value is the aleatoric/epistemic split that drives the split-case adjudicator -
that ``uncertainty.aleatoric`` and ``uncertainty.epistemic`` are both populated and non-negative.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.schemas import OutputRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO_ROOT / "endpoints" / "herg" / "bayesherg"
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
def test_bayesherg_smoke_fto43(fto43_input: dict[str, str], tmp_path: Path) -> None:
    """FTO-43 fixture -> the adapter -> a valid OutputRecord with a hERG P_block + the uncertainty split."""
    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps(fto43_input), encoding="utf-8")

    _run_adapter_on_box(in_path, out_path)

    assert out_path.exists(), "adapter exited 0 but wrote no output file"
    payload = json.loads(out_path.read_text(encoding="utf-8"))

    # Single input -> single OutputRecord object, validated against the real core schema.
    record = OutputRecord.model_validate(payload)
    assert record.model == "bayesherg"

    # score is P(hERG block): a finite probability in [0, 1], direction UP = more likely blocker.
    p_block = record.endpoint_values["P_block"]
    assert isinstance(p_block, float) and p_block == p_block, f"P_block not a finite float: {p_block!r}"
    assert 0.0 <= p_block <= 1.0, f"P_block={p_block} outside [0, 1]"

    # The aleatoric/epistemic split is the whole point of BayeshERG (the adjudicator): both must be
    # populated, non-negative, and finite - carried in the reserved Uncertainty fields (schema rule).
    assert record.uncertainty is not None, "BayeshERG emits an alea/epis split; Uncertainty must be populated"
    alea = record.uncertainty.aleatoric
    epis = record.uncertainty.epistemic
    assert isinstance(alea, float) and alea == alea and alea >= 0.0, f"aleatoric not a finite >=0 float: {alea!r}"
    assert isinstance(epis, float) and epis == epis and epis >= 0.0, f"epistemic not a finite >=0 float: {epis!r}"
