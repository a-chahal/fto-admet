#!/usr/bin/env python
"""ctoxpred2 adapter - multichannel cardiac ion-channel toxicity (hERG / NaV1.5 / CaV1.2).

Uniform model CLI (CLAUDE.md §2, SETTLED §6):

    python run.py --input <path> --output <path> [--gpu N]

CToxPred2 (issararab/CToxPred2, JCIM 2023/2024) predicts blocker/non-blocker calls for three cardiac
ion channels. It is a SECONDARY model (``in_bulk_loop=False``): its hERG channel feeds the hERG gate
(t52) as a confidence-weighted VOTE, NOT a probability in the P(block) average (CLAUDE.md §4); NaV1.5
and CaV1.2 are context. This runs in the model's ISOLATED pixi env (py3.9 + torch 1.12.1 + mordred +
PyBioMed) and so CANNOT import ``core``; it emits plain JSON matching ``core.schemas.OutputRecord`` and
the dispatcher validates that JSON on collection.

We drive prediction through the notebook's underlying functions (``notebooks/nutils.py`` DNN path,
``_generate_predictions_sl``), adapted here - NOT the shipped Tk GUI (``app.py``). Upstream code lives
unmodified in ``vendor/CToxPred2`` (its inner package tree); the compressed model weights are
decompressed under ``vendor/CToxPred2/models`` at install time (gitignored - see README).

Model choice: the DNN (supervised + MC-dropout at inference), NOT the RF (semi-supervised) variant. The
DNN gives a genuine MC-dropout confidence (the mean of 100 stochastic forward passes) that maps cleanly
onto the reserved ``uncertainty`` envelope, and its torch state-dicts load robustly across versions
(unlike the RF's sklearn-version-pinned joblib pickles). The RF weights ship in the same repo
(``models/random_forest``) as an alternate path but are not wired here (README).

LANDMINE (CLAUDE.md §4, IO_SPEC §1 #6) - the two exact points a plausible guess is wrong:
  (1) Each channel call is a BINARY 0/1 int via argmax (1 = blocker), NOT a continuous probability. We
      emit it as a vote in ``endpoint_values`` (``hERG_vote`` / ``NaV1.5_vote`` / ``CaV1.2_vote``).
  (2) Each confidence is written by upstream as a PERCENT STRING ``"{:.1%}"`` (e.g. ``"87.3%"``). We
      reproduce that export string verbatim in ``raw`` and PARSE it (strip ``%``, /100) into a float in
      [0, 1] for ``uncertainty`` - so ``uncertainty.confidence`` carries the parsed hERG confidence and
      the NaV1.5/CaV1.2 parsed confidences go in ``uncertainty.extra``. The parsed value inherits the
      export's 1-decimal-percent precision (that string IS the contract); the full-precision float is
      kept in ``extra`` alongside so nothing native is lost.

``--gpu`` is accepted and IGNORED: the DNN is tiny and runs on CPU (the upstream sl path pins
``torch.device("cpu")``). The uniform CLI is identical for every model so the dispatcher builds one command.

Robustness: an unparseable/empty SMILES yields a per-record result with null votes and the reason in
``raw`` (RDKit returns ``None``, which the upstream feature functions cannot process) - one bad molecule
never sinks a bulk batch.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path
from typing import Any

import numpy as np

# Locate the vendored upstream package + its decompressed weights, then put the inner package dir on the
# path so its flat imports (``from utils import ...`` etc., the layout nutils.py assumes) resolve. The
# vendored inner package's ``.py`` modules live directly under ``vendor/CToxPred2/`` and the decompressed
# weights under ``vendor/CToxPred2/models/`` (see README "Environment / install").
VENDOR_PKG = Path(__file__).resolve().parent / "vendor" / "CToxPred2"
MODELS = VENDOR_PKG / "models"
if str(VENDOR_PKG) not in sys.path:
    sys.path.insert(0, str(VENDOR_PKG))

warnings.filterwarnings("ignore")

import torch  # noqa: E402

from utils import (  # noqa: E402  (vendored upstream, on sys.path above)
    compute_descriptor_features,
    compute_fingerprint_features,
)

# CorrelationThreshold MUST be importable as ``__main__.CorrelationThreshold`` to unpickle the descriptor
# preprocessing pipelines: they were fit/pickled with that class defined in ``__main__`` (this run.py IS
# ``__main__``, exactly as the upstream notebook is when it imports the same name). Do not remove.
from pairwise_correlation import CorrelationThreshold  # noqa: E402,F401
from hERG_model import hERGClassifier  # noqa: E402
from nav15_model import Nav15Classifier  # noqa: E402
from cav12_model import Cav12Classifier  # noqa: E402

import joblib  # noqa: E402

MODEL = "ctoxpred2"

# Upstream fixed hyperparameters (nutils.py ``_generate_predictions_sl``): dropout rate + MC forward passes.
GLB_DROPOUT_RATE = 0.2
GLB_FORWARD_ITERATIONS = 100
# Seed so the MC-dropout vote/confidence are reproducible across runs (the smoke asserts shape, not value,
# but a stable number is friendlier for the ledger/audit trail).
GLB_SEED = 0

# Per-channel input dims (fingerprints [+ transformed descriptors]) - the exact sizes the shipped
# checkpoints were trained at (nutils.py). hERG is fingerprints-only; NaV1.5/CaV1.2 add descriptors.
_HERG_DIM = 1905
_NAV_DIM = 2453
_CAV_DIM = 2586


def _provenance() -> dict[str, Any]:
    """Provenance stamped onto every emitted record (versions read live, never hardcoded)."""
    return {
        "model": MODEL,
        "method": "CToxPred2 DNN (supervised) with MC-dropout at inference; ECFP2+PubChem fingerprints "
        "(PyBioMed) and Mordred 2D descriptors; per-channel MLP classifiers",
        "variant": "dl-sl",
        "torch_version": getattr(torch, "__version__", "unknown"),
        "mc_forward_iterations": GLB_FORWARD_ITERATIONS,
        "citation": "Arab I, et al. Semisupervised Learning to Boost hERG, Nav1.5, and Cav1.2 Cardiac Ion "
        "Channel Toxicity Prediction. J Chem Inf Model 2024. doi:10.1021/acs.jcim.4c01102",
        "license": "code: MIT (Issar Arab 2024); CODE-PKG",
    }


def parse_inputs(text: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse the ``--input`` payload into ``(records, single)`` (same contract as the t11 template).

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


def _parse_percent(pct: str) -> float:
    """Parse upstream's ``"{:.1%}"`` confidence STRING (LANDMINE): strip ``%``, divide by 100 -> [0, 1]."""
    return float(pct.strip().rstrip("%")) / 100.0


