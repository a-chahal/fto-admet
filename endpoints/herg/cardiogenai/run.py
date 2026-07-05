#!/usr/bin/env python
"""cardiogenai adapter - discriminative cardiac ion-channel activity (hERG / NaV1.5 / CaV1.2).

Uniform model CLI (CLAUDE.md §2, SETTLED §6):

    python run.py --input <path> --output <path> [--gpu N] [--mode discriminative|generative]

CardioGenAI (gregory-kyro/CardioGenAI, Kyro et al. JCIM 2024) has TWO entry points; this adapter builds
only ONE of them (CLAUDE.md §4, IO_SPEC §1 #7):

  1. DISCRIMINATIVE (BUILT, the default ``--mode discriminative``): a graph + fingerprint + transformer
     ensemble that predicts, per channel, a regression **pIC50** (higher = stronger blocker = higher tox).
     Upstream ``src.Discriminator.predict_cardiac_ion_channel_activity``. This is a SECONDARY model
     (``in_bulk_loop=False``): its hERG head can join the hERG gate (t52) as an extra vote.

  2. GENERATIVE (SCAFFOLD ONLY, ``--mode generative``): ``optimize_cardiotoxic_drug`` would emit candidate
     SMILES conditioned on the input scaffold. Its output is GATED on Kunhuan's FTO-binding +
     FTO-vs-ALKBH5 selectivity, and that cross-arm interface DOES NOT EXIST YET. So this mode refuses
     cleanly with a GATED message and never emits a candidate (see ``_refuse_generative``).

LANDMINE (CLAUDE.md §4, IO_SPEC §1 #7) - the two exact points a plausible guess is wrong:
  (1) The discriminative outputs are keyed with literal labels that CONTAIN A SPACE - ``"hERG pIC50"``,
      ``"NaV1.5 pIC50"``, ``"CaV1.2 pIC50"`` (verified from ``src/Optimization_Framework.py``). A key
      without the space silently misses. ``endpoint_values`` uses these exact space-keyed labels.
  (2) The regression output is a **pIC50, NOT a P(block)**. Mapping pIC50 -> probability (threshold
      pIC50 >= 5.0 or a logistic/calibration) is flag F-1 and lives in the DEFERRED hERG gate math (t52).
      This adapter EMITS the raw pIC50 and does NOT convert. It records the cutoff-based blocker call
      (pIC50 >= 5.0, VERIFIED non-blocker cutoff) only in ``raw`` as context, clearly marked as the
      cutoff class, never as a probability.

This runs in the model's ISOLATED pixi env (torch + torch_geometric + openbabel + rdkit) and so CANNOT
import ``core``; it emits plain JSON matching ``core.schemas.OutputRecord`` and the dispatcher validates
that JSON on collection. Upstream code lives unmodified in ``vendor/CardioGenAI/src`` (imported as the
``src`` package); the model weights + the 746M transformer-vocabulary CSV are fetched under
``vendor/CardioGenAI/{model_parameters,data}`` at install time (gitignored - see README).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import warnings
from pathlib import Path
from typing import Any

MODEL = "cardiogenai"

# Vendored upstream package root: it CONTAINS the ``src/`` package, so putting it on sys.path makes the
# upstream ``from src.X import ...`` absolute imports resolve (PEP 420 namespace package).
VENDOR = Path(__file__).resolve().parent / "vendor" / "CardioGenAI"

# Weights + transformer-vocabulary CSV live under the vendored tree but are NOT committed (CLAUDE.md §0):
# they are fetched on the box at install time (see README "Environment / install").
MODEL_PARAMS = VENDOR / "model_parameters"
DISC = MODEL_PARAMS / "discriminative_model_parameters"
BIDIR_PARAMS = MODEL_PARAMS / "transformer_model_parameters" / "Bidirectional_Transformer_parameters.pt"
TRANSFORMER_CSV = VENDOR / "data" / "prepared_transformer_datasets" / "prepared_transformer_data.csv"

# The three cardiac ion channels, in the order upstream emits them; ``key`` is the LANDMINE space-keyed
# label the pipeline contract requires, ``col`` is the column name upstream returns in its DataFrame.
CHANNELS = (
    ("hERG", "hERG", "hERG pIC50"),
    ("NaV1.5", "NaV1.5", "NaV1.5 pIC50"),
    ("CaV1.2", "CaV1.2", "CaV1.2 pIC50"),
)

# VERIFIED non-blocker cutoff (IO_SPEC §1 #7 / README + Optimization_Framework.py): pIC50 >= 5.0 => blocker.
# Used ONLY to record a context class in ``raw``; the pIC50 -> P(block) mapping is F-1 (DEFERRED, t52).
BLOCKER_PIC50_CUTOFF = 5.0

# The generative path is GATED and NOT wired (CLAUDE.md §4, task step 2).
GATED_MESSAGE = "GATED: needs Kunhuan binding/selectivity interface (not built)"


def _provenance() -> dict[str, Any]:
    """Provenance stamped onto every emitted record (torch version read live, never hardcoded)."""
    import torch

    return {
        "model": MODEL,
        "path": "discriminative",
        "method": "CardioGenAI discriminative ensemble (GAT graph + ECFP2 fingerprint + bidirectional "
        "transformer features) regression head; per-channel pIC50",
        "prediction_type": "regression",
        "torch_version": getattr(torch, "__version__", "unknown"),
        "blocker_pic50_cutoff": BLOCKER_PIC50_CUTOFF,
        "citation": "Kyro GW, Morgan PK, et al. CardioGenAI: a machine learning-based framework for "
        "re-engineering drugs to reduce hERG liability while preserving therapeutic activity. "
        "J Cheminform / JCIM 2024. Repo github.com/gregory-kyro/CardioGenAI.",
        "license": "code: MIT (Gregory W. Kyro 2024); CODE-PKG",
    }


def parse_inputs(text: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse the ``--input`` payload into ``(records, single)`` (same contract as the t11/t23 template).

    Accepts a single ``InputRecord`` JSON object (``single=True``), a JSON array of them (a bulk batch),
    or a ``.smi`` file (``<SMILES><whitespace><title>`` per line, ``#`` comments).
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


def _null_record(smiles: str, mol_id: Any, reason: str) -> dict[str, Any]:
    """A valid OutputRecord for a molecule that could not be scored (null pIC50s, reason in raw)."""
    return {
        "model": MODEL,
        "endpoint_values": {"hERG pIC50": None, "NaV1.5 pIC50": None, "CaV1.2 pIC50": None},
        "uncertainty": None,
        "raw": {"error": reason, "smiles": smiles, "mol_id": mol_id},
        "provenance": _provenance(),
    }


def _record_for(smiles: str, mol_id: Any, pic50: dict[str, float]) -> dict[str, Any]:
    """Assemble one OutputRecord from the three per-channel pIC50 regression outputs."""
    # LANDMINE (2): emit the raw pIC50, NOT a P(block). The cutoff-based blocker call below is context
    # only (F-1, the pIC50 -> probability mapping, is DEFERRED to the hERG gate math in t52).
    blocker_by_cutoff = {
        name: (None if pic50[key] is None else bool(pic50[key] >= BLOCKER_PIC50_CUTOFF))
        for name, _col, key in CHANNELS
    }
    return {
        "model": MODEL,
        # LANDMINE (1): the three keys CONTAIN A SPACE - "hERG pIC50" / "NaV1.5 pIC50" / "CaV1.2 pIC50".
        "endpoint_values": {
            "hERG pIC50": pic50["hERG pIC50"],
            "NaV1.5 pIC50": pic50["NaV1.5 pIC50"],
            "CaV1.2 pIC50": pic50["CaV1.2 pIC50"],
        },
        # CardioGenAI discriminative emits no native uncertainty signal; the reserved envelope stays empty.
        "uncertainty": None,
        "raw": {
            "smiles": smiles,
            "mol_id": mol_id,
            "hERG pIC50": pic50["hERG pIC50"],
            "NaV1.5 pIC50": pic50["NaV1.5 pIC50"],
            "CaV1.2 pIC50": pic50["CaV1.2 pIC50"],
            # Context only (cutoff class, NOT P(block)): pIC50 >= 5.0 => predicted blocker. The real
            # pIC50 -> probability mapping is F-1 and is DEFERRED to the hERG gate (t52).
            "blocker_by_cutoff_pic50_ge_5": blocker_by_cutoff,
            "cutoff_note": "cutoff class only (pIC50 >= 5.0); pIC50 -> P(block) is F-1, deferred to t52",
        },
        "provenance": _provenance(),
    }


def _predict_pic50(valid_smiles: list[str], device: str) -> list[dict[str, float]]:
    """Run the upstream discriminative regression for all three channels on a batch of parseable SMILES.

    Returns one ``{space-keyed label: pIC50}`` dict per input SMILES, in input order. Drives the exact
    documented entry point ``src.Discriminator.predict_cardiac_ion_channel_activity`` (regression), with
    absolute paths to the vendored (fetched-on-box) weights + transformer-vocabulary CSV.
    """
    if str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))

    from src.Discriminator import predict_cardiac_ion_channel_activity  # noqa: E402 (vendored, on sys.path)

    # inference() insists on writing its raw JSON to a save_path; hand it a throwaway temp file.
    with tempfile.TemporaryDirectory() as tmpd:
        save_path = os.path.join(tmpd, "predictions.json")
        df = predict_cardiac_ion_channel_activity(
            input_data=list(valid_smiles),
            prediction_type="regression",
            predict_hERG=True,
            predict_Nav=True,
            predict_Cav=True,
            device=device,
            bidirectional_transformer_params=str(BIDIR_PARAMS),
            transformer_training_data=str(TRANSFORMER_CSV),
            herg_regression_params=str(DISC / "hERG_Regression_parameters.pt"),
            nav_regression_params=str(DISC / "Nav_Regression_parameters.pt"),
            cav_regression_params=str(DISC / "Cav_Regression_parameters.pt"),
            # Regression-only: leave the classification heads unloaded.
            herg_classification_params=None,
            nav_classification_params=None,
            cav_classification_params=None,
            save_path=save_path,
        )

    out: list[dict[str, float]] = []
    for i in range(len(valid_smiles)):
        out.append({key: float(df[col].iloc[i]) for _, col, key in CHANNELS})
    return out


def run(records: list[dict[str, Any]], device: str) -> list[dict[str, Any]]:
    """Score a batch: split parseable from unparseable SMILES, predict the valid ones, keep input order."""
    from rdkit import Chem

    smiles_list = [str(r.get("smiles") or "").strip() for r in records]
    mol_ids = [r.get("mol_id") for r in records]

    valid_idx: list[int] = []
    for idx, smi in enumerate(smiles_list):
        if smi and Chem.MolFromSmiles(smi) is not None:
            valid_idx.append(idx)

    predictions: list[dict[str, float]] = []
    if valid_idx:
        try:
            predictions = _predict_pic50([smiles_list[i] for i in valid_idx], device)
        except Exception as exc:  # noqa: BLE001 - a batch-level failure degrades to per-record nulls, never a crash
            return [
                _null_record(smiles_list[i], mol_ids[i], f"prediction failed: {type(exc).__name__}: {exc}")
                for i in range(len(records))
            ]

    outputs: list[dict[str, Any]] = []
    pos = 0
    for idx in range(len(records)):
        if idx in valid_idx:
            outputs.append(_record_for(smiles_list[idx], mol_ids[idx], predictions[pos]))
            pos += 1
        else:
            reason = "empty SMILES" if not smiles_list[idx] else "RDKit could not parse SMILES"
            outputs.append(_null_record(smiles_list[idx], mol_ids[idx], reason))
    return outputs


def _refuse_generative() -> int:
    """The generative path is a SCAFFOLD-ONLY stub (task step 2): refuse cleanly, emit no candidate.

    CardioGenAI's ``optimize_cardiotoxic_drug`` output is GATED on Kunhuan's FTO-binding +
    FTO-vs-ALKBH5 selectivity, and that cross-arm interface does not exist yet. Until it does, this mode
    must never emit a generative candidate as usable. It prints the GATED message + a TODO and exits
    non-zero without touching the model.

    TODO(gate): wire ``optimize_cardiotoxic_drug`` only after Kunhuan's FTO-binding + FTO-vs-ALKBH5
    selectivity filter exists; filter every generated candidate through it BEFORE emitting anything.
    """
    print(GATED_MESSAGE, file=sys.stderr)
    print(
        "TODO: the generative path is scaffold-only. It stays disabled until Kunhuan's FTO-binding + "
        "FTO-vs-ALKBH5 selectivity interface exists; generated candidates must be filtered through it "
        "before any is emitted as usable.",
        file=sys.stderr,
    )
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CardioGenAI discriminative cardiac ion-channel adapter (uniform model CLI).")
    parser.add_argument("--input", type=Path, help="pipeline input (InputRecord JSON, JSON array, or .smi)")
    parser.add_argument("--output", type=Path, help="where to write the OutputRecord JSON")
    parser.add_argument("--gpu", type=int, default=None, help="GPU index to use; omit for CPU")
    parser.add_argument(
        "--mode",
        choices=("discriminative", "generative"),
        default="discriminative",
        help="discriminative (BUILT: per-channel pIC50) or generative (SCAFFOLD-ONLY stub, refuses: GATED)",
    )
    args = parser.parse_args(argv)

    if args.mode == "generative":
        return _refuse_generative()

    if args.input is None or args.output is None:
        parser.error("--input and --output are required in discriminative mode")

    # Honor --gpu: pin the physical device BEFORE torch is imported, then let upstream select cuda:0
    # (which now maps to the pinned card). No --gpu => force CPU. (GPU claiming is manual; CLAUDE.md §1.)
    warnings.filterwarnings("ignore")
    if args.gpu is not None:
        os.environ["CUDA_VISIBLE_DEVICES"] = str(args.gpu)
        device = "gpu"
    else:
        os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
        device = "cpu"

    records, single = parse_inputs(args.input.read_text(encoding="utf-8"))
    outputs = run(records, device)
    payload: Any = outputs[0] if (single and len(outputs) == 1) else outputs

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
