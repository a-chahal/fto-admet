"""Smoke test for the openadmet adapter - the CYP-metabolism REFERENCE (@pytest.mark.model, box-only).

Same shape as the t10/t11 smokes (CLAUDE.md §5, SETTLED §8): the test runs in the **core** env (it may
import ``core`` + pytest) but **shells out** to the model's ``run.py`` in that model's **isolated pixi
env** via ``pixi run --manifest-path``, exactly as ``core.dispatch`` does. So it drives the adapter on the
box AND validates the output against the real ``core.schemas.OutputRecord``.

Marked ``model`` so it is excluded from the fast tier (``pytest -m 'not model'``) and only runs on the box
where the model env is installed (``pixi install`` under ``endpoints/triage/openadmet/``) AND the released
baseline weights have been fetched into the /zfs cache (HuggingFace git-lfs; see README). If the weights
are absent the test SKIPS with a clear reason rather than failing - the weights are an out-of-band fetch,
not a repo artifact.

The assertions do NOT hard-code prediction values (the FTO-43 fixture SMILES is a documented placeholder,
and OpenADMET is reference-only anyway). They assert the structural contract:
  * ``endpoint_values`` carries the released multitask baseline's four CYP ``OADMET_PRED_*`` LOGAC50 heads
    as finite floats;
  * the reserved ``uncertainty`` envelope is populated from the ``OADMET_STD_*`` columns - and, because
    the RELEASED baselines are SINGLE CheMeleon models (not ensembles), every native sigma is ``None``
    (verified: inference sets std=NaN for a non-ensemble; the release blog says the STD columns are empty).
    This encodes the ground truth without fabricating a sigma. The STD->uncertainty wiring is real and would
    carry a number if an ensemble model dir were supplied.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from core.schemas import OutputRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO_ROOT / "endpoints" / "triage" / "openadmet"
MANIFEST = MODEL_DIR / "pixi.toml"
RUN_PY = MODEL_DIR / "run.py"

# The released multitask CheMeleon baseline's four CYP tasks, as the OADMET_PRED_ column names the pipeline
# appends (tag = "openadmet-AC50"; tasks = OPENADMET_LOGAC50_cyp{3a4,2d6,2c9,1a2}). Verified from a real box run.
_TAG = "openadmet-AC50"
_TASKS = ("cyp3a4", "cyp2d6", "cyp2c9", "cyp1a2")
PRED_KEYS = tuple(f"OADMET_PRED_{_TAG}_OPENADMET_LOGAC50_{t}" for t in _TASKS)
STD_KEYS = tuple(f"OADMET_STD_{_TAG}_OPENADMET_LOGAC50_{t}" for t in _TASKS)

# Default /zfs cache location for the fetched released baseline (overridable via OPENADMET_MODEL_DIRS).
_DEFAULT_MODEL_DIR = (
    "/zfs/sanjanp/fto-admet-envs/openadmet-models/"
    "cyp1a2-cyp2d6-cyp3a4-cyp3c9-chemeleon-baseline/anvil_training"
)
_DEFAULT_OPENADMET_HOME = "/zfs/sanjanp/fto-admet-envs/openadmet-home"


def _adapter_env() -> dict[str, str]:
    """Env for the box subprocess: point the adapter at the fetched baseline + keep caches on /zfs.

    ``OPENADMET_MODEL_DIRS`` selects the released baseline model dir; ``OPENADMET_HOME`` repoints $HOME so
    the CheMeleon foundation download lands on /zfs (HOME is ~97% full). Both honor a pre-set override.
    """
    env = dict(os.environ)
    env.setdefault("OPENADMET_MODEL_DIRS", _DEFAULT_MODEL_DIR)
    env.setdefault("OPENADMET_HOME", _DEFAULT_OPENADMET_HOME)
    env.setdefault("HF_HOME", "/zfs/sanjanp/fto-admet-envs/hf")
    return env


def _run_adapter_on_box(input_path: Path, output_path: Path, env: dict[str, str]) -> None:
    """Invoke the model's run.py in its OWN pixi env, the same command core.dispatch builds (CPU: no --gpu)."""
    cmd = [
        "pixi", "run", "--manifest-path", str(MANIFEST),
        "python", str(RUN_PY),
        "--input", str(input_path),
        "--output", str(output_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert proc.returncode == 0, f"adapter exited {proc.returncode}: {proc.stderr.strip()[:1500]}"


@pytest.mark.model
def test_openadmet_smoke_fto43(fto43_input: dict[str, str], tmp_path: Path) -> None:
    """FTO-43 fixture -> the adapter -> a valid OutputRecord with the four CYP PRED heads + STD envelope."""
    env = _adapter_env()
    model_dir = Path(env["OPENADMET_MODEL_DIRS"].split(os.pathsep)[0].split(",")[0])
    if not (model_dir / "recipe_components").exists():
        pytest.skip(
            f"released OpenADMET baseline not fetched at {model_dir} (out-of-band HuggingFace git-lfs); "
            "see endpoints/triage/openadmet/README.md"
        )

    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps(fto43_input), encoding="utf-8")

    _run_adapter_on_box(in_path, out_path, env)

    assert out_path.exists(), "adapter exited 0 but wrote no output file"
    payload = json.loads(out_path.read_text(encoding="utf-8"))

    # Single input -> single OutputRecord object, validated against the real core schema.
    record = OutputRecord.model_validate(payload)
    assert record.model == "openadmet"

    # Every OADMET_PRED_* head reaches endpoint_values as a finite float; the four released CYP heads present.
    assert record.endpoint_values, "no OADMET_PRED_* heads reached endpoint_values"
    for key in PRED_KEYS:
        val = record.endpoint_values.get(key)
        assert isinstance(val, float) and val == val, f"CYP head {key} not a finite float: {val!r}"

    # The reserved uncertainty envelope is populated FROM the OADMET_STD_* columns (native sigma, DIRECT).
    # Released baselines are single CheMeleon models -> every native sigma is None (no fabricated sigma).
    assert record.uncertainty is not None, "STD columns present; uncertainty envelope must be populated"
    for key in STD_KEYS:
        assert key in record.uncertainty.extra, f"native sigma column {key} missing from uncertainty.extra"
        assert record.uncertainty.extra[key] is None, (
            f"released single-model baseline must emit NaN sigma -> None, got {record.uncertainty.extra[key]!r}"
        )
    assert record.uncertainty.epistemic is None, "single-model baseline has no ensemble spread -> epistemic None"
