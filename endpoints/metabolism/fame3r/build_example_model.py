#!/usr/bin/env python
"""Build the FAME3R EXAMPLE model artifacts on the box (a build-time step, NOT the adapter).

WHY THIS EXISTS
---------------
FAME3R v2.0.0 (molinfo-vienna/FAME3R) ships as scikit-learn *components* only - it ships NO trained
model. The production, paper-grade models are trained on the MetaQSAR database and are a GATED download:
Zenodo DOI 10.5281/zenodo.17223468 is *restricted access* (owner must grant a request) and the
MetaQSAR-derived models additionally require a commercial license from the Universita degli Studi di
Milano for for-profit use. That gated artifact could not be fetched in the headless build session
(status = needs_aaran; see README + .harness/results/t26-model-fame3r.json).

To still PROVE the adapter end-to-end (env resolves, atom marking works, `predict_proba[:, 1]` returns a
per-atom probability table, `FAME3RScore` computes), this script trains the upstream TUTORIAL EXAMPLE
model - byte-for-byte the recipe in FAME3R's own `docs/source/tutorials/PythonAPI.ipynb`, on the
`metatrans_autoannotated_cleaned` dataset shipped in that same tutorial. Upstream states plainly that this
example model "is not expected to be useful for real metabolism prediction"; it is a stand-in that
exercises the machinery, exactly like the FTO-43 placeholder SMILES fixture. run.py stamps
`model_source` onto every record so no output ever silently claims to be the MetaQSAR paper model.

The produced artifacts (`random_forest_classifier.joblib`, `fame3r_score_estimator.joblib`,
`model_source.txt`) land in the models dir (default `<this dir>/data/models`, override with
FAME3R_MODELS_DIR). They are WEIGHTS: gitignored (the folder is `data/`, repo-wide ignored), never
committed. Swapping in the real MetaQSAR models is a drop-in replacement of these three files.

USAGE (on the box, inside this model's pixi env):

    pixi run --manifest-path pixi.toml python build_example_model.py \
        --train-sdf data/metatrans_autoannotated_cleaned/train.sdf \
        --out data/models

The hyperparameters below are the FAME3R paper / CLI defaults (see the tutorial + `fame3r train`).
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
    random_state=0,  # deterministic example artifact (upstream leaves this unset; we fix it for reproducibility)
)
N_NEIGHBORS = 3  # FAME3RScoreEstimator default (paper value)

MODEL_SOURCE = (
    "fame3r-tutorial-example: RandomForestClassifier trained by build_example_model.py on FAME3R's shipped "
    "docs/source/tutorials/data/metatrans_autoannotated_cleaned/train.sdf (upstream: 'not expected to be "
    "useful for real metabolism prediction'). NOT the MetaQSAR paper model. Replace with the gated Zenodo "
    "10.5281/zenodo.17223468 MetaQSAR models (restricted access + UniMi commercial license) for production."
)


def _load_atoms_and_labels(train_sdf: Path) -> tuple[list[str], list[bool]]:
    """Read the tutorial SDF: each atom -> (atom-mapped SMILES, is-a-known-SOM). Mirrors the tutorial."""
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
    parser = argparse.ArgumentParser(description="Train the FAME3R tutorial-example model artifacts.")
    parser.add_argument("--train-sdf", required=True, type=Path, help="tutorial train.sdf (labeled SOMs)")
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
    # Save the BARE estimators (same layout the fame3r CLI writes), so the real MetaQSAR joblibs from
    # Zenodo drop in unchanged. run.py rebuilds the input="smiles" vectorizer around them.
    joblib.dump(clf.named_steps["randomforestclassifier"], args.out / "random_forest_classifier.joblib", compress=3)
    joblib.dump(score.named_steps["fame3rscoreestimator"], args.out / "fame3r_score_estimator.joblib", compress=3)
    (args.out / "model_source.txt").write_text(MODEL_SOURCE + "\n", encoding="utf-8")
    print(f"wrote model artifacts to {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
