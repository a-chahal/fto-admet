#!/usr/bin/env python
"""Train the pipeline's in-house FAME3R model on the box (a build-time step, NOT the adapter).

WHY THIS EXISTS
---------------
FAME3R v2.0.0 (molinfo-vienna/FAME3R) ships as scikit-learn *components* only - it ships NO trained
model. The repo ships ``train.sdf`` / ``test.sdf`` precisely so the model is trained in-house. This
script trains this pipeline's PRODUCTION FAME3R model: a ``RandomForestClassifier`` fit on the shipped
``metatrans_autoannotated_cleaned/train.sdf`` (a MetaTrans-derived, auto-annotated, cleaned
site-of-metabolism set), using the FAME3R paper / CLI default hyperparameters. It is a legitimately
trained FAME3R model on the shipped dataset - an honest, documented modeling choice.

It is deliberately NOT the gated MetaQSAR models (Zenodo DOI 10.5281/zenodo.17223468, *restricted access*
plus a Universita degli Studi di Milano commercial license). This pipeline does not use those; it trains
on the openly shipped train.sdf and reports honest held-out metrics on the shipped test.sdf
(``evaluate_model.py``). run.py stamps ``model_source`` onto every record so provenance is explicit.

The produced artifacts (``random_forest_classifier.joblib``, ``fame3r_score_estimator.joblib``,
``model_source.txt``) land in the models dir (default ``<this dir>/data/models``, override with
FAME3R_MODELS_DIR). They are WEIGHTS: gitignored (the folder is ``data/``, repo-wide ignored), never
committed - they are rebuilt on the box from the committed lock + this script.

USAGE (on the box, inside this model's pixi env):

    pixi run --manifest-path pixi.toml python build_model.py \
        --train-sdf data/metatrans_autoannotated_cleaned/train.sdf \
        --out data/models
    pixi run --manifest-path pixi.toml python evaluate_model.py \
        --test-sdf data/metatrans_autoannotated_cleaned/test.sdf \
        --models data/models

The hyperparameters below are the FAME3R paper / CLI defaults (see the tutorial + ``fame3r train``).
"""

from __future__ import annotations

import argparse
from ast import literal_eval
from pathlib import Path

import joblib
from rdkit.Chem.rdmolfiles import SDMolSupplier
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import make_pipeline

from fame3r import FAME3RScoreEstimator, FAME3RVectorizer

# Import the adapter's own atom-marking helper so training and inference use the IDENTICAL marked-SMILES
# convention (RDKit atom -> atom-mapped SMILES). One source of truth avoids a train/serve feature skew.
from run import RADIUS, atom_to_marked_smiles

# FAME3R paper / CLI default hyperparameters for the random forest (PythonAPI.ipynb cell "Training").
RF_KWARGS = dict(
    n_estimators=250,
    max_depth=None,
    min_samples_split=2,
    min_samples_leaf=1,
    max_features="sqrt",
    class_weight="balanced_subsample",
    n_jobs=-1,
    random_state=0,  # deterministic artifact (upstream leaves this unset; we fix it for reproducibility)
)
N_NEIGHBORS = 3  # FAME3RScoreEstimator default (paper value)

MODEL_SOURCE = (
    "fame3r-inhouse: RandomForestClassifier (FAME3R paper/CLI default hyperparameters, radius=5) trained "
    "by build_model.py on FAME3R's shipped docs/source/tutorials/data/metatrans_autoannotated_cleaned/"
    "train.sdf (a MetaTrans-derived, auto-annotated, cleaned site-of-metabolism set). This is the "
    "pipeline's production FAME3R model - an honest in-house training on the shipped dataset, evaluated on "
    "the shipped test.sdf (see evaluate_model.py / README for held-out metrics). NOT the gated MetaQSAR "
    "models (Zenodo 10.5281/zenodo.17223468, restricted access + UniMi commercial license). "
    "Dataset/model license: CC-BY-NC-4.0 (non-commercial research)."
)


def _load_atoms_and_labels(train_sdf: Path) -> tuple[list[str], list[bool]]:
    """Read the SDF: each atom -> (atom-mapped SMILES, is-a-known-SoM). Mirrors the FAME3R tutorial."""
    supplier = SDMolSupplier(str(train_sdf))
    marked: list[str] = []
    labels: list[bool] = []
    for mol in supplier:
        if mol is None:
            continue
        soms = set(literal_eval(mol.GetProp("soms"))) if mol.HasProp("soms") else set()
        for atom in mol.GetAtoms():
            marked.append(atom_to_marked_smiles(mol, atom.GetIdx()))
            labels.append(atom.GetIdx() in soms)
    return marked, labels


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train the in-house FAME3R model artifacts.")
    parser.add_argument("--train-sdf", required=True, type=Path, help="shipped train.sdf (labeled SoMs)")
    parser.add_argument("--out", required=True, type=Path, help="models output directory")
    args = parser.parse_args(argv)

    marked, labels = _load_atoms_and_labels(args.train_sdf)
    n_pos = sum(labels)
    print(f"loaded {len(marked)} atoms ({n_pos} SOMs) from {args.train_sdf}", flush=True)

    # Classifier: full FAME3R descriptor set (fingerprint + physicochemical + topological).
    clf = make_pipeline(
        FAME3RVectorizer(input="smiles", radius=RADIUS),
        RandomForestClassifier(**RF_KWARGS),
    )
    print("training random forest classifier ...", flush=True)
    clf.fit([[s] for s in marked], labels)

    # FAME score estimator: fingerprint-only (Tanimoto is defined on binary vectors), n_neighbors=3.
    score = make_pipeline(
        FAME3RVectorizer(input="smiles", radius=RADIUS, output=["fingerprint"]),
        FAME3RScoreEstimator(n_neighbors=N_NEIGHBORS),
    )
    print("training FAME score estimator ...", flush=True)
    score.fit([[s] for s in marked], labels)

    args.out.mkdir(parents=True, exist_ok=True)
    # Save the BARE estimators (same layout the fame3r CLI writes). run.py rebuilds the input="smiles"
    # vectorizer around them; evaluate_model.py scores the held-out test.sdf the same way.
    joblib.dump(clf.named_steps["randomforestclassifier"], args.out / "random_forest_classifier.joblib", compress=3)
    joblib.dump(score.named_steps["fame3rscoreestimator"], args.out / "fame3r_score_estimator.joblib", compress=3)
    (args.out / "model_source.txt").write_text(MODEL_SOURCE + "\n", encoding="utf-8")
    print(f"wrote model artifacts to {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
