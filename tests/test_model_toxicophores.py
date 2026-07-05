"""Smoke + consistency tests for the toxicophores adapter (toxicity structural-alert rule), following t10/t17.

Like every ``@pytest.mark.model`` test (CLAUDE.md §5, SETTLED §8): the test itself runs in the **core**
env (it may import ``core`` + pytest), but it **shells out** to the model's ``run.py`` in that model's
**isolated pixi env** via ``pixi run --manifest-path``, exactly as ``core.dispatch`` does. So the test can
drive the adapter on the box AND validate its output against the real ``core.schemas.OutputRecord`` - the
model env never imports ``core``; the test env does.

Marked ``model`` so it is excluded from the fast tier (``pytest -m 'not model'``) and only runs on the box
where the model env is installed (``pixi install`` under ``endpoints/toxicity/toxicophores/``).

What is checked (the task's done-criteria):
1. **Smoke on FTO-43**: a valid OutputRecord with the three endpoint fields (``tox_alert_hit`` /
   ``tox_alert_count`` / ``catalog``), each of the right type, the documented catalog name, and the count
   **consistent with the flag** (``hit`` iff ``count > 0``), with the matched-name list in ``raw`` whose
   length matches the count. It does NOT hard-code whether FTO-43 flags (the fixture SMILES is a
   documented placeholder).
2. **A known alerting molecule** (nitrobenzene, a BRENK ``nitro_group``) returns ``tox_alert_hit=True``
   with a non-empty matched-alert list carrying names + matched-atom substructure - proving the catalog
   is actually loaded and matching, not silently empty.
3. **A clean molecule** (ethane) returns ``tox_alert_hit=False`` and ``tox_alert_count == 0`` with an
   empty match list.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.schemas import OutputRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO_ROOT / "endpoints" / "toxicity" / "toxicophores"
MANIFEST = MODEL_DIR / "pixi.toml"
RUN_PY = MODEL_DIR / "run.py"

CATALOG_NAME = "BRENK"  # the single documented toxicity alert catalog (see the adapter README)


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


def _predict(smiles: str, tmp_path: Path) -> OutputRecord:
    """Drive the adapter on one SMILES and return the validated OutputRecord."""
    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps({"smiles": smiles, "mol_id": "case"}), encoding="utf-8")
    _run_adapter_on_box(in_path, out_path)
    assert out_path.exists(), "adapter exited 0 but wrote no output file"
    return OutputRecord.model_validate(json.loads(out_path.read_text(encoding="utf-8")))


def _assert_consistent(record: OutputRecord) -> None:
    """The fields must be self-consistent: hit iff count > 0, raw match-list length == count, catalog set."""
    hit = record.endpoint_values["tox_alert_hit"]
    count = record.endpoint_values["tox_alert_count"]
    assert record.endpoint_values["catalog"] == CATALOG_NAME, (
        f"catalog {record.endpoint_values['catalog']!r} != documented {CATALOG_NAME!r}"
    )
    assert isinstance(hit, bool), f"tox_alert_hit not a bool: {hit!r}"
    assert isinstance(count, int) and count >= 0, f"tox_alert_count not a non-negative int: {count!r}"
    assert hit == (count > 0), f"tox_alert_hit ({hit}) inconsistent with tox_alert_count ({count})"
    matches = record.raw["tox_alert_matches"]
    assert isinstance(matches, list) and len(matches) == count, (
        f"tox_alert_matches length {len(matches)} != tox_alert_count {count}"
    )
    names = record.raw["tox_alert_names"]
    assert isinstance(names, list) and len(names) == count, (
        f"tox_alert_names length {len(names)} != tox_alert_count {count}"
    )
    for entry in matches:
        assert entry["name"], f"matched entry missing a name: {entry!r}"
        assert isinstance(entry["atoms"], list), f"matched entry missing atom list: {entry!r}"


@pytest.mark.model
def test_toxicophores_smoke_fto43(fto43_input: dict[str, str], tmp_path: Path) -> None:
    """FTO-43 fixture -> the adapter -> a valid OutputRecord with the three consistent fields."""
    in_path = tmp_path / "input.json"
    out_path = tmp_path / "output.json"
    in_path.write_text(json.dumps(fto43_input), encoding="utf-8")

    _run_adapter_on_box(in_path, out_path)

    assert out_path.exists(), "adapter exited 0 but wrote no output file"
    record = OutputRecord.model_validate(json.loads(out_path.read_text(encoding="utf-8")))
    assert record.model == "toxicophores"
    assert record.uncertainty is None  # rule: deterministic
    assert set(record.endpoint_values) == {"tox_alert_hit", "tox_alert_count", "catalog"}
    _assert_consistent(record)
    assert record.raw.get("soft_filter") is True  # over-flags; look-closer, not auto-kill (docs §28)
    assert record.raw.get("intent") == "toxicity"  # distinct from t17 pains_brenk by intent


@pytest.mark.model
def test_toxicophores_brenk_positive_nitro(tmp_path: Path) -> None:
    """Nitrobenzene carries a BRENK ``nitro_group`` alert: hit True, count >= 1, names + atoms present."""
    record = _predict("[O-][N+](=O)c1ccccc1", tmp_path)  # nitrobenzene
    assert record.endpoint_values["tox_alert_hit"] is True, "nitro compound not flagged (catalog not loaded?)"
    assert record.endpoint_values["tox_alert_count"] >= 1
    _assert_consistent(record)
    names = record.raw["tox_alert_names"]
    assert any(name for name in names), "match carried no alert name"
    assert any(m["atoms"] for m in record.raw["tox_alert_matches"]), "match carried no matched atoms"


@pytest.mark.model
def test_toxicophores_clean_molecule(tmp_path: Path) -> None:
    """A small inert molecule (ethane) trips the catalog nowhere: hit False, count 0, empty lists."""
    record = _predict("CC", tmp_path)  # ethane
    assert record.endpoint_values["tox_alert_hit"] is False
    assert record.endpoint_values["tox_alert_count"] == 0
    _assert_consistent(record)
    assert record.raw["tox_alert_matches"] == [] and record.raw["tox_alert_names"] == []
