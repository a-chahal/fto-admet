#!/usr/bin/env python
"""Evaluate the in-house FAME3R model on the shipped held-out test.sdf (a build-time step, NOT the adapter).

This is the evidence that the model trained by ``build_model.py`` works. It scores every atom of every
molecule in the shipped ``metatrans_autoannotated_cleaned/test.sdf`` with the SAME marked-SMILES ->
``predict_proba[:, 1]`` pipeline the adapter uses (so the numbers reflect real inference), and reports:

  - per-atom ROC-AUC and average precision (PR-AUC) over all atoms - the ranking quality of the raw SoM
    probability against the auto-annotated SoM labels (strong signal despite heavy class imbalance);
  - top-k site-of-metabolism recovery (k = 1, 2, 3): the fraction of molecules (that carry >= 1 labeled
    SoM) for which at least one true SoM is ranked within the k highest-probability atoms. This is how the
    FAME 3 / FAME3R papers report SoM recovery, and it is the metric that matters for the metabolism
    endpoint, which co-ranks atoms ordinally (t42, F-2).

Atoms are marked and labelled directly from the SDF (never via a SMILES round-trip), so each probability
stays aligned to its RDKit atom index and SoM label - the same alignment ``build_model.py`` trains on.

USAGE (on the box, inside this model's pixi env, after build_model.py):

    pixi run --manifest-path pixi.toml python evaluate_model.py \
        --test-sdf data/metatrans_autoannotated_cleaned/test.sdf \
        --models data/models

It writes ``eval_metrics.json`` into the models dir and prints the summary. The metrics are recorded in
the README and the task result note.
"""

from __future__ import annotations

import argparse
import json
from ast import literal_eval
from pathlib import Path

import joblib
from rdkit.Chem.rdmolfiles import SDMolSupplier
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import make_pipeline

from fame3r import FAME3RVectorizer

# One source of truth for the marked-SMILES convention, descriptor radius, and artifact name.
from run import CLASSIFIER_FILE, RADIUS, atom_to_marked_smiles


def _score_molecule(clf, mol) -> list[float]:
    """Per-atom SoM probability for every atom of ``mol`` (same scheme run.py uses at inference)."""
    marked = [[atom_to_marked_smiles(mol, i)] for i in range(mol.GetNumAtoms())]
    return list(clf.predict_proba(marked)[:, 1])


def evaluate(test_sdf: Path, models_dir: Path) -> dict:
    classifier = joblib.load(models_dir / CLASSIFIER_FILE)
    clf = make_pipeline(FAME3RVectorizer(input="smiles", radius=RADIUS).fit(), classifier)

    all_labels: list[int] = []
    all_probs: list[float] = []
    topk_hits = {1: 0, 2: 0, 3: 0}
    n_mols_with_som = 0
    n_mols = 0
    n_soms = 0

    supplier = SDMolSupplier(str(test_sdf))
    for mol in supplier:
        if mol is None or mol.GetNumAtoms() == 0:
            continue
        n_mols += 1
        soms = set(literal_eval(mol.GetProp("soms"))) if mol.HasProp("soms") else set()
        probs = _score_molecule(clf, mol)
        labels = [1 if i in soms else 0 for i in range(mol.GetNumAtoms())]

        all_probs.extend(probs)
        all_labels.extend(labels)
        n_soms += len(soms)

        if not soms:
            continue
        n_mols_with_som += 1
        # Atoms ranked by descending SoM probability; does a true SoM land in the top k?
        ranked = sorted(range(len(probs)), key=lambda i: probs[i], reverse=True)
        for k in topk_hits:
            if any(idx in soms for idx in ranked[:k]):
                topk_hits[k] += 1

    metrics = {
        "n_molecules_scored": n_mols,
        "n_molecules_with_som": n_mols_with_som,
        "n_atoms": len(all_labels),
        "n_som_atoms": n_soms,
        "per_atom_roc_auc": round(roc_auc_score(all_labels, all_probs), 4),
        "per_atom_average_precision": round(average_precision_score(all_labels, all_probs), 4),
        "top1_som_recovery": round(topk_hits[1] / n_mols_with_som, 4),
        "top2_som_recovery": round(topk_hits[2] / n_mols_with_som, 4),
        "top3_som_recovery": round(topk_hits[3] / n_mols_with_som, 4),
        "test_sdf": str(test_sdf),
    }
    return metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the in-house FAME3R model on held-out test.sdf.")
    parser.add_argument("--test-sdf", required=True, type=Path, help="shipped test.sdf (labeled SoMs)")
    parser.add_argument("--models", required=True, type=Path, help="models dir with the trained classifier")
    args = parser.parse_args(argv)

    metrics = evaluate(args.test_sdf, args.models)
    (args.models / "eval_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
