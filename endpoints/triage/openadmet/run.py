#!/usr/bin/env python
"""openadmet adapter - the CYP-metabolism REFERENCE (not a gate authority).

Uniform model CLI (CLAUDE.md §2, SETTLED §6):

    python run.py --input <path> --output <path> [--gpu N]

This runs in the model's ISOLATED pixi env (openadmet-models + chemprop + torch) and so CANNOT import
``core`` (a separate env). It emits plain JSON matching ``core.schemas.OutputRecord``; the dispatcher
validates that JSON against the real schema on collection. It follows the t11 folder/adapter template.

ROLE: REFERENCE, NOT AUTHORITY (t22 landmine, IO_SPEC §1 #3). OpenADMET's own inaugural-release write-up
reports random-split R^2 ~ 0.6 but cluster-split R^2 ~ 0.1, i.e. poor generalization to out-of-distribution
chemical space (exactly the FTO oxetane chemotype). So its ``endpoints`` set is ``{triage}`` and it is a
CYP cross-check only: it must NEVER feed a gate. Its outputs live in ``endpoint_values`` for reference.

WHAT OPENADMET IS. A modeling FRAMEWORK (curate -> train via "anvil" YAML recipes -> infer), not a turnkey
``predict(smiles)``. There is no single generalist head like ADMET-AI. We run the released BASELINE model
directories through the library's own inference entry point
(``openadmet.models.inference.inference.predict``), which appends, per model task, a fixed pair of columns:

    OADMET_PRED_{tag}_{task}  - the prediction (classification tasks route through predict_proba -> a
                                probability; regression tasks emit the value).
    OADMET_STD_{tag}_{task}   - the per-prediction standard deviation.

We map every ``OADMET_PRED_*`` column into ``endpoint_values`` (keyed by the verbatim column name so a
downstream consumer can pick a specific CYP task by name), and every ``OADMET_STD_*`` column into the
reserved ``uncertainty`` envelope (``uncertainty.extra``, keyed by the verbatim STD column name).

NATIVE sigma IS ENSEMBLE-ONLY (verified, corrects the task premise). ``inference.py`` returns a real
per-prediction std ONLY for an ENSEMBLE model dir (``std = model.predict(..., return_std=True)``); for a
SINGLE model it sets ``std = np.full(shape, np.nan)``. The PUBLICLY RELEASED baselines
(``openadmet/cyp1a2-cyp2d6-cyp3a4-cyp3c9-chemeleon-baseline`` and ``openadmet/pxr-chemeleon-baseline`` on
HuggingFace) are SINGLE CheMeleon models, so their ``OADMET_STD_*`` columns are all NaN and the inaugural
blog states outright that "standard deviation columns are empty because uncertainty cannot be estimated
unless training an ensemble of models". This adapter therefore populates ``uncertainty`` from STD FAITHFULLY:
NaN std -> ``None`` (no fabricated sigma); a real ensemble std -> the actual DIRECT per-prediction sigma. The
STD->uncertainty wiring is fully implemented; whether it carries a number depends on the model dir supplied.
See the README for the release-channel divergence (weights are on HuggingFace, not S3).

MODEL DIRS. Each ``--model-dir`` for ``predict`` is a trained anvil directory (``recipe_components/`` +
serialized weights, optionally ``bootstrap_*`` subdirs for an ensemble). The set to run is configured via
the ``OPENADMET_MODEL_DIRS`` env var (os.pathsep- or comma-separated absolute paths); with none set the
adapter raises a clear error rather than guessing. Weights are fetched out-of-band (HuggingFace git-lfs)
into a ``/zfs`` cache; nothing is downloaded from inside this adapter.

CheMeleon HOME landmine. ``openadmet.models.architecture.chemprop`` downloads the CheMeleon foundation
checkpoint to ``Path.home()/.chemprop`` (Zenodo) if a CheMeleon model is (re)built. ``$HOME`` on the box is
~97% full, so if ``OPENADMET_HOME`` is set we repoint ``$HOME`` at it BEFORE importing openadmet, keeping any
such write on ``/zfs``. Documented in the README.

``--gpu``: ``--gpu N`` pins ``CUDA_VISIBLE_DEVICES=N`` and runs inference with ``accelerator="gpu"``; omitted
-> CPU (``accelerator="cpu"``, ``CUDA_VISIBLE_DEVICES=""``), which is deterministic and needs no GPU claim
(``requires_gpu=False``; reference role does not warrant holding a device).

Robustness: SMILES that OpenADMET cannot featurize are simply absent from the prediction columns for that
row; the per-record output then carries empty ``endpoint_values`` with the reason in ``raw`` rather than
raising - one bad molecule never sinks a bulk batch (uniform-CLI contract).
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

MODEL = "openadmet"

# The column-name prefixes the OpenADMET inference pipeline appends (IO_SPEC §1 #3, verified from
# openadmet/models/inference/inference.py). PRED -> endpoint_values; STD -> uncertainty.
PRED_PREFIX = "OADMET_PRED_"
STD_PREFIX = "OADMET_STD_"

# The SMILES column name we hand OpenADMET's predict(); kept internal so the pipeline's InputRecord shape
# is unchanged. OpenADMET's CLI default is OPENADMET_SMILES, but predict() accepts any input_col.
_INPUT_COL = "OPENADMET_SMILES"


def _configure_home() -> None:
    """Repoint $HOME at OPENADMET_HOME (a /zfs cache) BEFORE importing openadmet, if provided.

    ``openadmet.models.architecture.chemprop`` writes the CheMeleon foundation checkpoint under
    ``Path.home()/.chemprop``; $HOME on the box is ~97% full, so any such write must land on /zfs. Must run
    before the heavy import so ``Path.home()`` resolves to the redirected dir.
    """
    home = os.environ.get("OPENADMET_HOME")
    if home:
        os.environ["HOME"] = home


def _configure_device(gpu: int | None) -> str:
    """Pin the compute device via CUDA_VISIBLE_DEVICES BEFORE torch/openadmet import.

    ``--gpu N`` -> that single device + ``accelerator="gpu"``; omitted -> forced CPU (empty string) +
    ``accelerator="cpu"``, deterministic and needing no GPU claim (requires_gpu=False).
    """
    if gpu is None:
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        return "cpu"
    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu)
    return "gpu"


def _pkg_version(dist: str) -> str:
    """Read an installed package version live (never hardcoded)."""
    try:
        return version(dist)
    except PackageNotFoundError:
        return "unknown"


def _provenance(accelerator: str, model_dirs: list[str]) -> dict[str, Any]:
    """Provenance stamped onto every emitted record. Versions read live, never hardcoded."""
    return {
        "model": MODEL,
        "method": (
            "OpenADMET released baseline models run through openadmet.models.inference.predict; "
            "CYP inhibition/reaction-phenotyping reference (CheMeleon/ChemProp baselines)"
        ),
        "openadmet_models_version": _pkg_version("openadmet-models"),
        "chemprop_version": _pkg_version("chemprop"),
        "model_dirs": model_dirs,
        "role": "REFERENCE, NOT AUTHORITY (cluster-split R^2 ~ 0.1); NOT fed to any gate",
        "uncertainty_note": (
            "OADMET_STD_* is a real per-prediction sigma only for ENSEMBLE model dirs; released baselines "
            "are single CheMeleon models -> STD is NaN -> uncertainty is None (no fabricated sigma)"
        ),
        "weights_note": (
            "released baselines are hosted on HuggingFace git-lfs (openadmet/*-chemeleon-baseline), fetched "
            "out-of-band into a /zfs cache; _download_s3_dir in comparison/posthoc.py is comparison-only"
        ),
        "device": accelerator,
        "citation": "OpenADMET (OMSF/UCSF/Octant/MSKCC). github.com/OpenADMET/openadmet-models; docs.openadmet.org",
        "license": "MIT (CODE-PKG); upstream OpenADMET/openadmet-models",
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


def _resolve_model_dirs() -> list[str]:
    """Return the configured OpenADMET model dirs, or raise a clear error (never guess/fabricate).

    Set via ``OPENADMET_MODEL_DIRS`` (os.pathsep- or comma-separated absolute paths). Each must be a
    trained anvil dir containing ``recipe_components/``. Weights are fetched out-of-band (HuggingFace).
    """
    raw = os.environ.get("OPENADMET_MODEL_DIRS", "").strip()
    if not raw:
        raise RuntimeError(
            "OPENADMET_MODEL_DIRS is unset. Point it (os.pathsep/comma-separated) at the released "
            "OpenADMET baseline model dirs fetched into the /zfs cache (e.g. "
            "cyp1a2-cyp2d6-cyp3a4-cyp3c9-chemeleon-baseline/anvil_training). This adapter never downloads "
            "or guesses weights."
        )
    parts: list[str] = []
    for chunk in raw.replace(",", os.pathsep).split(os.pathsep):
        c = chunk.strip()
        if c:
            parts.append(c)
    missing = [p for p in parts if not Path(p).exists()]
    if missing:
        raise RuntimeError(f"OPENADMET_MODEL_DIRS point at nonexistent paths: {missing}")
    return parts


def _clean(value: Any) -> float | int | None:
    """Coerce an OpenADMET cell to a JSON-safe scalar: finite float/int or None (NaN/inf -> None)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _run_predict(model_dirs: list[str], smiles_list: list[str], accelerator: str) -> Any:
    """Run OpenADMET inference on a batch of SMILES and return the appended-column DataFrame.

    Deferred heavy import (pandas + openadmet + torch) so device/HOME are pinned first. ``log=False``
    silences loguru so nothing pollutes stdout; the real output is the JSON written to --output.
    """
    warnings.filterwarnings("ignore")
    import pandas as pd  # noqa: E402
    from openadmet.models.inference.inference import predict  # noqa: E402

    frame = pd.DataFrame({_INPUT_COL: smiles_list})
    return predict(
        input_path=frame,
        input_col=_INPUT_COL,
        model_dir=model_dirs,
        write_csv=False,
        accelerator=accelerator,
        log=False,
    )


