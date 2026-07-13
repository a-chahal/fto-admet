"""FDA DILIrank / DILIst drug-induced liver injury loader - the dili binary target.

Source: FDA Liver Toxicity Knowledge Base (LTKB) DILIst dataset (Thakkar et al.), the binary
DILI-concern derivative of DILIrank: 1279 drugs classified 1 = DILI-positive (768) / 0 = DILI-negative
(511), oral route. FDA distributes DILIst as drug NAMES only (no structures), so structures were resolved
by drug name via the PubChem PUG-REST name lookup on the box (property "SMILES"), then cached.

Files (``$FTO_ADMET_ROOT/training/data/dilirank/``):
  - ``dilirank_raw`` : FDA DILIrank v2.0/v1.0 xlsx (severity-ranked, 4 classes; reference only).
  - ``dilist.csv``   : DILIst binary table (DILIST_ID, CompoundName, dili_label, route) from FDA media/160597.
  - ``dilist_resolved.csv`` : dilist.csv + PubChem-resolved SMILES (1188 of 1279 names resolved; 91 names,
    mostly mixtures/salts/ambiguous, did not map and carry a null SMILES).
See PROVENANCE.txt for the exact FDA source URLs, PubChem resolution method, and the unresolved list.

This loader reads ``dilist_resolved.csv``, standardizes each resolved SMILES identically to the exclusion
index, and returns the binary DILI label. Rows without a resolved structure are dropped. Recipe target dili
(dataset ``dilirank``, label ``dili_label``, logit transform, logistic calibration).
"""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path

import pandas as pd

from training.datasets import register
from training.standardize import standardize


def _path() -> Path:
    root = Path(os.environ.get("FTO_ADMET_ROOT", "."))
    return root / "training" / "data" / "dilirank" / "dilist_resolved.csv"


@register("dilirank")
def load() -> pd.DataFrame:
    """Return DataFrame[smiles, mol_id, label, inchikey, inchikey14] for FDA DILIst DILI hazard.

    ``label`` is the binary DILIst class (1 = DILI-positive, 0 = DILI-negative). Each PubChem-resolved
    SMILES is standardized identically to the exclusion index; rows with a null/unresolved structure or an
    unparseable one are dropped; duplicate InChIKeys take the positive-dominant (max) label.
    """
    df = pd.read_csv(_path())

    labels: dict[str, int] = defaultdict(int)
    rep: dict[str, tuple[str, str, str]] = {}   # inchikey -> (smiles, inchikey14, mol_id)
    for _, r in df.iterrows():
        y = r.get("dili_label")
        smi = r.get("SMILES")
        if pd.isna(y) or int(y) not in (0, 1):
            continue
        if not isinstance(smi, str) or not smi.strip():
            continue
        std = standardize(smi)
        if std is None:
            continue
        smiles, ik, ik14, _mw = std
        labels[ik] = max(labels[ik], int(y))
        rep.setdefault(ik, (smiles, ik14, str(r.get("DILIST_ID", ""))))

    rows = []
    for ik, y in labels.items():
        smiles, ik14, mol_id = rep[ik]
        rows.append({"smiles": smiles, "mol_id": mol_id,
                     "label": int(y), "inchikey": ik, "inchikey14": ik14})
    return pd.DataFrame(rows)
