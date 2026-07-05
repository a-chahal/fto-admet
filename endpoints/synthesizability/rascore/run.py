#!/usr/bin/env python
"""rascore adapter - RAscore, a machine-learned retrosynthetic-accessibility classifier
(synthesizability endpoint; legacy 2021 sklearn/xgboost stack).

Uniform model CLI (CLAUDE.md 2, SETTLED 6):

    python run.py --input <path> --output <path> [--gpu N]

RAscore (reymond-group/RAscore, Thakkar et al., Chem. Sci. 2021) is a binary classifier trained on
200,000 ChEMBL compounds labelled by whether the CASP tool AiZynthFinder could find a synthetic route
to them (1) or not (0). Its output is P(a route is findable) in [0, 1]: it is a fast (~4500x) surrogate
for actually running the retrosynthesis search.

Role: the SECOND rung of the synthesizability tier ladder (SAscore -> RAscore -> AiZynthFinder, docs
IO_SPEC 1 #26 / 2). RAscore is a CLASSIFIER for route-findability, NOT a route search - that is the
third rung, AiZynthFinder (t32), which is a distinct model. The rungs use different scales and are
reported as a tier, never averaged.

Output (docs IO_SPEC 1 #26):
    endpoint_values = {"RAscore": <float in 0..1>}   # UP = more likely synthesizable
    uncertainty     = None                            # the classifier emits a single probability

Direction: HIGHER RAscore = more likely a synthetic route exists = more likely synthesizable. (This is
the natural "higher = better" sense, unlike its rung-1 neighbour SAscore, where LOWER = easier.)

This runs in the model's ISOLATED, LEGACY pixi env (python 3.7 + scikit-learn 0.22.1 + xgboost 1.0.2 +
rdkit 2020.09) and so CANNOT import ``core``; it emits plain JSON matching ``core.schemas.OutputRecord``
and the dispatcher validates that JSON on collection. Upstream code lives unmodified under
``vendor/RAscore``; we import the ``RAscore`` package and run inference here.

LANDMINE (pinned 2021 stack - CLAUDE.md 4, IO_SPEC 1 #26, task t31):
  The default RAscore classifier is a pickled XGBoost sklearn wrapper
  (``RAscore/models/XGB_chembl_ecfp_counts/model.pkl``). Upstream states it can ONLY be unpickled with
  ``scikit-learn == 0.22.1`` and ``xgboost == 1.0.2`` - a wrong pin silently fails to unpickle (or
  unpickles into an object that predicts garbage). Those exact versions are pinned in ``pixi.toml``.

  We use the XGB (ECFP-counts) variant, NOT the TensorFlow/Keras (FCFP-counts) DNN: the XGB path is
  TF-free (no CUDA to fight the box driver), and in this pinned commit the DNN default loader points at a
  ``model.tf`` that the shipped archive does not contain (only ``model.h5``), so the NN default is broken
  upstream while the XGB default is present and correct. Both are RAscore variants trained on the same
  labels and emit the same P(route findable).

The trained models ship inside the repo as ``models.zip`` (~64 MB unzipped) and are NOT committed to git
(CLAUDE.md 0: never commit weights/data). The whole upstream repo is cloned once, on first use, at the
pinned commit into the gitignored ``vendor/RAscore`` path, and ``models.zip`` is unzipped there (see
README). ``RAScorerXGB()`` resolves ``model.pkl`` by a path relative to the package dir.

``--gpu`` is accepted and IGNORED: the XGB classifier is CPU-only. The uniform CLI is identical for every
model so the dispatcher builds one command.

Robustness: an unparseable / empty SMILES yields a per-record result with a null ``RAscore`` and the
reason in ``raw`` (RDKit returns ``None`` for a bad parse) - one bad molecule never sinks a bulk batch.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import warnings
import zipfile
from pathlib import Path
from typing import Any, Optional

# Vendored upstream (code + models.zip) is cloned on first use under vendor/RAscore (gitignored). The
# importable `RAscore` package sits at vendor/RAscore/RAscore, so the repo ROOT (vendor/RAscore) is what
# goes on sys.path for `from RAscore import RAscore_XGB`.
VENDOR = Path(__file__).resolve().parent / "vendor" / "RAscore"
# The python package dir inside the repo, and the model archive + the sentinel checkpoint it unzips to.
PKG_DIR = VENDOR / "RAscore"
MODELS_ZIP = PKG_DIR / "models" / "models.zip"
XGB_PKL = PKG_DIR / "models" / "XGB_chembl_ecfp_counts" / "model.pkl"

# The upstream repo is cloned + pinned to this exact commit (code + models.zip). Pinning keeps provenance
# exact. (This was HEAD of reymond-group/RAscore at build time.)
UPSTREAM_URL = "https://github.com/reymond-group/RAscore.git"
UPSTREAM_COMMIT = "cb77db503ee5cbf0e8bb8963df6e5b76b3a94f06"

warnings.filterwarnings("ignore")

MODEL = "rascore"
# The XGB (ECFP-counts, ChEMBL) classifier is the default RAscore variant we score with.
MODEL_VARIANT = "XGB_chembl_ecfp_counts"

RASCORE_MIN = 0.0
RASCORE_MAX = 1.0


def _provenance(sklearn_version, xgboost_version, rdkit_version):
    # type: (str, str, str) -> dict
    """Provenance stamped onto every emitted record (library versions read live, never hardcoded)."""
    return {
        "model": MODEL,
        "method": "RAscore: binary retrosynthetic-accessibility classifier (route findable by "
        "AiZynthFinder, trained on 200k ChEMBL); XGBoost/ECFP6-counts variant "
        "(models/XGB_chembl_ecfp_counts/model.pkl). Output is P(route findable) in [0, 1], "
        "UP = more likely synthesizable. Second rung of the synthesizability tier ladder "
        "(SAscore -> RAscore -> AiZynthFinder); reported as a tier, never averaged.",
        "model_variant": MODEL_VARIANT,
        "scikit_learn_version": sklearn_version,
        "xgboost_version": xgboost_version,
        "rdkit_version": rdkit_version,
        "upstream_commit": UPSTREAM_COMMIT,
        "citation": "Thakkar A, Chadimova V, Bjerrum EJ, Engkvist O, Reymond J-L. Retrosynthetic "
        "accessibility score (RAscore): rapid machine learned synthesizability classification from AI "
        "driven retrosynthetic planning. Chem Sci 2021;12:3339-3349. doi:10.1039/D0SC05401A",
        "license": "MIT (reymond-group/RAscore). Access CODE-PKG.",
    }


def parse_inputs(text):
    # type: (str) -> tuple
    """Parse the ``--input`` payload into ``(records, single)`` (same contract as the t11/t30 template).

    Accepts a single ``InputRecord`` JSON object (``single=True``), a JSON array of them (a bulk batch),
    or a ``.smi`` file (``<SMILES><whitespace><title>`` per line, ``#`` comments). JSON is detected by
    trying to parse it, so a ``.smi`` line beginning with a bracket atom (e.g. ``[nH]``) is not misread.
    """
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            data = json.loads(stripped)
        except ValueError:
            data = None
        if isinstance(data, dict):
            return [data], True
        if isinstance(data, list):
            return list(data), False
        if data is not None:
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
    """Clone the upstream repo once, pinned to UPSTREAM_COMMIT, and unzip its models.zip (gitignored).

    Idempotent: a present XGB model.pkl means the vendor tree is already populated and is left untouched.
    Raises on failure so a missing/partial vendor is a loud error, never a silent wrong run.
    """
    if XGB_PKL.exists() and XGB_PKL.stat().st_size > 0:
        return
    VENDOR.parent.mkdir(parents=True, exist_ok=True)
    if not (VENDOR / ".git").exists():
        subprocess.check_call(["git", "clone", UPSTREAM_URL, str(VENDOR)])
    # Pin the exact commit (the clone may track a moved HEAD); checkout is a no-op if already there.
    subprocess.check_call(["git", "-C", str(VENDOR), "checkout", "--quiet", UPSTREAM_COMMIT])
    # The pretrained models ship as models.zip inside the package; unzip in place (its entries are rooted
    # at "models/", so extracting into PKG_DIR yields PKG_DIR/models/XGB_chembl_ecfp_counts/model.pkl).
    if not (XGB_PKL.exists() and XGB_PKL.stat().st_size > 0):
        if not MODELS_ZIP.exists():
            raise RuntimeError("RAscore vendor clone at {0} is missing models.zip".format(VENDOR))
        with zipfile.ZipFile(str(MODELS_ZIP)) as zf:
            zf.extractall(str(PKG_DIR))
    if not (XGB_PKL.exists() and XGB_PKL.stat().st_size > 0):
        raise RuntimeError(
            "RAscore vendor at {0} is missing the XGB model after unzip ({1})".format(VENDOR, XGB_PKL)
        )


def _load_scorer():
    # type: () -> Any
    """Import the vendored RAscore package and instantiate the default XGB (ECFP-counts) scorer.

    Adds the repo root (VENDOR) to sys.path so ``from RAscore import RAscore_XGB`` resolves to the
    vendored package. ``RAScorerXGB()`` unpickles ``models/XGB_chembl_ecfp_counts/model.pkl`` (the pin
    landmine) via a path relative to the package dir.
    """
    if str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))
    from RAscore import RAscore_XGB  # noqa: E402  (import after sys.path is set - vendored package)

    return RAscore_XGB.RAScorerXGB()


def _null_record(smiles, mol_id, reason, provenance):
    # type: (str, Any, str, dict) -> dict
    """A valid OutputRecord for a molecule that could not be scored (null RAscore, reason in raw)."""
    return {
        "model": MODEL,
        "endpoint_values": {"RAscore": None},
        "uncertainty": None,
        "raw": {"error": reason, "smiles": smiles, "mol_id": mol_id},
        "provenance": provenance,
    }


def run(records):
    # type: (list) -> list
    """Score a batch: validate each SMILES, predict the parseable ones, keep input order."""
    import sklearn
    import xgboost
    from rdkit import Chem, rdBase

    provenance = _provenance(
        getattr(sklearn, "__version__", "unknown"),
        getattr(xgboost, "__version__", "unknown"),
        rdBase.rdkitVersion,
    )

    smiles_list = [str(r.get("smiles") or "").strip() for r in records]
    mol_ids = [r.get("mol_id") for r in records]

    scorer = _load_scorer()

    outputs = []
    for idx in range(len(records)):
        smiles = smiles_list[idx]
        mol_id = mol_ids[idx]
        # RAScorerXGB.ecfp() does not guard against an unparseable SMILES, so pre-validate with RDKit.
        mol = Chem.MolFromSmiles(smiles) if smiles else None
        if mol is None:
            reason = "empty SMILES" if not smiles else "RDKit could not parse SMILES"
            outputs.append(_null_record(smiles, mol_id, reason, provenance))
            continue
        try:
            score = float(scorer.predict(smiles))
        except Exception as exc:  # noqa: BLE001 - one bad molecule degrades to a null record, never a crash
            reason = "prediction failed: {0}: {1}".format(type(exc).__name__, exc)
            outputs.append(_null_record(smiles, mol_id, reason, provenance))
            continue
        outputs.append(
            {
                "model": MODEL,
                # score is already P(route findable); identity into the synthesizability tier (UP = better).
                "endpoint_values": {"RAscore": score},
                # A single classifier probability: no native aleatoric/epistemic split -> uncertainty None
                # (schema rule CLAUDE.md 3: the reserved fields stay null rather than fabricated).
                "uncertainty": None,
                "raw": {
                    "smiles": smiles,
                    "mol_id": mol_id,
                    "RAscore": score,
                    "model_variant": MODEL_VARIANT,
                    "scale": {
                        "min": RASCORE_MIN,
                        "max": RASCORE_MAX,
                        "direction": "higher = more likely a synthetic route exists (more synthesizable)",
                    },
                    "tier": "synthesizability rung 2 of 3 (SAscore -> RAscore -> AiZynthFinder)",
                },
                "provenance": provenance,
            }
        )
    return outputs


def main(argv=None):
    # type: (Optional[list]) -> int
    parser = argparse.ArgumentParser(
        description="RAscore retrosynthetic-accessibility classifier (XGB/ECFP-counts) adapter (uniform model CLI)."
    )
    parser.add_argument("--input", required=True, type=Path, help="pipeline input (InputRecord JSON, JSON array, or .smi)")
    parser.add_argument("--output", required=True, type=Path, help="where to write the OutputRecord JSON")
    parser.add_argument("--gpu", type=int, default=None, help="ignored (XGB RAscore is CPU-only); present for the uniform CLI")
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
