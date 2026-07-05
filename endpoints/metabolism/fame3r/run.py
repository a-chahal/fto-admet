#!/usr/bin/env python
"""fame3r adapter - per-atom site-of-metabolism (SoM) probability + FAME3RScore applicability domain.

Uniform model CLI (CLAUDE.md §2, SETTLED §6):

    python run.py --input <path> --output <path> [--gpu N]

FAME3R (molinfo-vienna/FAME3R, Jacob et al., J. Cheminform. 2026) replaces the legacy Java FAME 3. It is
packaged as scikit-learn COMPONENTS, not a turnkey CSV writer (IO_SPEC §1 #9), so this adapter builds the
per-atom table itself:

  - Per-atom SoM = a scikit-learn ``RandomForestClassifier.predict_proba(...)[:, 1]`` = probability the
    atom is a site of metabolism (0-1, **UP = more likely SoM**). Atoms are fed as ATOM-MARKED SMILES:
    RDKit marks one atom with an atom-map number (``atom_to_marked_smiles``) and ``FAME3RVectorizer``
    (input="smiles") turns that atom's environment into the FAME3R descriptor vector. FAME3R ships NO
    ``atom_id`` column, so this adapter attaches the RDKit atom index itself (the marked atom keeps its
    index through canonicalization, so ``probs[i]`` is the SoM probability of RDKit atom ``i``).
  - Applicability domain / reliability = a SEPARATE ``FAME3RScoreEstimator(n_neighbors=3)`` whose feature
    is ``FAME3RScore`` = mean Tanimoto similarity to the k nearest reference atoms (0-1, UP = more
    in-domain). This is the reliability signal - NOT Shannon entropy, which the package computes for its
    own CLI but which the IO_SPEC does not use here.

LANDMINE (CLAUDE.md §4, IO_SPEC §1 #9) - the exact points a plausible guess is wrong:
  (1) NO hard-coded 0.3 threshold. 0.3 was the legacy Java FAME 3 decision threshold; FAME3R emits a raw
      probability. This adapter emits the raw per-atom probability and applies NO binarization. The
      metabolism aggregator (t42) reconciles FAME3R vs SMARTCyp by ORDINAL co-ranking of atoms, never by
      thresholding or averaging (F-2).
  (2) DIRECTION: higher FAME3R probability = more likely SoM - the OPPOSITE of SMARTCyp, where a lower
      Score/Ranking = more likely SoM. Do not average the two raw scales; co-rank ordinally (t42).

WHERE THE MODEL COMES FROM: FAME3R ships no trained model - the repo ships ``train.sdf`` / ``test.sdf``
precisely so the model is trained in-house. This pipeline's production FAME3R model is a
``RandomForestClassifier`` trained by ``build_model.py`` on the shipped
``metatrans_autoannotated_cleaned/train.sdf`` (a MetaTrans-derived, auto-annotated, cleaned SoM set) and
evaluated on the shipped ``test.sdf`` (metrics in README). This is a legitimately trained FAME3R model on
the shipped dataset - an honest, documented modeling choice - NOT the gated MetaQSAR models (Zenodo
10.5281/zenodo.17223468, restricted access + a UniMi commercial license), which this pipeline does not use.
run.py loads whatever models dir it is pointed at (FAME3R_MODELS_DIR, else ``<this dir>/data/models``) and
stamps ``model_source`` onto every record, so provenance is never silently misrepresented.

This runs in the model's ISOLATED pixi env (fame3r + cdpkit + rdkit + scikit-learn) and so CANNOT import
``core``; it emits plain JSON matching ``core.schemas.OutputRecord`` and the dispatcher validates it on
collection. ``--gpu`` is accepted and ignored (``requires_gpu=False``); FAME3R is CPU-only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

MODEL = "fame3r"

# FAME3R circular-descriptor radius. 5 is the paper/CLI/tutorial default; training and inference MUST use
# the same radius (the classifier's feature space is radius-dependent).
RADIUS = 5

# Trained artifacts (WEIGHTS - gitignored, never committed, rebuilt on the box by build_model.py). Default
# under this model's data/ dir; an alternate models dir can be pointed at via FAME3R_MODELS_DIR.
_DEFAULT_MODELS_DIR = Path(__file__).resolve().parent / "data" / "models"
CLASSIFIER_FILE = "random_forest_classifier.joblib"
SCORE_FILE = "fame3r_score_estimator.joblib"
SOURCE_FILE = "model_source.txt"


def models_dir() -> Path:
    """Resolve the trained-model directory: FAME3R_MODELS_DIR override, else the packaged default."""
    override = os.environ.get("FAME3R_MODELS_DIR")
    return Path(override) if override else _DEFAULT_MODELS_DIR


def atom_to_marked_smiles(mol: Any, idx: int) -> str:
    """Return a SMILES for ``mol`` with atom ``idx`` marked by atom-map number 1 (FAME3R input="smiles").

    This is the exact helper from FAME3R's PythonAPI tutorial: it copies the molecule, tags one atom with
    an atom-map number, and emits SMILES. CDPKit (inside FAME3RVectorizer) reads that map number to pick
    the atom whose environment becomes the descriptor vector. The map number rides through RDKit's
    canonicalization, so the marked atom is still original RDKit index ``idx``.
    """
    from rdkit.Chem.rdchem import Mol
    from rdkit.Chem.rdmolfiles import MolToSmiles

    marked = Mol(mol)
    marked.GetAtomWithIdx(idx).SetAtomMapNum(1)
    return MolToSmiles(marked)


def _fame3r_version() -> str:
    try:
        return version("fame3r")
    except PackageNotFoundError:  # pragma: no cover
        return "unknown"


def _model_source(mdir: Path) -> str:
    """The provenance stamp for the loaded artifacts (tutorial-example vs the real MetaQSAR models)."""
    src = mdir / SOURCE_FILE
    if src.exists():
        return src.read_text(encoding="utf-8").strip()
    return "unknown (no model_source.txt beside the joblib artifacts)"


def _provenance(mdir: Path) -> dict[str, Any]:
    """Provenance stamped onto every emitted record. Versions read live; model_source never fabricated."""
    return {
        "model": MODEL,
        "method": "FAME3R RandomForestClassifier.predict_proba[:,1] per-atom SoM probability (atom-marked "
        "SMILES via RDKit; CDPKit descriptors, radius=5) + FAME3RScoreEstimator(n_neighbors=3) AD",
        "fame3r_version": _fame3r_version(),
        "model_source": _model_source(mdir),
        "citation": "Jacob RA, et al. FAME 3R. J. Cheminform. 2026. doi:10.1186/s13321-026-01161-1",
        "license": "code: MIT (CODE-PKG). In-house model trained on the shipped MetaTrans-derived "
        "auto-annotated cleaned train.sdf: CC-BY-NC-4.0 (non-commercial research; the dataset inherits the "
        "FAME3R data license; for-profit use needs the upstream commercial terms).",
        "direction": "higher SoM probability = more likely site of metabolism (OPPOSITE of SMARTCyp)",
    }


class _Predictor:
    """Loads the two FAME3R estimators once and scores whole molecules atom-by-atom.

    The bare estimators are loaded (same layout the fame3r CLI writes / the Zenodo models use) and wrapped
    in an input="smiles" pipeline so we can feed RDKit-marked SMILES. Fitting the vectorizer is a stateless
    setup call (it only registers feature names), so it is safe to (re)fit an already-trained estimator's
    front-end vectorizer.
    """

    def __init__(self, mdir: Path) -> None:
        import joblib
        from sklearn.pipeline import make_pipeline

        from fame3r import FAME3RVectorizer

        clf_path = mdir / CLASSIFIER_FILE
        score_path = mdir / SCORE_FILE
        if not clf_path.exists():
            raise FileNotFoundError(
                f"missing trained classifier {clf_path}. FAME3R ships no model; train the in-house model on "
                f"the box with build_model.py (--train-sdf data/.../train.sdf --out data/models). See README."
            )
        classifier = joblib.load(clf_path)
        self._clf = make_pipeline(FAME3RVectorizer(input="smiles", radius=RADIUS).fit(), classifier)

        self._score = None
        if score_path.exists():
            estimator = joblib.load(score_path)
            # FAME3RScore is defined on fingerprint-only (binary) features - match how it was trained.
            self._score = make_pipeline(
                FAME3RVectorizer(input="smiles", radius=RADIUS, output=["fingerprint"]).fit(), estimator
            )

    def score_molecule(self, smiles: str) -> tuple[list[dict[str, Any]], str | None]:
        """Return (per-atom rows, error). Each row: atom_index, element, som_probability, fame3r_score."""
        from rdkit.Chem.rdmolfiles import MolFromSmiles

        mol = MolFromSmiles(smiles)
        if mol is None:
            return [], "RDKit could not parse SMILES"
        n = mol.GetNumAtoms()
        if n == 0:
            return [], "molecule has no atoms"

        marked = [[atom_to_marked_smiles(mol, i)] for i in range(n)]
        probs = self._clf.predict_proba(marked)[:, 1]
        if self._score is not None:
            fame_scores = self._score.predict(marked)
        else:
            fame_scores = [None] * n

        rows: list[dict[str, Any]] = []
        for i in range(n):
            fs = fame_scores[i]
            rows.append(
                {
                    "atom_index": i,
                    "element": mol.GetAtomWithIdx(i).GetSymbol(),
                    "som_probability": _f(probs[i]),
                    "fame3r_score": _clamp01(_f(fs)) if fs is not None else None,
                }
            )
        return rows, None


def _f(value: Any) -> float | None:
    """Coerce a numpy/py scalar to a plain finite float, or None if missing/non-finite."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _clamp01(value: float | None) -> float | None:
    """FAME3RScore is a mean Tanimoto in [0, 1]; clamp defensively against float wobble for the AD field."""
    if value is None:
        return None
    return min(1.0, max(0.0, value))


