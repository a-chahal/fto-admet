"""Smoke test for the smartcyp adapter - a ``@pytest.mark.model`` test (runs on the box).

Same shape as the fame3r / pksmart smokes (CLAUDE.md 5, SETTLED 8): the test runs in the **core** env
(imports ``core`` + pytest) but **shells out** to the model's ``run.py`` in that model's **isolated pixi
env** via ``pixi run --manifest-path``, exactly as ``core.dispatch`` does. So it drives the adapter on the
box AND validates the output against the real ``core.schemas.OutputRecord``.

Marked ``model`` so it is excluded from the fast tier (``pytest -m 'not model'``) and only runs on the box
where the model env is installed (rdkit + openjdk) AND the vendored engine exists at
``endpoints/metabolism/smartcyp/vendor/smartcyp-2.4.2.jar`` (a gitignored binary fetched per the README).

The assertions do NOT hard-code Score/Ranking values (the FTO-43 fixture SMILES is a documented
placeholder). They assert the CONTRACT the metabolism aggregator consumes: a per-atom table in
``raw.atoms`` keyed on the RDKit ``atom_index`` with the general-3A4 ``Score`` (float, direction: LOWER =
more likely SoM) and ``Ranking`` (int or null), plus the top-site summary in ``endpoint_values`` and a
null ``uncertainty`` (SMARTCyp emits no native per-atom uncertainty).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.schemas import OutputRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO_ROOT / "endpoints" / "metabolism" / "smartcyp"
MANIFEST = MODEL_DIR / "pixi.toml"
RUN_PY = MODEL_DIR / "run.py"

# The aggregator (endpoints/metabolism/aggregate.py) keys on these EXACT names; the smoke asserts them so
# a rename here can never silently break the SoM co-rank.
RAW_ATOMS_KEY = "atoms"
ATOM_INDEX_KEY = "atom_index"
SMARTCYP_SCORE_KEY = "Score"
SMARTCYP_RANKING_KEY = "Ranking"


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
def test_smartcyp_smoke_fto43(fto43_input: dict[str, str], tmp_path: Path) -> None:
    """FTO-43 fixture -> the adapter -> a valid OutputRecord with the per-atom SoM table the aggregator needs."""
    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps(fto43_input), encoding="utf-8")

    _run_adapter_on_box(in_path, out_path)

    assert out_path.exists(), "adapter exited 0 but wrote no output file"
    payload = json.loads(out_path.read_text(encoding="utf-8"))

    record = OutputRecord.model_validate(payload)
    assert record.model == "smartcyp"

    # Top-site SUMMARY lives in endpoint_values (NOT the per-atom vector crammed in).
    n_atoms = record.endpoint_values["n_atoms"]
    assert isinstance(n_atoms, int) and n_atoms > 0, f"expected atoms scored, got {n_atoms!r}"
    top_idx = record.endpoint_values["top_som_atom_index"]
    top_score = record.endpoint_values["top_som_score"]
    assert isinstance(top_idx, int) and 0 <= top_idx < n_atoms, f"top_som_atom_index out of range: {top_idx!r}"
    assert isinstance(top_score, float), f"top_som_score must be a float (kJ/mol scale): {top_score!r}"

    # The load-bearing output: the per-atom SoM table the metabolism aggregator co-ranks (F-2).
    atoms = record.raw[RAW_ATOMS_KEY]
    assert isinstance(atoms, list) and len(atoms) == n_atoms, "raw.atoms must be the per-atom table"
    seen_ranking = False
    for i, row in enumerate(atoms):
        assert row[ATOM_INDEX_KEY] == i, "atom_index must be the RDKit index, dense and in order (aligns with FAME3R)"
        assert isinstance(row.get("element"), str) and row["element"], "each atom row carries its element symbol"
        score = row[SMARTCYP_SCORE_KEY]
        assert isinstance(score, float), f"atom {i} Score must be a float (lower = more likely SoM): {score!r}"
        ranking = row[SMARTCYP_RANKING_KEY]
        assert ranking is None or isinstance(ranking, int), f"atom {i} Ranking must be int or null: {ranking!r}"
        if ranking is not None:
            seen_ranking = True
    assert seen_ranking, "at least one atom must carry a general-3A4 Ranking (1 = most likely SoM)"

    # Direction sanity: the endpoint_values top site is the softest spot, so its Score is the minimum
    # among atoms the engine actually scored (lower Score = more likely SoM).
    scores = [row[SMARTCYP_SCORE_KEY] for row in atoms if isinstance(row[SMARTCYP_SCORE_KEY], float)]
    assert scores, "at least one atom must carry a numeric Score"
    assert top_score == min(scores), "top_som_score must be the lowest Score (direction: lower = more likely SoM)"

    # SMARTCyp emits no native per-atom uncertainty; the reserved envelope stays empty.
    assert record.uncertainty is None, "SMARTCyp has no native uncertainty signal; uncertainty must be null"

    # Raw-output cache: the verbatim CSV is kept so the result is reconstructible if the engine changes.
    assert isinstance(record.raw.get("csv"), str) and record.raw["csv"].strip(), "raw.csv (verbatim CSV) must be cached"
