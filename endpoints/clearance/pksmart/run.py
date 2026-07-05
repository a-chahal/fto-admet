#!/usr/bin/env python
"""pksmart adapter - the first REAL isolated env (subprocess + box lock + native uncertainty).

Uniform model CLI (CLAUDE.md §2, SETTLED §6):

    python run.py --input <path> --output <path> [--gpu N]

This runs in the model's ISOLATED pixi env (pksmart + mordredcommunity + a pinned scikit-learn) and so
CANNOT import ``core`` (a separate env). It emits plain JSON matching ``core.schemas.OutputRecord``; the
dispatcher validates that JSON against the real schema on collection. It follows the t10 folder/adapter
template and adds a genuine upstream env plus the reserved uncertainty fields (PKSmart emits a fold-error).

Endpoint: clearance. PKSmart is a two-stage RF (animal PK -> human RF) predicting human i.v. PK. We map
its five human parameters into ``endpoint_values`` with units baked into the key names (CLAUDE.md §4):

    endpoint_values = {
        "CL_mL_min_kg": <total body clearance, mL/min/kg, UP = faster clearance>,  # the FTO liability
        "VDss_L_kg":    <volume of distribution at steady state, L/kg, UP = more tissue distribution>,
        "t_half_h":     <half-life, h, UP = longer>,
        "fu":           <fraction unbound in plasma, 0-1, UP = more free>,
        "MRT_h":        <mean residence time, h, UP = longer>,
    }

CL is WEAK (R^2=0.31, GMFE ~2.43): it is ranking-only. We emit CL faithfully but PKSmart documents a
per-parameter fold-error, so we surface it: the CL fold-error interval goes in the reserved
``uncertainty.fold_error_low`` / ``uncertainty.fold_error_high`` (the lower/upper prediction bounds), and
every parameter's fold factor + the native applicability-domain alert are kept in ``uncertainty.extra`` so
a downstream consumer never has to re-touch this adapter. NEVER combine this CL with the other clearance
units downstream (F-3) - that harmonization is t43's job; here we only emit CL + its fold-error.

The mordred descriptors are computed by ``mordredcommunity`` (the maintained fork), NOT upstream
``mordred`` (unmaintained on modern Python): the isolated env pins mordredcommunity + scikit-learn to the
versions that load PKSmart's shipped RF pickles (see pixi.toml / README).

``--gpu`` is accepted and ignored (``requires_gpu=False``); PKSmart is CPU-only. The uniform CLI is the
same for every model so the dispatcher can build one command.

Robustness: an unparseable SMILES yields a per-record result with null values and the reason in ``raw``
(PKSmart raises a TypeError from RDKit on a bad parse) - one bad molecule never sinks a bulk batch.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

# PKSmart is chatty (loguru + tabulate tables on import/predict). Silence it so nothing pollutes stdout;
# the real output is the JSON file written to --output.
warnings.filterwarnings("ignore")
try:  # pragma: no cover - defensive: loguru is a hard dep of pksmart, but never let logging setup crash a run
    from loguru import logger

    logger.remove()
except Exception:  # pragma: no cover
    pass

import pksmart  # noqa: E402  (imported after logging is quieted)

MODEL = "pksmart"

# The five human PK columns predict_pk_params() actually returns, mapped to our units-baked-in keys.
# Verified live from the installed pksmart v3.0.1 (the repo's external-test CSV names differ from the
# in-memory DataFrame columns, so these are read from a real run, not the CSV template - see README).
VALUE_COLUMNS: dict[str, str] = {
    "CL_mL_min_kg": "CL_mL_min_kg",  # total body clearance, mL/min/kg, UP = faster (FTO liability; anchor ~89.6)
    "VDss_L_kg": "VDss_L_kg",  # volume of distribution (ss), L/kg
    "t_half_h": "thalf_hr",  # half-life, h
    "fu": "Fraction_unbound_in_plasma_(fup)",  # fraction unbound in plasma, 0-1
    "MRT_h": "MRT_hr",  # mean residence time, h
}

# Native per-parameter fold-error columns (the DIRECT uncertainty PKSmart documents; widens out of domain).
CL_FOLD_ERROR = "Clearance_(CL)_folderror"
CL_LOWER = "Clearance_(CL)_lowerbound"
CL_UPPER = "Clearance_(CL)_upperbound"
FOLD_ERROR_COLUMNS: dict[str, str] = {
    "cl_fold_error": CL_FOLD_ERROR,
    "vdss_fold_error": "Volume_of_distribution_(VDss)_folderror",
    "fup_fold_error": "Fraction_unbound_in_plasma_(fup)_folderror",
    "mrt_fold_error": "Mean_Residence_Time_(MRT)_folderror",
    "thalf_fold_error": "Half_life_(thalf)_folderror",
}


def _pksmart_version() -> str:
    """Read the installed pksmart version live (not fabricated); pksmart exposes no ``__version__``."""
    try:
        return version("pksmart")
    except PackageNotFoundError:  # pragma: no cover
        return "unknown"


def _provenance() -> dict[str, Any]:
    """Provenance stamped onto every emitted record. Versions are read live, never hardcoded."""
    return {
        "model": MODEL,
        "method": "PKSmart two-stage random forest (animal PK -> human RF); Morgan FP + Mordred descriptors",
        "pksmart_version": _pksmart_version(),
        "mordred_impl": "mordredcommunity (maintained fork; NOT upstream mordred)",
        "citation": "Seal S, et al. PKSmart. J Cheminform 2025, 17. doi:10.1186/s13321-025-01066-5",
        "license": "code: open (CODE-PKG); see upstream srijitseal/PKSmart",
    }


def parse_inputs(text: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse the ``--input`` payload into ``(records, single)`` (identical contract to the t10 template).

    Accepts the three forms core may feed an adapter:
    - a single ``InputRecord`` JSON object -> ``single=True``,
    - a JSON array of ``InputRecord`` objects (a bulk batch) -> ``single=False``,
    - a ``.smi`` file (``<SMILES><whitespace><title>`` per line, ``#`` comments) -> ``single=False``.
    """
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        data = json.loads(stripped)
        if isinstance(data, dict):
            return [data], True
        if isinstance(data, list):
            return list(data), False
        raise ValueError("input JSON must be an object or an array of objects")

    records: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        mol_id = parts[1] if len(parts) > 1 else None
        records.append({"smiles": parts[0], "mol_id": mol_id})
    return records, False