def _mc_dropout(model: torch.nn.Module, feats: np.ndarray) -> tuple[list[int], list[float]]:
    """Run the upstream MC-dropout inference: ``.train()`` (dropout ON), average 100 stochastic passes.

    Returns ``(votes, confidences)`` where vote = argmax of the mean softmax (0/1) and confidence = the max
    mean-softmax probability (the winning class's mean confidence) - exactly nutils.py ``_generate_predictions_sl``.
    """
    device = torch.device("cpu")
    model.to(device)
    model.train()  # keep dropout active at inference - this is what makes it MC-dropout, not a bug
    x = torch.from_numpy(feats).float().to(device)
    all_predictions = torch.empty(len(feats), 2, GLB_FORWARD_ITERATIONS)
    with torch.no_grad():
        for i in range(GLB_FORWARD_ITERATIONS):
            all_predictions[:, :, i] = model(x).cpu()
    mean_predictions = all_predictions.mean(dim=2)
    confidences, votes = mean_predictions.max(1)
    return [int(v) for v in votes.tolist()], [float(c) for c in confidences.tolist()]


def _predict_channels(valid_smiles: list[str]) -> dict[str, tuple[list[int], list[str]]]:
    """Predict all three channels for a list of PARSEABLE SMILES.

    Returns ``{channel: (votes, percent_strings)}`` where each percent string is upstream's ``"{:.1%}"``
    export literal (the LANDMINE contract value) - the caller parses it back to a float.
    """
    torch.manual_seed(GLB_SEED)
    fingerprints = compute_fingerprint_features(valid_smiles)
    descriptors = compute_descriptor_features(valid_smiles)

    out: dict[str, tuple[list[int], list[str]]] = {}

    # hERG - fingerprints only.
    herg = hERGClassifier(_HERG_DIM, 2, GLB_DROPOUT_RATE)
    herg.load(str(MODELS / "model_weights" / "hERG" / "_herg_checkpoint.model"))
    votes, confs = _mc_dropout(herg, fingerprints)
    out["hERG"] = (votes, ["{:.1%}".format(c) for c in confs])

    # NaV1.5 - fingerprints + its own transformed Mordred descriptors.
    nav_pipe = joblib.load(str(MODELS / "decriptors_preprocessing" / "Nav1.5" / "nav_descriptors_preprocessing_pipeline.sav"))
    nav_features = np.concatenate((fingerprints, nav_pipe.transform(descriptors)), axis=1)
    nav = Nav15Classifier(_NAV_DIM, 2, GLB_DROPOUT_RATE)
    nav.load(str(MODELS / "model_weights" / "Nav1.5" / "_nav15_checkpoint.model"))
    votes, confs = _mc_dropout(nav, nav_features)
    out["NaV1.5"] = (votes, ["{:.1%}".format(c) for c in confs])

    # CaV1.2 - fingerprints + its own transformed Mordred descriptors.
    cav_pipe = joblib.load(str(MODELS / "decriptors_preprocessing" / "Cav1.2" / "cav_descriptors_preprocessing_pipeline.sav"))
    cav_features = np.concatenate((fingerprints, cav_pipe.transform(descriptors)), axis=1)
    cav = Cav12Classifier(_CAV_DIM, 2, GLB_DROPOUT_RATE)
    cav.load(str(MODELS / "model_weights" / "Cav1.2" / "_cav12_checkpoint.model"))
    votes, confs = _mc_dropout(cav, cav_features)
    out["CaV1.2"] = (votes, ["{:.1%}".format(c) for c in confs])

    return out


