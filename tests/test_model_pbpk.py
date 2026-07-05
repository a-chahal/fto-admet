"""Unit tests for the pbpk transcription helper - the OUT-OF-BAND INTEGRATOR (R 4.x + .NET 8 + OSP).

PBPK is not a pixi model and not a per-molecule predictor: it is a whole-body concentration-time INTEGRATOR
parameterized from OTHER endpoints' outputs and simulated with the ``ospsuite`` R package (CLAUDE.md §4,
IO_SPEC §1 #12). The code deliverable is a thin ledger-transcription helper (``run.py`` :func:`build_record`)
that turns metrics a modeler ALREADY extracted from an ospsuite run (Cmax / AUC / ...) into a
``core.schemas.OutputRecord``. Because the helper runs no simulation and is pure stdlib, these tests run on
the LAPTOP fast tier - no box, no OSP, no R/.NET (task done-criterion). ``run.py`` is imported directly by
path (it has no pixi env to shell into, exactly like the OPERA out-of-band adapter).

The sample metrics are a format-faithful SYNTHETIC ospsuite extraction: their structure matches what
``pbpk.R`` writes, the values are placeholders (NOT a real PBPK run - that is the ``needs_aaran`` residue
once the OSP runtime is installed). The tests assert TRANSCRIPTION and SHAPE, never pharmacokinetic values.

What is checked (the done-criteria):
1. A metrics object transcribes to one valid OutputRecord: numeric metrics -> ``endpoint_values``, units +
   parameterization + simulation metadata preserved in ``raw`` (raw-output caching, CLAUDE.md §4a).
2. Bare-number metrics and ``{"value","unit"}`` metrics both work; a NaN/None metric maps to a null value
   (one bad metric never crashes the transcription).
3. The reserved ``uncertainty`` envelope is populated ONLY from a modeler-supplied block, and is ``None``
   otherwise (PBPK has no native sigma - nothing is fabricated, CLAUDE.md §3).
4. The provenance records PBPK as an out-of-band integrator (env_manifest None, not in the bulk loop).
5. The uniform CLI writes a valid output file (object in -> object out; array in -> array out).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from core.schemas import OutputRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO_ROOT / "endpoints" / "clearance" / "pbpk"
RUN_PY = MODEL_DIR / "run.py"


def _load_run():
    """Import the out-of-band helper module directly by path (it has no pixi env / package to import)."""
    spec = importlib.util.spec_from_file_location("pbpk_run", RUN_PY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run = _load_run()


def _sample_metrics() -> dict:
    """A format-faithful synthetic ospsuite extraction (placeholder values; NOT a real PBPK run)."""
    return {
        "mol_id": "FTO-43",
        "metrics": {
            "Cmax": {"value": 1.85, "unit": "uM"},
            "AUC_0_inf": {"value": 12.4, "unit": "uM*h"},
            "tmax": {"value": 1.5, "unit": "h"},
            "t_half": {"value": 4.2, "unit": "h"},
            "Kp_uu_brain": 0.34,  # bare number, dimensionless
        },
        "parameterization": {
            "lipophilicity_logP": {"source_model": "opera", "field": "LogP", "value": 3.42},
            "fraction_unbound": {"source_model": "ochem_ppb", "field": "fu", "value": 0.12},
            "intestinal_permeability": {"source_model": "opera", "field": "Caco2", "value": -4.6},
            "hepatic_clint": {"source_model": "opera", "field": "Clint", "value": 15.4},
        },
        "simulation": {
            "dose_mg": 100,
            "route": "iv",
            "species": "human",
            "model_file": "fto43_pbpk.pkml",
            "ospsuite_version": "12.x",
        },
    }


def test_sample_transcribes_to_valid_output_record() -> None:
    """The metrics object transcribes to one valid OutputRecord with all five metrics in endpoint_values."""
    rec = run.build_record(_sample_metrics())
    model = OutputRecord.model_validate(rec)  # raises on any schema violation
    assert model.model == "pbpk"
    assert set(model.endpoint_values) == {"Cmax", "AUC_0_inf", "tmax", "t_half", "Kp_uu_brain"}
    assert model.endpoint_values["Cmax"] == 1.85
    assert model.endpoint_values["Kp_uu_brain"] == 0.34  # bare-number metric parsed


def test_units_and_parameterization_preserved_in_raw() -> None:
    """Units, the upstream parameterization, and the simulation metadata are cached verbatim in raw."""
    rec = run.build_record(_sample_metrics())
    raw = rec["raw"]
    assert raw["molecule_id"] == "FTO-43"
    assert raw["units"]["Cmax"] == "uM"
    assert raw["units"]["AUC_0_inf"] == "uM*h"
    assert "Kp_uu_brain" not in raw["units"]  # dimensionless bare number carries no unit
    # Parameterization provenance is kept so the ledger record is reconstructible (CLAUDE.md §4a).
    assert raw["parameterization"]["fraction_unbound"]["source_model"] == "ochem_ppb"
    assert raw["parameterization"]["hepatic_clint"]["field"] == "Clint"
    assert raw["simulation"]["model_file"] == "fto43_pbpk.pkml"
    assert raw["kind"] == "pbpk_simulation_metrics"


def test_nan_and_missing_metric_maps_to_null() -> None:
    """A NaN / non-numeric metric maps to a null value (one bad metric never crashes the transcription)."""
    data = {
        "mol_id": "X1",
        "metrics": {
            "Cmax": {"value": 2.0, "unit": "uM"},
            "AUC_0_inf": {"value": "NaN", "unit": "uM*h"},  # failed integration -> null
            "t_half": None,
        },
    }
    rec = run.build_record(data)
    model = OutputRecord.model_validate(rec)
    assert model.endpoint_values["Cmax"] == 2.0
    assert model.endpoint_values["AUC_0_inf"] is None
    assert model.endpoint_values["t_half"] is None
    # The unit of the null AUC is still preserved.
    assert rec["raw"]["units"]["AUC_0_inf"] == "uM*h"


def test_uncertainty_is_none_without_modeler_block() -> None:
    """PBPK has no native sigma: uncertainty stays None unless the modeler supplies one (no fabrication)."""
    rec = run.build_record(_sample_metrics())
    assert rec["uncertainty"] is None
    assert OutputRecord.model_validate(rec).uncertainty is None


def test_uncertainty_populated_from_modeler_block() -> None:
    """A modeler-supplied uncertainty block (e.g. a GSA range) maps into the reserved envelope's extra."""
    data = _sample_metrics()
    data["uncertainty"] = {"fold_error_low": 0.6, "fold_error_high": 1.7, "extra": {"gsa_cmax_range": "1.5-2.3 uM"}}
    rec = run.build_record(data)
    model = OutputRecord.model_validate(rec)
    assert model.uncertainty is not None
    assert model.uncertainty.fold_error_low == 0.6
    assert model.uncertainty.fold_error_high == 1.7
    assert model.uncertainty.extra["gsa_cmax_range"] == "1.5-2.3 uM"