def _f(value: Any) -> float | None:
    """Coerce a pandas/numpy scalar to a plain finite float, or ``None`` if missing/non-finite."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def record_for(rec: dict[str, Any]) -> dict[str, Any]:
    """Compute one ``OutputRecord``-shaped dict for a single input record.

    An unparseable/empty SMILES returns a valid record with null ``endpoint_values`` and the reason in
    ``raw`` rather than raising: PKSmart raises a ``TypeError`` from RDKit on a bad parse, so we catch it
    (the uniform contract's per-record error behavior - one bad molecule never sinks a bulk batch).
    """
    smiles = str(rec.get("smiles") or "").strip()
    mol_id = rec.get("mol_id")
    base: dict[str, Any] = {"model": MODEL, "provenance": _provenance()}

    if not smiles:
        return {
            **base,
            "endpoint_values": {k: None for k in VALUE_COLUMNS},
            "uncertainty": None,
            "raw": {"error": "empty SMILES", "smiles": smiles, "mol_id": mol_id},
        }

    try:
        df = pksmart.predict_pk_params(smiles)
        row = df.iloc[0].to_dict()
    except Exception as exc:  # noqa: BLE001 - per-record error surfaced in raw, not raised
        return {
            **base,
            "endpoint_values": {k: None for k in VALUE_COLUMNS},
            "uncertainty": None,
            "raw": {
                "error": f"pksmart.predict_pk_params failed: {type(exc).__name__}: {exc}",
                "smiles": smiles,
                "mol_id": mol_id,
            },
        }

    endpoint_values = {key: _f(row.get(col)) for key, col in VALUE_COLUMNS.items()}

    # Native uncertainty: CL fold-error interval into the reserved fields; every parameter's fold factor
    # and the applicability-domain alert into extra so nothing native is lost (schema rule, CLAUDE.md §3).
    ad_alert = str(row.get("comments") or "").strip()
    extra: dict[str, Any] = {name: _f(row.get(col)) for name, col in FOLD_ERROR_COLUMNS.items()}
    extra["ad_alert"] = ad_alert
    uncertainty = {
        "fold_error_low": _f(row.get(CL_LOWER)),
        "fold_error_high": _f(row.get(CL_UPPER)),
        # ad_in_domain records PKSmart's own Tanimoto-to-training alert (a native signal, not a new policy;
        # the operational AD rule is DEFERRED, CLAUDE.md §4a): True when PKSmart raised no OOD alert.
        "ad_in_domain": not ad_alert,
        "extra": extra,
    }

    return {
        **base,
        "endpoint_values": endpoint_values,
        "uncertainty": uncertainty,
        "raw": {
            "smiles": smiles,
            "mol_id": mol_id,
            "smiles_r": row.get("smiles_r"),
            "human": {k: _f(v) for k, v in row.items() if k != "comments" and not k.startswith(("dog_", "monkey_", "rat_"))},
            "animal": {k: _f(v) for k, v in row.items() if k.startswith(("dog_", "monkey_", "rat_"))},
            "ad_alert": ad_alert,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PKSmart human i.v. PK adapter (uniform model CLI).")
    parser.add_argument("--input", required=True, type=Path, help="pipeline input (InputRecord JSON, JSON array, or .smi)")
    parser.add_argument("--output", required=True, type=Path, help="where to write the OutputRecord JSON")
    parser.add_argument("--gpu", type=int, default=None, help="ignored (pksmart is CPU-only); present for the uniform CLI")
    args = parser.parse_args(argv)

    records, single = parse_inputs(args.input.read_text(encoding="utf-8"))
    outputs = [record_for(rec) for rec in records]
    payload: Any = outputs[0] if (single and len(outputs) == 1) else outputs

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