def _null_record(smiles: str, mol_id: Any, reason: str) -> dict[str, Any]:
    """A valid OutputRecord for a molecule that could not be scored (null votes, reason in raw)."""
    return {
        "model": MODEL,
        "endpoint_values": {"hERG_vote": None, "NaV1.5_vote": None, "CaV1.2_vote": None},
        "uncertainty": None,
        "raw": {"error": reason, "smiles": smiles, "mol_id": mol_id},
        "provenance": _provenance(),
    }


def _record_for(smiles: str, mol_id: Any, channels: dict[str, tuple[list[int], list[str]]], i: int) -> dict[str, Any]:
    """Assemble one OutputRecord from the batched channel predictions for the i-th valid molecule."""
    herg_vote, herg_pct = channels["hERG"][0][i], channels["hERG"][1][i]
    nav_vote, nav_pct = channels["NaV1.5"][0][i], channels["NaV1.5"][1][i]
    cav_vote, cav_pct = channels["CaV1.2"][0][i], channels["CaV1.2"][1][i]

    herg_conf = _parse_percent(herg_pct)
    nav_conf = _parse_percent(nav_pct)
    cav_conf = _parse_percent(cav_pct)

    # hERG confidence -> the reserved scalar ``confidence``; NaV1.5/CaV1.2 (context) -> ``extra``.
    uncertainty = {
        "confidence": herg_conf,
        "extra": {
            "nav15_confidence": nav_conf,
            "cav12_confidence": cav_conf,
            # the verbatim upstream export strings (the LANDMINE %-string contract), kept for audit
            "hERG_confidence_pct": herg_pct,
            "nav15_confidence_pct": nav_pct,
            "cav12_confidence_pct": cav_pct,
        },
    }
    return {
        "model": MODEL,
        # 0/1 VOTES, not probabilities (LANDMINE): the hERG gate weights these by confidence, never
        # averages them into the P(block) pool.
        "endpoint_values": {"hERG_vote": herg_vote, "NaV1.5_vote": nav_vote, "CaV1.2_vote": cav_vote},
        "uncertainty": uncertainty,
        "raw": {
            "smiles": smiles,
            "mol_id": mol_id,
            "hERG": herg_vote,
            "hERG_confidence": herg_pct,
            "Nav1.5": nav_vote,
            "Nav1.5_confidence": nav_pct,
            "Cav1.2": cav_vote,
            "Cav1.2_confidence": cav_pct,
        },
        "provenance": _provenance(),
    }


def run(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Score a batch: split parseable from unparseable SMILES, predict the valid ones, keep input order."""
    from rdkit import Chem

    smiles_list = [str(r.get("smiles") or "").strip() for r in records]
    mol_ids = [r.get("mol_id") for r in records]

    valid_idx: list[int] = []
    for idx, smi in enumerate(smiles_list):
        if smi and Chem.MolFromSmiles(smi) is not None:
            valid_idx.append(idx)

    channels: dict[str, tuple[list[int], list[str]]] = {}
    if valid_idx:
        try:
            channels = _predict_channels([smiles_list[i] for i in valid_idx])
        except Exception as exc:  # noqa: BLE001 - a batch-level failure degrades to per-record nulls, never a crash
            return [
                _null_record(smiles_list[i], mol_ids[i], f"prediction failed: {type(exc).__name__}: {exc}")
                for i in range(len(records))
            ]

    outputs: list[dict[str, Any]] = []
    pos = 0
    for idx in range(len(records)):
        if idx in valid_idx:
            outputs.append(_record_for(smiles_list[idx], mol_ids[idx], channels, pos))
            pos += 1
        else:
            reason = "empty SMILES" if not smiles_list[idx] else "RDKit could not parse SMILES"
            outputs.append(_null_record(smiles_list[idx], mol_ids[idx], reason))
    return outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CToxPred2 cardiac ion-channel toxicity adapter (uniform model CLI).")
    parser.add_argument("--input", required=True, type=Path, help="pipeline input (InputRecord JSON, JSON array, or .smi)")
    parser.add_argument("--output", required=True, type=Path, help="where to write the OutputRecord JSON")
    parser.add_argument("--gpu", type=int, default=None, help="ignored (the DNN runs on CPU); present for the uniform CLI")
    args = parser.parse_args(argv)

    records, single = parse_inputs(args.input.read_text(encoding="utf-8"))
    outputs = run(records)
    payload: Any = outputs[0] if (single and len(outputs) == 1) else outputs

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
