#!/usr/bin/env python
"""cardiotox_net adapter - CardioTox net, a deep-learning meta-feature ensemble for hERG blocker
probability (the healthiest, most drop-in hERG model in the gate; legacy TF stack).

Uniform model CLI (CLAUDE.md 2, SETTLED 6):

    python run.py --input <path> --output <path> [--gpu N]

CardioTox net (Abdulk084/CardioTox, Karim et al., J. Cheminformatics 2021) stacks four base learners -
a Mordred-descriptor MLP, an ECFP2+PubChem fingerprint MLP, a SMILES-vector CNN, and a Morgan
fingerprint-vector CNN - under a trained meta-learner. It is a PRIMARY hERG model: its output is
P(hERG block) fed to the gate core average (identity, UP = more likely blocker).

This runs in the model's ISOLATED, LEGACY pixi env (python 3.8 + tensorflow 2.3.1 + keras 2.4.3 +
rdkit 2020.03 + mordred) and so CANNOT import ``core``; it emits plain JSON matching
``core.schemas.OutputRecord`` and the dispatcher validates that JSON on collection. Upstream code lives
unmodified under ``vendor/CardioTox`` (its ``cardiotox`` package + trained weights); we import the
ensemble and run inference here rather than shelling out to the repo's ``test.py``.

LANDMINE (bare array, positional alignment - CLAUDE.md 4, IO_SPEC 1 #5):
  ``ensemble.predict(smiles, probabilities=False)`` returns a BARE NumPy array of P(block), one per
  input SMILES (shape (N, 1) from the meta-learner's single sigmoid). There is NO named field to key on:
  the adapter aligns it POSITIONALLY to the input list. A misalignment would silently mislabel every
  molecule, so ``_predict`` asserts the returned length equals the number of scored SMILES. (With
  ``probabilities=True`` the upstream helper expands to two columns ``[P(non-blocker), P(blocker)]`` for
  LIME; column 1 there equals what ``probabilities=False`` already returns, so we use the simpler path.)

LANDMINE (applicability limit, flag - never drop - CLAUDE.md 4, IO_SPEC 1 #5):
  CardioTox net is "only suitable for SMILES with max number of 1's in Morgan fingerprint <= 93" - the
  fingerprint-vector base model truncates the on-bit list to 93, so a molecule with more on-bits is out
  of the applicability domain. We compute the Morgan (radius 2, 1024-bit) on-bit count that base model
  uses and record ``ad_in_domain`` (on-bits <= 93) in the reserved Uncertainty envelope (+ the count in
  ``extra`` and mirrored in ``raw``) so the gate can DOWN-WEIGHT rather than trust an out-of-range call.
  We never drop the molecule.

Native (alea/epis) uncertainty is INDIRECT for CardioTox net (ensemble-vs-ensemble agreement, computed
at t52), so ``aleatoric`` / ``epistemic`` stay None here; only the applicability-domain flag is emitted.

The trained weights are ~216 MB and are NOT committed to git (CLAUDE.md 0: never commit weights). The
whole upstream repo (code + weights) is cloned once, on first use, at the pinned commit into the
gitignored ``vendor/CardioTox`` path and cached there (see README). ``load_ensemble()`` resolves its
checkpoints by paths RELATIVE to that repo root, so we chdir into it for the load + predict.

``--gpu`` is accepted and IGNORED: this legacy TF 2.3.1 CPU build is used (the ensemble is tiny and the
old-TF/old-CUDA stack does not cooperate with the box's modern driver). The uniform CLI is identical for
every model so the dispatcher builds one command.

Robustness: an unparseable / empty SMILES yields a per-record result with a null ``P_block`` and the
reason in ``raw`` (RDKit returns ``None`` for a bad parse) - one bad molecule never sinks a bulk batch.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Any, Optional

# Vendored upstream (code + weights) is cloned on first use under vendor/CardioTox (gitignored). The
# `cardiotox` package sits at vendor/CardioTox/cardiotox and its checkpoints are addressed by paths
# RELATIVE to the repo root (e.g. "cardiotox/models/training_stack/cp_st.ckpt"), so load_ensemble() must
# run with the cwd set to VENDOR.
VENDOR = Path(__file__).resolve().parent / "vendor" / "CardioTox"
# A sentinel checkpoint file that proves the (large, gitignored) weights are present.
STACK_CKPT = VENDOR / "cardiotox" / "models" / "training_stack" / "cp_st.ckpt.index"

# The upstream repo is cloned + pinned to this exact commit (code + the ~216 MB weights). Pinning the
# commit keeps provenance exact. (This was HEAD of Abdulk084/CardioTox at build time.)
UPSTREAM_URL = "https://github.com/Abdulk084/CardioTox.git"
UPSTREAM_COMMIT = "6096ef004016f82a64df99e5df8c1133d7092550"

warnings.filterwarnings("ignore")
# Quiet TensorFlow's C++ + Python chatter so nothing pollutes stdout (the real output is the JSON file).
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")  # force CPU: the legacy TF/CUDA stack fights the driver

MODEL = "cardiotox_net"

# The applicability limit the fingerprint-vector base model bakes in: Morgan (radius 2, 1024-bit) on-bit
# count must be <= 93 (the model truncates the on-bit list to this length). A wrong radius/nBits here
# would compute the wrong AD flag, so these mirror cardiotox/fv_model.py exactly.
MORGAN_RADIUS = 2
MORGAN_NBITS = 1024
MORGAN_ONBIT_LIMIT = 93


def _provenance(tf_version):
    # type: (str) -> dict
    """Provenance stamped onto every emitted record (the TF version is read live, never hardcoded)."""
    return {
        "model": MODEL,
        "method": "CardioTox net: stacked meta-feature ensemble (Mordred-descriptor MLP + ECFP2/PubChem "
        "fingerprint MLP + SMILES-vector CNN + Morgan fingerprint-vector CNN) under a trained "
        "meta-learner; output is P(hERG block)",
        "tensorflow_version": tf_version,
        "upstream_commit": UPSTREAM_COMMIT,
        "citation": "Karim A, Lee M, Balle T, Sattar A. CardioTox net: a robust predictor of hERG "
        "channel blockade based on deep learning meta-feature ensembles. J Cheminform 2021;13:60. "
        "doi:10.1186/s13321-021-00541-z",
        "license": "code: see upstream Abdulk084/CardioTox. Access CODE-PKG.",
    }


def parse_inputs(text):
    # type: (str) -> tuple
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

    records = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        mol_id = parts[1] if len(parts) > 1 else None
        records.append({"smiles": parts[0], "mol_id": mol_id})
    return records, False


def _ensure_vendor():
    # type: () -> None
    """Clone the upstream repo (code + ~216 MB weights) once, pinned to UPSTREAM_COMMIT (gitignored).

    Idempotent: a present stack checkpoint means the vendor tree is already populated and is left
    untouched. Raises on failure so a missing/partial vendor is a loud error, never a silent wrong run.
    """
    if STACK_CKPT.exists() and STACK_CKPT.stat().st_size > 0:
        return
    VENDOR.parent.mkdir(parents=True, exist_ok=True)
    if not (VENDOR / ".git").exists():
        subprocess.check_call(["git", "clone", UPSTREAM_URL, str(VENDOR)])
    # Pin the exact commit (the clone may track a moved HEAD); checkout is a no-op if already there.
    subprocess.check_call(["git", "-C", str(VENDOR), "checkout", "--quiet", UPSTREAM_COMMIT])
    if not (STACK_CKPT.exists() and STACK_CKPT.stat().st_size > 0):
        raise RuntimeError(
            "CardioTox vendor clone at {0} is missing the trained weights ({1})".format(VENDOR, STACK_CKPT)
        )


def _morgan_onbits(smiles):
    # type: (str) -> Optional[int]
    """Count on-bits in the Morgan (radius 2, 1024-bit) fingerprint the fv base model uses.

    Returns the on-bit count, or None if RDKit cannot parse the SMILES. This is exactly the fingerprint
    cardiotox/fv_model.py builds, so the count is the one the applicability limit (<= 93) is defined on.
    """
    from rdkit import Chem
    from rdkit.Chem import AllChem

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    fp = AllChem.GetMorganFingerprintAsBitVect(mol, MORGAN_RADIUS, nBits=MORGAN_NBITS)
    return int(sum(fp))


def _predict(smiles_list):
    # type: (list) -> list
    """Run the CardioTox net ensemble on a list of PARSEABLE SMILES, aligned to ``smiles_list``.

    Returns a list of float P(block). load_ensemble() addresses its checkpoints by paths relative to the
    upstream repo root, so we chdir into VENDOR for the load + predict, then restore the cwd. The
    predict() output is a BARE array (no named field), so we align it positionally and ASSERT its length
    equals the number of scored SMILES (the misalignment landmine).
    """
    import numpy as np

    prev_cwd = os.getcwd()
    if str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))
    os.chdir(str(VENDOR))
    try:
        import cardiotox

        ensemble = cardiotox.load_ensemble()
        out = ensemble.predict(list(smiles_list), probabilities=False)
    finally:
        os.chdir(prev_cwd)

    probs = np.asarray(out, dtype=float).reshape(-1)
    if probs.shape[0] != len(smiles_list):
        raise RuntimeError(
            "CardioTox returned {0} predictions for {1} SMILES - positional alignment broken".format(
                probs.shape[0], len(smiles_list)
            )
        )
    return [float(x) for x in probs]


def _null_record(smiles, mol_id, reason, provenance):
    # type: (str, Any, str, dict) -> dict
    """A valid OutputRecord for a molecule that could not be scored (null P_block, reason in raw)."""
    return {
        "model": MODEL,
        "endpoint_values": {"P_block": None},
        "uncertainty": None,
        "raw": {"error": reason, "smiles": smiles, "mol_id": mol_id},
        "provenance": provenance,
    }


def run(records):
    # type: (list) -> list
    """Score a batch: split parseable from unparseable SMILES, predict the valid ones, keep input order."""
    import tensorflow as tf  # imported here so provenance can read the live version

    provenance = _provenance(getattr(tf, "__version__", "unknown"))

    smiles_list = [str(r.get("smiles") or "").strip() for r in records]
    mol_ids = [r.get("mol_id") for r in records]

    # On-bit count per molecule (None => unparseable). This both drives the AD flag and gives us the
    # parseable set to score.
    onbits = [(_morgan_onbits(smi) if smi else None) for smi in smiles_list]
    valid_idx = [i for i, ob in enumerate(onbits) if ob is not None]

    scores = []
    if valid_idx:
        try:
            scores = _predict([smiles_list[i] for i in valid_idx])
        except Exception as exc:  # noqa: BLE001 - a batch-level failure degrades to per-record nulls, never a crash
            reason = "prediction failed: {0}: {1}".format(type(exc).__name__, exc)
            return [_null_record(smiles_list[i], mol_ids[i], reason, provenance) for i in range(len(records))]

    outputs = []
    pos = 0
    for idx in range(len(records)):
        if idx in valid_idx:
            score = scores[pos]
            pos += 1
            onbit = onbits[idx]
            in_domain = onbit <= MORGAN_ONBIT_LIMIT
            outputs.append(
                {
                    "model": MODEL,
                    # score is already P(block); identity into the gate core average (UP = more blocker).
                    "endpoint_values": {"P_block": score},
                    # Native alea/epis uncertainty is INDIRECT (computed at t52) -> None. The applicability
                    # limit IS a native signal: record it in the reserved AD fields so the gate can
                    # down-weight an out-of-range molecule (schema rule, CLAUDE.md 3).
                    "uncertainty": {
                        "aleatoric": None,
                        "epistemic": None,
                        "ad_in_domain": in_domain,
                        "extra": {
                            "morgan_onbits": onbit,
                            "morgan_onbit_limit": MORGAN_ONBIT_LIMIT,
                            "in_applicability_domain": in_domain,
                        },
                    },
                    "raw": {
                        "smiles": smiles_list[idx],
                        "mol_id": mol_ids[idx],
                        "P_block": score,
                        "morgan_onbits": onbit,
                        "morgan_onbit_limit": MORGAN_ONBIT_LIMIT,
                        "in_applicability_domain": in_domain,
                    },
                    "provenance": provenance,
                }
            )
        else:
            reason = "empty SMILES" if not smiles_list[idx] else "RDKit could not parse SMILES"
            outputs.append(_null_record(smiles_list[idx], mol_ids[idx], reason, provenance))
    return outputs


def main(argv=None):
    # type: (Optional[list]) -> int
    parser = argparse.ArgumentParser(description="CardioTox net hERG blocker probability adapter (uniform model CLI).")
    parser.add_argument("--input", required=True, type=Path, help="pipeline input (InputRecord JSON, JSON array, or .smi)")
    parser.add_argument("--output", required=True, type=Path, help="where to write the OutputRecord JSON")
    parser.add_argument("--gpu", type=int, default=None, help="ignored (legacy TF runs on CPU); present for the uniform CLI")
    args = parser.parse_args(argv)

    _ensure_vendor()

    records, single = parse_inputs(args.input.read_text(encoding="utf-8"))
    outputs = run(records)
    payload = outputs[0] if (single and len(outputs) == 1) else outputs

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