def test_flat_metrics_accepted() -> None:
    """A flat {metric: number} payload (no 'metrics' wrapper) is also accepted, minus reserved keys."""
    rec = run.build_record({"mol_id": "X2", "Cmax": 3.1, "AUC_0_t": 20.5})
    model = OutputRecord.model_validate(rec)
    assert model.endpoint_values == {"Cmax": 3.1, "AUC_0_t": 20.5}
    assert rec["raw"]["molecule_id"] == "X2"  # mol_id is reserved, not treated as a metric


def test_provenance_marks_out_of_band_integrator() -> None:
    """Provenance records PBPK as an out-of-band R/.NET integrator, not a bulk-loop SMILES predictor."""
    prov = run.build_record(_sample_metrics())["provenance"]
    assert prov["model"] == "pbpk"
    assert "integrator" in prov["method"].lower()
    assert "OUT-OF-BAND" in prov["runtime"]
    assert "in_bulk_loop=False" in prov["runtime"]
    assert "Open-Systems-Pharmacology" in prov["source"]


def test_cli_object_in_object_out(tmp_path: Path) -> None:
    """The uniform CLI writes a valid record: a single metrics object in -> a single OutputRecord out."""
    in_path = tmp_path / "metrics.json"
    out_path = tmp_path / "record.json"
    in_path.write_text(json.dumps(_sample_metrics()), encoding="utf-8")

    rc = run.main(["--input", str(in_path), "--output", str(out_path), "--gpu", "0"])
    assert rc == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    OutputRecord.model_validate(payload)


def test_cli_array_in_array_out(tmp_path: Path) -> None:
    """An input array (a shortlist batch) transcribes to an output array of valid records."""
    in_path = tmp_path / "metrics.json"
    out_path = tmp_path / "record.json"
    in_path.write_text(json.dumps([_sample_metrics(), {"mol_id": "X3", "metrics": {"Cmax": 0.9}}]), encoding="utf-8")

    rc = run.main(["--input", str(in_path), "--output", str(out_path)])
    assert rc == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert isinstance(payload, list) and len(payload) == 2
    for rec in payload:
        OutputRecord.model_validate(rec)
