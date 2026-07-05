"""Smoke test for the admet_ai adapter - the cross-cutting generalist (@pytest.mark.model, box-only).

Same shape as the t10/t11 smokes (CLAUDE.md §5, SETTLED §8): the test runs in the **core** env (it may
import ``core`` + pytest) but **shells out** to the model's ``run.py`` in that model's **isolated pixi
env** via ``pixi run --manifest-path``, exactly as ``core.dispatch`` does. So it drives the adapter on the
box AND validates the output against the real ``core.schemas.OutputRecord``.

Marked ``model`` so it is excluded from the fast tier (``pytest -m 'not model'``) and only runs on the box
where the model env is installed (``pixi install`` under ``endpoints/triage/admet_ai/``).

The assertions do NOT hard-code prediction values (the FTO-43 fixture SMILES is a documented placeholder,
and ADMET-AI v2 predictions differ from v1 anyway). They assert the structural contract that the ten
downstream aggregators depend on: ``raw.columns`` carries the full head set, ``endpoint_values`` OMITS the
two R^2-negative heads (VDss + half-life) while keeping them quarantined in ``raw``, classification heads
are probabilities in [0, 1], and ``uncertainty`` is ``None`` (ADMET-AI's uncertainty is INDIRECT).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.schemas import OutputRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO_ROOT / "endpoints" / "triage" / "admet_ai"
MANIFEST = MODEL_DIR / "pixi.toml"
RUN_PY = MODEL_DIR / "run.py"

# The two heads F-17 marks worse-than-the-mean: they must NEVER appear in endpoint_values.
EXCLUDED_HEADS = ("VDss_Lombardo", "Half_Life_Obach")

# A few classification heads that must be present as probabilities in [0, 1] (the strong heads the gates
# actually use: hERG, BBB, Pgp, a CYP head). Used to assert the head set survived into endpoint_values.
CLASSIFICATION_HEADS = ("hERG", "BBB_Martins", "Pgp_Broccatelli", "CYP3A4_Veith", "HIA_Hou")


def _run_adapter_on_box(input_path: Path, output_path: Path) -> None:
    """Invoke the model's run.py in its OWN pixi env, the same command core.dispatch builds (CPU: no --gpu)."""
    cmd = [
        "pixi", "run", "--manifest-path", str(MANIFEST),
        "python", str(RUN_PY),
        "--input", str(input_path),
        "--output", str(output_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, f"adapter exited {proc.returncode}: {proc.stderr.strip()[:1000]}"


@pytest.mark.model
def test_admet_ai_smoke_fto43(fto43_input: dict[str, str], tmp_path: Path) -> None:
    """FTO-43 fixture -> the adapter -> a valid OutputRecord with the full head set and the F-17 exclusions."""
    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps(fto43_input), encoding="utf-8")

    _run_adapter_on_box(in_path, out_path)

    assert out_path.exists(), "adapter exited 0 but wrote no output file"
    payload = json.loads(out_path.read_text(encoding="utf-8"))

    # Single input -> single OutputRecord object, validated against the real core schema.
    record = OutputRecord.model_validate(payload)
    assert record.model == "admet_ai"

    # ADMET-AI has no native per-prediction uncertainty; the signal is INDIRECT (cross-model spread).
    assert record.uncertainty is None, "ADMET-AI uncertainty is INDIRECT; per-record uncertainty must be None"

    # raw.columns is the verbatim, complete output: every head + physchem + alerts + percentile companions.
    columns = record.raw["columns"]
    assert isinstance(columns, dict) and len(columns) > 40, f"expected the full ADMET-AI head set, got {len(columns)}"
    # Physchem + structural-alert counts + at least one percentile companion are present.
    for phys in ("molecular_weight", "logP", "tpsa", "QED"):
        assert phys in columns, f"physchem head {phys} missing from raw.columns"
    for alert in ("PAINS_alert", "BRENK_alert", "NIH_alert"):
        assert alert in columns, f"structural-alert count {alert} missing from raw.columns"
    assert any(k.endswith("_drugbank_approved_percentile") for k in columns), "no percentile companion in raw.columns"

    # F-17: the two R^2-negative heads are OMITTED from endpoint_values but quarantined in raw.
    for head in EXCLUDED_HEADS:
        assert head not in record.endpoint_values, f"{head} (R^2 negative) must NOT reach endpoint_values"
        assert head in columns, f"{head} should still be present verbatim in raw.columns"
        assert head in record.raw["excluded_r2_negative"], f"{head} should be quarantined in raw.excluded_r2_negative"

    # Percentile companions are context: kept in raw, kept OUT of endpoint_values.
    assert not any(k.endswith("_drugbank_approved_percentile") for k in record.endpoint_values), \
        "percentile companions must stay in raw, not endpoint_values"

    # The strong classification heads survived into endpoint_values as probabilities in [0, 1].
    for head in CLASSIFICATION_HEADS:
        assert head in record.endpoint_values, f"classification head {head} missing from endpoint_values"
        val = record.endpoint_values[head]
        assert isinstance(val, float) and 0.0 <= val <= 1.0, f"{head}={val!r} not a probability in [0, 1]"

    # The low-weight clearance heads are present (usable, just low-weight) and flagged for downstream.
    for head in ("Clearance_Hepatocyte_AZ", "Clearance_Microsome_AZ"):
        assert head in record.endpoint_values, f"clearance head {head} should be emitted (low-weight, not excluded)"
        assert head in record.raw["head_flags"], f"{head} should carry a low-weight advisory flag in raw.head_flags"
