#!/usr/bin/env python
"""admet_ai adapter - the busiest cross-cutting generalist (ADMET-AI v2, Chemprop v2).

Uniform model CLI (CLAUDE.md §2, SETTLED §6):

    python run.py --input <path> --output <path> [--gpu N]

This runs in the model's ISOLATED pixi env (admet_ai + chemprop v2 + torch) and so CANNOT import
``core`` (a separate env). It emits plain JSON matching ``core.schemas.OutputRecord``; the dispatcher
validates that JSON against the real schema on collection. It follows the t11/t10 folder/adapter template.

ADMET-AI is the busiest cross-cutting model: its registry ``endpoints`` set spans TEN endpoints (triage,
herg, metabolism, clearance, ppb, solubility, lipophilicity, permeability, distribution, toxicity), so we
emit EVERY head and let each endpoint's aggregator pick the fields it needs.

WHAT WE EMIT
------------
``raw.columns`` - the verbatim, complete ADMET-AI output for the molecule: all ~8 physicochemical props,
the 3 structural-alert counts, every classification head (incl. ``hERG`` / ``BBB_Martins`` /
``Pgp_Broccatelli`` / the CYP heads / the 12 Tox21 pathway heads), every regression head, and each
``<property>_drugbank_approved_percentile`` companion. Nothing upstream is dropped from ``raw``.

``endpoint_values`` - only the PROMOTED, usable heads: every prediction head EXCEPT the two the model
itself reports as unusable, and excluding the ``_drugbank_approved_percentile`` context companions (kept in
``raw`` only). The excluded heads are, per F-17 (IO_SPEC §3, verified from admet_ai/resources/data/admet.csv):

  - ``VDss_Lombardo``  (R^2 = -1.21, WORSE than predicting the mean) -> NEVER reaches endpoint_values
  - ``Half_Life_Obach`` (R^2 = -2.39, WORSE than predicting the mean) -> NEVER reaches endpoint_values

Both stay in ``raw.columns`` and are additionally surfaced under ``raw.excluded_r2_negative`` tagged so
nothing downstream can consume them by accident (CLAUDE.md §4).

``raw.head_flags`` - per-head advisory tags a downstream aggregator can read without re-touching this
adapter: the two clearance heads are LOW-WEIGHT / QUALITATIVE only (R^2 ~ 0.26 / 0.28), and ``LD50_Zhu``
is ``log(1/(mol/kg))`` (UP = MORE toxic) which is NOT comparable to ProTox's mg/kg (CLAUDE.md §4, F-5).

``uncertainty = None`` per record. ADMET-AI v2 has NO native per-prediction uncertainty field (IO_SPEC
§1 #1: "No native per-prediction uncertainty field -> uncertainty is INDIRECT"). Its uncertainty signal is
INDIRECT cross-model spread, computed later at aggregation, so there is nothing DIRECT to put in the
reserved ``Uncertainty`` envelope here. The per-head weight/exclusion tags are metadata (they describe the
head's reliability, not a per-molecule uncertainty), so they live in ``raw.head_flags`` / ``raw.excluded_*``,
keeping ``uncertainty`` faithfully ``None``.

UNITS (baked per IO_SPEC §1 #1; the key names are ADMET-AI's canonical column names so aggregators can pick
them by name): ``PPBR_AZ`` = % bound; ``Clearance_Hepatocyte_AZ`` = uL/min/10^6 cells;
``Clearance_Microsome_AZ`` = uL/min/mg; ``LD50_Zhu`` = log(1/(mol/kg)) (UP = more toxic);
``Solubility_AqSolDB`` = log mol/L; ``Lipophilicity_AstraZeneca`` = logD7.4; ``Caco2_Wang`` = log Papp cm/s.
Classification heads are probabilities in [0, 1] = P(named positive class). See README for the full table.

v2 != v1: these are the RETRAINED v2 heads (Chemprop v2, no RDKit fingerprints). Predictions do NOT exactly
match the v1 paper or the live greenstonebio web server (both still v1). Recorded in the README.

F-16 (input standardization) is DEFERRED (CLAUDE.md §4a): this adapter feeds each model the single canonical
SMILES ``core`` hands it, UNMODIFIED. ADMET-AI does its own internal RDKit parse/canonicalization but has no
documented desalting/protonation step, so on the FTO di-cation the pipeline must feed a neutralized parent
upstream. We do NOT silently pick a protonation state here; we flag it (README) and leave it to core.

``--gpu``: honored via ``CUDA_VISIBLE_DEVICES`` set BEFORE torch/admet_ai import. Given ``--gpu N`` -> that
device; omitted -> CPU (``CUDA_VISIBLE_DEVICES=""``), since ``requires_gpu=False`` and a deterministic CPU
run needs no GPU claim. Weights ship inside the admet_ai wheel; no download at run time.

Robustness: an unparseable/empty SMILES yields a per-record result with null ``endpoint_values`` and the
reason in ``raw`` rather than raising - one bad molecule never sinks a bulk batch (uniform-CLI contract).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import warnings
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

MODEL = "admet_ai"

# The two regression heads ADMET-AI v2 reports as worse-than-the-mean (F-17, verified from
# admet_ai/resources/data/admet.csv). These must NEVER reach endpoint_values; they stay in raw, tagged.
EXCLUDED_R2_NEGATIVE: tuple[str, ...] = ("VDss_Lombardo", "Half_Life_Obach")

# Per-head advisory tags for downstream aggregators (metadata, not per-molecule uncertainty).
HEAD_FLAGS: dict[str, str] = {
    "Clearance_Hepatocyte_AZ": "low_weight_qualitative (R^2 ~ 0.26; uL/min/10^6 cells; NEVER combine with other clearance units, F-3)",
    "Clearance_Microsome_AZ": "low_weight_qualitative (R^2 ~ 0.28; uL/min/mg; NEVER combine with other clearance units, F-3)",
    "VDss_Lombardo": "excluded_r2_negative (R^2 = -1.21; kept in raw only, never in endpoint_values, F-17)",
    "Half_Life_Obach": "excluded_r2_negative (R^2 = -2.39; kept in raw only, never in endpoint_values, F-17)",
    "LD50_Zhu": "log(1/(mol/kg)); UP = MORE toxic; NOT comparable to ProTox LD50 (mg/kg), F-5",
    "PPBR_AZ": "percent bound (%); for ppb, normalize /100 to a fraction downstream",
}

_PERCENTILE_SUFFIX = "_drugbank_approved_percentile"


def _configure_device(gpu: int | None) -> str:
    """Pin the compute device via CUDA_VISIBLE_DEVICES BEFORE torch/admet_ai import.

    ``--gpu N`` -> that single device; omitted -> forced CPU (empty string), which is deterministic and
    needs no GPU claim (requires_gpu=False). Must run before importing torch, so it is called at the top
    of ``main`` and the heavy imports are deferred into ``_load_model``.
    """
    if gpu is None:
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        return "cpu"
    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu)
    return f"cuda:{gpu}"


def _admet_ai_version() -> str:
    """Read the installed admet_ai version live (never hardcoded)."""
    for dist in ("admet_ai", "admet-ai"):
        try:
            return version(dist)
        except PackageNotFoundError:
            continue
    return "unknown"


def _provenance(device: str) -> dict[str, Any]:
    """Provenance stamped onto every emitted record. Versions read live, never hardcoded."""
    return {
        "model": MODEL,
        "method": "ADMET-AI v2 (Chemprop v2 D-MPNN, retrained; no RDKit fingerprints); multi-endpoint ADMET",
        "admet_ai_version": _admet_ai_version(),
        "version_note": "v2 heads; predictions differ from the v1 paper/greenstonebio web server (both v1)",
        "device": device,
        "citation": "Swanson K, et al. ADMET-AI. Bioinformatics 40(7):btae416 (2024). doi:10.1093/bioinformatics/btae416",
        "license": "MIT (CODE-PKG); upstream swansonk14/admet_ai",
    }


def parse_inputs(text: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse the ``--input`` payload into ``(records, single)`` (identical contract to t10/t11).

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


def _clean(value: Any) -> Any:
    """Coerce an ADMET-AI cell to a JSON-safe scalar: finite float, int, or None (NaN/inf -> None)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    try:
        f = float(value)
    except (TypeError, ValueError):
        return value  # leave non-numeric (e.g. a string) as-is
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _predict_one(model: Any, smiles: str) -> dict[str, Any]:
    """Run ADMET-AI on ONE SMILES and return the full column dict (cleaned to JSON-safe scalars).

    ``ADMETModel().predict(str)`` returns a dict for a single SMILES; some versions return a 1-row
    DataFrame. Handle both. Per-molecule call gives clean per-record error isolation (the model object is
    loaded once and reused), matching the pksmart template.
    """
    result = model.predict(smiles)
    # DataFrame -> first row as a plain dict; dict -> use directly.
    if hasattr(result, "iloc"):
        row = result.iloc[0].to_dict()
    elif isinstance(result, dict):
        row = dict(result)
    else:
        raise TypeError(f"unexpected predict() return type: {type(result).__name__}")
    return {str(k): _clean(v) for k, v in row.items()}


