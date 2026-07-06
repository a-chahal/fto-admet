"""Smoke test for the fame3r adapter - a ``@pytest.mark.model`` test (runs on the box).

Same shape as the pksmart smoke (CLAUDE.md §5, SETTLED §8): the test runs in the **core** env (imports
``core`` + pytest) but **shells out** to the model's ``run.py`` in that model's **isolated pixi env** via
``pixi run --manifest-path``, exactly as ``core.dispatch`` does. So it drives the adapter on the box AND
validates the output against the real ``core.schemas.OutputRecord``.

Marked ``model`` so it is excluded from the fast tier (``pytest -m 'not model'``) and only runs on the box
where the model env is installed AND the model artifacts exist under ``endpoints/metabolism/fame3r/data/
models`` (trained in-house by ``build_model.py`` on the shipped ``train.sdf`` - see README).

The assertions do NOT hard-code SoM probabilities (the FTO-43 fixture SMILES is a documented placeholder).
They assert the CONTRACT: a per-atom SoM-probability table with RDKit atom indices attached, each
probability a finite 0-1 value (direction: UP = more likely SoM), and the FAME3RScore applicability-domain
signal populated.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.schemas import OutputRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO_ROOT / "endpoints" / "metabolism" / "fame3r"
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
def test_fame3r_smoke_fto43(fto43_input: dict[str, str], tmp_path: Path) -> None:
    """FTO-43 fixture -> the adapter -> a valid OutputRecord with a per-atom SoM table + FAME3RScore."""
    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps(fto43_input), encoding="utf-8")

    _run_adapter_on_box(in_path, out_path)

    assert out_path.exists(), "adapter exited 0 but wrote no output file"
    payload = json.loads(out_path.read_text(encoding="utf-8"))

    record = OutputRecord.model_validate(payload)
    assert record.model == "fame3r"

    # Molecule-level scalar summaries (NOT the per-atom vector crammed into endpoint_values).
    n_atoms = record.endpoint_values["n_atoms_scored"]
    assert isinstance(n_atoms, int) and n_atoms > 0, f"expected atoms scored, got {n_atoms!r}"
    top_prob = record.endpoint_values["max_som_probability"]
    assert isinstance(top_prob, float) and 0.0 <= top_prob <= 1.0, f"max_som_probability not a 0-1 float: {top_prob!r}"
    assert isinstance(record.endpoint_values["top_som_atom_index"], int)

    # The load-bearing output: the per-atom SoM-probability table with RDKit atom indices attached.
    atoms = record.raw["atoms"]
    assert isinstance(atoms, list) and len(atoms) == n_atoms, "raw.atoms must be the per-atom table"
    for i, row in enumerate(atoms):
        assert row["atom_index"] == i, "atom_index must be the RDKit index this adapter attaches, in order"
        prob = row["som_probability"]
        assert isinstance(prob, float) and 0.0 <= prob <= 1.0, f"atom {i} SoM prob not a 0-1 float: {prob!r}"
    # No 0.3 (or any) threshold binarization is emitted - raw probabilities only (landmine).
    assert all("binary" not in k and "y_pred" not in k for row in atoms for k in row), "no binarized SoM call expected"

    # FAME3RScore applicability-domain signal must be populated (per-atom + the top-SoM atom's AD index).
    assert record.uncertainty is not None, "FAME3R emits FAME3RScore; Uncertainty must be populated"
    ad = record.uncertainty.ad_index
    assert ad is None or (0.0 <= ad <= 1.0), f"ad_index (top-atom FAME3RScore) out of [0,1]: {ad!r}"
    per_atom_scores = record.uncertainty.extra["fame3r_score_per_atom"]
    assert isinstance(per_atom_scores, list) and len(per_atom_scores) == n_atoms, "FAME3RScore per atom expected"
    assert all(s is None or (0.0 <= s <= 1.0) for s in per_atom_scores), "FAME3RScore must be 0-1"