def _split_columns(row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split one result row into (endpoint_values from OADMET_PRED_*, std map from OADMET_STD_*)."""
    endpoint_values: dict[str, Any] = {}
    std_map: dict[str, Any] = {}
    for key, val in row.items():
        if key.startswith(PRED_PREFIX):
            endpoint_values[key] = _clean(val)
        elif key.startswith(STD_PREFIX):
            std_map[key] = _clean(val)
    return endpoint_values, std_map


def _uncertainty_for(std_map: dict[str, Any]) -> dict[str, Any] | None:
    """Build the reserved uncertainty envelope from the OADMET_STD_* columns (native sigma, DIRECT).

    Every STD column is carried verbatim in ``extra`` (keyed by column name) so nothing native is lost.
    ``epistemic`` is set to the single STD value when exactly one task is present and it is a real number
    (ensemble spread = epistemic uncertainty); with released single models every value is None. Returns
    None only when the pipeline appended no STD column at all.
    """
    if not std_map:
        return None
    real = [v for v in std_map.values() if v is not None]
    epistemic = real[0] if len(std_map) == 1 and real else None
    return {"epistemic": epistemic, "extra": dict(std_map)}


def record_for(row: dict[str, Any], smiles: str, mol_id: Any, accelerator: str, model_dirs: list[str]) -> dict[str, Any]:
    """Compute one ``OutputRecord``-shaped dict from a single result row.

    A row with no OADMET_PRED_* columns (OpenADMET could not featurize/predict this SMILES) yields empty
    ``endpoint_values`` with the reason in ``raw`` rather than raising (per-record error isolation).
    """
    endpoint_values, std_map = _split_columns(row)
    base: dict[str, Any] = {"model": MODEL, "provenance": _provenance(accelerator, model_dirs)}

    if not endpoint_values:
        return {
            **base,
            "endpoint_values": {},
            "uncertainty": None,
            "raw": {
                "error": "OpenADMET produced no OADMET_PRED_* columns for this SMILES (unfeaturizable/dropped row)",
                "smiles": smiles,
                "mol_id": mol_id,
            },
        }

    return {
        **base,
        "endpoint_values": endpoint_values,
        "uncertainty": _uncertainty_for(std_map),
        "raw": {
            "smiles": smiles,
            "mol_id": mol_id,
            # Verbatim OADMET_PRED_*/OADMET_STD_* pairs for the raw-output cache / audit trail.
            "pred_columns": endpoint_values,
            "std_columns": std_map,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenADMET CYP-reference adapter (uniform model CLI).")
    parser.add_argument("--input", required=True, type=Path, help="pipeline input (InputRecord JSON, JSON array, or .smi)")
    parser.add_argument("--output", required=True, type=Path, help="where to write the OutputRecord JSON")
    parser.add_argument("--gpu", type=int, default=None, help="CUDA device index; omitted -> CPU (requires_gpu=False)")
    args = parser.parse_args(argv)

    _configure_home()
    accelerator = _configure_device(args.gpu)
    model_dirs = _resolve_model_dirs()

    records, single = parse_inputs(args.input.read_text(encoding="utf-8"))
    smiles_list = [str(r.get("smiles") or "").strip() for r in records]
    mol_ids = [r.get("mol_id") for r in records]

    result = _run_predict(model_dirs, smiles_list, accelerator)
    # Align the appended-column rows back to the input order. predict() keeps the input rows (predictions
    # are inserted by original index), so iloc position matches the input record position.
    rows = [result.iloc[i].to_dict() for i in range(len(records))]

    outputs = [
        record_for(rows[i], smiles_list[i], mol_ids[i], accelerator, model_dirs)
        for i in range(len(records))
    ]
    payload: Any = outputs[0] if (single and len(outputs) == 1) else outputs

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