def record_for(model: Any, rec: dict[str, Any], device: str) -> dict[str, Any]:
    """Compute one ``OutputRecord``-shaped dict for a single input record.

    An unparseable/empty SMILES returns a valid record with null ``endpoint_values`` and the reason in
    ``raw`` rather than raising (per-record error behavior; one bad molecule never sinks a bulk batch).
    """
    smiles = str(rec.get("smiles") or "").strip()
    mol_id = rec.get("mol_id")
    base: dict[str, Any] = {"model": MODEL, "provenance": _provenance(device), "uncertainty": None}

    if not smiles:
        return {
            **base,
            "endpoint_values": {},
            "raw": {"error": "empty SMILES", "smiles": smiles, "mol_id": mol_id},
        }

    try:
        columns = _predict_one(model, smiles)
    except Exception as exc:  # noqa: BLE001 - per-record error surfaced in raw, not raised
        return {
            **base,
            "endpoint_values": {},
            "raw": {
                "error": f"admet_ai predict failed: {type(exc).__name__}: {exc}",
                "smiles": smiles,
                "mol_id": mol_id,
            },
        }

    # Promote only the usable heads: every prediction head EXCEPT the two R^2-negative regression heads and
    # EXCEPT the percentile context companions (those stay in raw.columns only).
    endpoint_values: dict[str, Any] = {
        key: val
        for key, val in columns.items()
        if key not in EXCLUDED_R2_NEGATIVE and not key.endswith(_PERCENTILE_SUFFIX)
    }

    # Keep the excluded heads (+ any percentile companion) visible but quarantined in raw so nothing
    # downstream can promote them by accident.
    excluded: dict[str, Any] = {}
    for key in EXCLUDED_R2_NEGATIVE:
        if key in columns:
            excluded[key] = columns[key]
        pct = f"{key}{_PERCENTILE_SUFFIX}"
        if pct in columns:
            excluded[pct] = columns[pct]

    return {
        **base,
        "endpoint_values": endpoint_values,
        "raw": {
            "smiles": smiles,
            "mol_id": mol_id,
            "columns": columns,  # verbatim, complete: every head + physchem + alerts + percentiles
            "excluded_r2_negative": excluded,  # VDss_Lombardo / Half_Life_Obach kept out of endpoint_values (F-17)
            "head_flags": HEAD_FLAGS,  # low-weight clearance + LD50 direction + PPBR units (advisory metadata)
        },
    }


def _load_model(device: str) -> Any:
    """Import admet_ai (heavy: torch + chemprop) and instantiate ADMETModel once, quietly.

    Imports are deferred here (not module-level) so ``_configure_device`` can pin CUDA_VISIBLE_DEVICES
    before torch initializes. The model object is reused across every record in the batch.
    """
    warnings.filterwarnings("ignore")
    from admet_ai import ADMETModel  # noqa: E402  (imported after device is pinned)

    return ADMETModel()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ADMET-AI v2 cross-cutting generalist adapter (uniform model CLI).")
    parser.add_argument("--input", required=True, type=Path, help="pipeline input (InputRecord JSON, JSON array, or .smi)")
    parser.add_argument("--output", required=True, type=Path, help="where to write the OutputRecord JSON")
    parser.add_argument("--gpu", type=int, default=None, help="CUDA device index; omitted -> CPU (requires_gpu=False)")
    args = parser.parse_args(argv)

    device = _configure_device(args.gpu)
    records, single = parse_inputs(args.input.read_text(encoding="utf-8"))

    model = _load_model(device)
    outputs = [record_for(model, rec, device) for rec in records]
    payload: Any = outputs[0] if (single and len(outputs) == 1) else outputs

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
