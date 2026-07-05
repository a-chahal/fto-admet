#!/usr/bin/env python
"""pbpk transcription helper - PBPK is an OUT-OF-BAND INTEGRATOR (R 4.x + .NET 8 + OSP binaries).

PBPK (Open Systems Pharmacology / PK-Sim) is **not a per-molecule SMILES->number predictor**. It is a
whole-body concentration-time INTEGRATOR: a PK-Sim model is parameterized with *other endpoints' outputs*
(clearance, fraction unbound, permeability, logP, pKa) and simulated with the ``ospsuite`` R package to
produce a C(t) profile from which the modeler extracts exposure metrics (Cmax, AUC, tmax, ...). See
``README.md`` and ``pbpk.R`` for the install recipe, the parameterization mapping, and the simulation
call. The runtime is R + .NET + OSP binaries, which cannot live in a pixi env (CLAUDE.md §4: non-Python
heavy runtimes isolate OUTSIDE pixi), so PBPK has ``env_manifest = None`` in the registry, is
``in_bulk_loop = False`` (shortlist only), and is NEVER driven through ``core.dispatch``.

THIS file is the thin ledger-transcription helper only. It takes the metrics a modeler has ALREADY
extracted from an ``ospsuite`` run (a small JSON of Cmax / AUC / ... plus the parameterization that fed the
model) and writes a single ``core.schemas.OutputRecord``-shaped JSON so a PBPK result enters the ledger in
the same shape every other adapter emits. It runs NO simulation: no R, no .NET, no OSP, no chemistry. It is
pure stdlib (``json`` + ``argparse``) and does NOT import ``core`` (it has no pixi env, exactly like the
OPERA out-of-band adapter); the dispatcher/ledger validates the emitted JSON against the real schema when it
is collected.

Uniform model CLI (CLAUDE.md §2), adapted for an integrator (``--input`` is EXTRACTED METRICS, not SMILES):

    python run.py --input <metrics.json> --output <record.json> [--gpu N]

``--gpu`` is accepted and ignored (the OSP simulation is CPU; the flag is present only for CLI uniformity).

Input (``--input``) - the metrics a modeler transcribed off an ospsuite simulation:

    {
      "mol_id": "FTO-43",
      "metrics": {
        "Cmax":      {"value": 1.85, "unit": "uM"},
        "AUC_0_inf": {"value": 12.4, "unit": "uM*h"},
        "tmax":      {"value": 1.5,  "unit": "h"},
        "t_half":    {"value": 4.2,  "unit": "h"},
        "Kp_uu_brain": 0.34
      },
      "parameterization": {                       # which upstream endpoint output fed which PK-Sim input
        "lipophilicity_logP":     {"source_model": "opera",     "field": "LogP",  "value": 3.42},
        "fraction_unbound":       {"source_model": "ochem_ppb", "field": "fu",    "value": 0.12},
        "intestinal_permeability":{"source_model": "opera",     "field": "Caco2", "value": -4.6},
        "hepatic_clint":          {"source_model": "opera",     "field": "Clint", "value": 15.4}
      },
      "simulation": {"dose_mg": 100, "route": "iv", "species": "human",
                     "model_file": "fto43_pbpk.pkml", "ospsuite_version": "12.x"},
      "uncertainty": {"extra": {"gsa_cmax_range": "1.5-2.3 uM"}}   # OPTIONAL: modeler-supplied sensitivity
    }

A metric may be a bare number (``"Kp_uu_brain": 0.34``) or a ``{"value", "unit"}`` object. Numeric metric
values land in ``endpoint_values``; their units, the parameterization provenance, and the simulation
metadata are preserved verbatim in ``raw`` (raw-output caching, CLAUDE.md §4a - a PBPK result must be
reconstructible). Nothing is invented: there is NO fixed PBPK output schema (IO_SPEC §1 #12), so whatever
metrics the modeler extracts are what gets transcribed.

Uncertainty (CLAUDE.md §3): PBPK has no NATIVE per-prediction uncertainty; its uncertainty is propagated
from upstream parameter uncertainty and any global-sensitivity analysis the modeler runs. The reserved
``uncertainty`` envelope is therefore populated ONLY from a modeler-supplied ``uncertainty`` block (mapped
into ``extra``); it is left ``None`` otherwise (no fabricated sigma).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

MODEL = "pbpk"

# Keys of the input object that are NOT metrics (everything else under "metrics" is a metric).
_RESERVED_INPUT_KEYS = frozenset(
    {"mol_id", "metrics", "parameterization", "simulation", "uncertainty", "smiles", "standardized", "standardizer"}
)


def _provenance() -> dict[str, Any]:
    """Provenance stamped on the emitted record. No version is fabricated: the ``ospsuite`` version and
    the source model file are carried through from the input's ``simulation`` block (see :func:`build_record`).
    """
    return {
        "model": MODEL,
        "method": "whole-body PBPK integrator (PK-Sim / MoBi); parameterized from other endpoints' outputs "
        "(CL, fu, permeability, logP, pKa), simulated via the ospsuite R package; NOT a SMILES->number predictor",
        "runtime": "OUT-OF-BAND: R 4.x + .NET 8 + OSP Suite binaries; env_manifest=None, in_bulk_loop=False "
        "(shortlist only), never driven through core.dispatch. This file only transcribes extracted metrics.",
        "citation": "Lippert J, et al. Open Systems Pharmacology community: PK-Sim/MoBi. CPT Pharmacometrics "
        "Syst Pharmacol 2019, 8:878-882. doi:10.1002/psp4.12473 (PMC6930856).",
        "license": "Open Systems Pharmacology Suite (PK-Sim/MoBi/ospsuite): GPLv2, free including commercial use.",
        "source": "github.com/Open-Systems-Pharmacology (Suite, PK-Sim, ospsuite)",
    }


def _f(value: Any) -> float | None:
    """Coerce a metric cell to a finite float, or ``None`` for missing / non-numeric / NaN / inf."""
    if value is None or isinstance(value, bool):
        return None
    s = str(value).strip()
    if not s or s.lower() in ("nan", "na", "null", "none", "-"):
        return None
    try:
        f = float(s)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _metric(raw: Any) -> tuple[float | None, str | None]:
    """Normalize one metric to ``(value, unit)``. Accepts a bare number or a ``{"value", "unit"}`` object.

    A metric with no numeric value (missing / NaN / non-numeric) yields ``(None, unit)`` - it is preserved as
    a null in ``endpoint_values`` rather than dropped, so the record never silently loses a reported metric.
    """
    if isinstance(raw, dict):
        return _f(raw.get("value")), (raw.get("unit") if raw.get("unit") not in ("", None) else None)
    return _f(raw), None


def build_record(data: dict[str, Any]) -> dict[str, Any]:
    """Turn one extracted-metrics input dict into a ``core.schemas.OutputRecord``-shaped dict.

    THE code deliverable. Pure stdlib; runs no simulation. Numeric metric values -> ``endpoint_values``;
    their units, the upstream parameterization, and the simulation metadata -> ``raw`` (cached verbatim);
    a modeler-supplied ``uncertainty`` block -> the reserved ``uncertainty`` envelope (never fabricated).
    """
    if not isinstance(data, dict):
        raise ValueError("pbpk metrics input must be a JSON object")

    # Metrics live under "metrics"; if that key is absent, treat every non-reserved top-level key as a metric
    # so a flat {"Cmax": 1.85, ...} payload is also accepted.
    metrics_in = data.get("metrics")
    if metrics_in is None:
        metrics_in = {k: v for k, v in data.items() if k not in _RESERVED_INPUT_KEYS}
    if not isinstance(metrics_in, dict) or not metrics_in:
        raise ValueError("pbpk metrics input has no 'metrics' (or top-level metric keys) to transcribe")

    endpoint_values: dict[str, float | None] = {}
    units: dict[str, str] = {}
    for name, raw_val in metrics_in.items():
        value, unit = _metric(raw_val)
        endpoint_values[name] = value
        if unit is not None:
            units[name] = unit

    raw: dict[str, Any] = {
        "molecule_id": data.get("mol_id"),
        "kind": "pbpk_simulation_metrics",
        "units": units,
        "parameterization": data.get("parameterization", {}),
        "simulation": data.get("simulation", {}),
        "metrics_raw": metrics_in,
    }

    # Reserved uncertainty envelope: populated only if the modeler supplied one (e.g. a GSA range). PBPK has
    # no native per-prediction sigma, so nothing is fabricated (CLAUDE.md §3).
    uncertainty: dict[str, Any] | None = None
    unc_in = data.get("uncertainty")
    if isinstance(unc_in, dict) and unc_in:
        uncertainty = {
            "aleatoric": _f(unc_in.get("aleatoric")),
            "epistemic": _f(unc_in.get("epistemic")),
            "fold_error_low": _f(unc_in.get("fold_error_low")),
            "fold_error_high": _f(unc_in.get("fold_error_high")),
            "extra": dict(unc_in.get("extra", {})) if isinstance(unc_in.get("extra"), dict) else {},
        }

    record: dict[str, Any] = {
        "model": MODEL,
        "endpoint_values": endpoint_values,
        "uncertainty": uncertainty,
        "raw": raw,
        "provenance": _provenance(),
    }
    return record


def parse_input(text: str) -> list[dict[str, Any]]:
    """Parse ``--input`` (one metrics object or a JSON array of them) into a list of records to transcribe."""
    data = json.loads(text)
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return list(data)
    raise ValueError("pbpk input must be a JSON object or an array of objects")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PBPK ledger-transcription helper (uniform model CLI).")
    parser.add_argument("--input", required=True, type=Path, help="extracted PBPK metrics JSON (object or array)")
    parser.add_argument("--output", required=True, type=Path, help="where to write the OutputRecord JSON")
    parser.add_argument("--gpu", type=int, default=None, help="ignored (OSP simulation is CPU); present for the uniform CLI")
    args = parser.parse_args(argv)

    raw_text = args.input.read_text(encoding="utf-8")
    input_is_object = isinstance(json.loads(raw_text), dict)
    records = parse_input(raw_text)
    outputs = [build_record(rec) for rec in records]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    # One input object -> one object; an input array -> an array (mirrors the input shape, like OPERA).
    payload: Any = outputs[0] if input_is_object else outputs
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