def parse_inputs(text: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse ``--input`` into ``(records, single)`` - identical contract to the other adapters.

    Accepts a single InputRecord object (single=True), a JSON array of them, or a ``.smi`` file
    (``<SMILES><whitespace><title>`` per line, ``#`` comments).
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


def record_for(rec: dict[str, Any], predictor: _Predictor, provenance: dict[str, Any]) -> dict[str, Any]:
    """Compute one OutputRecord-shaped dict for a single input molecule.

    endpoint_values carries only molecule-level SCALAR summaries derived from the per-atom table (the
    task forbids cramming the per-atom vector into scalar endpoint_values). The full per-atom SoM table
    lives in ``raw.atoms`` (the verbatim payload the metabolism aggregator co-ranks at t42), and the
    per-atom FAME3RScore reliability lives in ``uncertainty`` (schema rule, CLAUDE.md §3).
    """
    smiles = str(rec.get("smiles") or "").strip()
    mol_id = rec.get("mol_id")
    base: dict[str, Any] = {"model": MODEL, "provenance": provenance}

    if not smiles:
        rows, err = [], "empty SMILES"
    else:
        rows, err = predictor.score_molecule(smiles)

    if err is not None or not rows:
        return {
            **base,
            "endpoint_values": {"max_som_probability": None, "top_som_atom_index": None, "n_atoms_scored": 0},
            "uncertainty": None,
            "raw": {"error": err or "no atoms scored", "smiles": smiles, "mol_id": mol_id},
        }

    probs = [(r["atom_index"], r["som_probability"]) for r in rows if r["som_probability"] is not None]
    top_idx, top_prob = (max(probs, key=lambda p: p[1]) if probs else (None, None))
    fame_scores = [r["fame3r_score"] for r in rows if r["fame3r_score"] is not None]
    top_fame_score = next((r["fame3r_score"] for r in rows if r["atom_index"] == top_idx), None)

    endpoint_values = {
        # The molecule's softest spot: the single highest per-atom SoM probability (UP = more labile).
        "max_som_probability": top_prob,
        # Which RDKit atom that is (co-ranking / reporting handle).
        "top_som_atom_index": top_idx,
        "n_atoms_scored": len(rows),
    }

    # AD/reliability: FAME3RScore. ad_index carries the reliability of the top-SoM prediction (0-1, UP =
    # more in-domain); the full per-atom FAME3RScore list + mean go in extra so nothing native is lost.
    # This is a native signal only; the operational AD rule is DEFERRED (CLAUDE.md §4a).
    uncertainty = {
        "ad_index": _clamp01(top_fame_score),
        "extra": {
            "fame3r_score_per_atom": [r["fame3r_score"] for r in rows],
            "fame3r_score_mean": _f(sum(fame_scores) / len(fame_scores)) if fame_scores else None,
            "ad_signal": "FAME3RScore = mean Tanimoto to k=3 nearest reference atoms (UP = more in-domain)",
        },
    }

    return {
        **base,
        "endpoint_values": endpoint_values,
        "uncertainty": uncertainty,
        "raw": {
            "smiles": smiles,
            "mol_id": mol_id,
            # The per-atom SoM table - the load-bearing output. atom_index is the RDKit index this adapter
            # attaches (FAME3R ships no atom_id). Consumed by t42 via ORDINAL co-ranking with SMARTCyp.
            "atoms": rows,
            "threshold_policy": "none applied; raw predict_proba[:,1] emitted. The legacy Java FAME 3 used "
            "0.3; FAME3R does not. Binarization/co-ranking is deferred to the t42 metabolism aggregator "
            "(F-2, ordinal co-rank with SMARTCyp; never average the raw scales).",
            "radius": RADIUS,
        },
    }


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")  # keep stdout clean; the real output is the JSON file
    parser = argparse.ArgumentParser(description="FAME3R per-atom site-of-metabolism adapter (uniform model CLI).")
    parser.add_argument("--input", required=True, type=Path, help="pipeline input (InputRecord JSON, JSON array, or .smi)")
    parser.add_argument("--output", required=True, type=Path, help="where to write the OutputRecord JSON")
    parser.add_argument("--gpu", type=int, default=None, help="ignored (FAME3R is CPU-only); present for the uniform CLI")
    args = parser.parse_args(argv)

    mdir = models_dir()
    provenance = _provenance(mdir)
    predictor = _Predictor(mdir)  # loads models once; raises a clear error if the artifacts are absent

    records, single = parse_inputs(args.input.read_text(encoding="utf-8"))
    outputs = [record_for(rec, predictor, provenance) for rec in records]
    payload: Any = outputs[0] if (single and len(outputs) == 1) else outputs

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
