"""Hansen 2009 Ames mutagenicity benchmark loader - the ames_mutagenicity binary target.

File: ``$FTO_ADMET_ROOT/training/data/hansen_ames/Mutagenicity_N6512.csv`` (Hansen et al., "Benchmark Data
Set for in Silico Prediction of Ames Mutagenicity", J Chem Inf Model 2009, 49(9):2077-2081; downloaded from
the authors' TU-Berlin benchmark page http://doc.ml.tu-berlin.de/toxbenchmark/). Columns: CAS_NO, Source
(CCRIS/VITIC/EPA/GENETOX), Activity (1 = mutagenic / Ames-positive, 0 = non-mutagenic), Steroid, WDI,
Canonical_Smiles, REFERENCE. 6512 rows.

This loader standardizes each SMILES and returns the binary Ames label. Where several source rows
standardize to the same InChIKey, the label is taken as the max (positive-dominant: a compound is
Ames-positive if any curated source calls it positive). Recipe target ames_mutagenicity (label ``ames``,
logit transform, logistic calibration).
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
    return root / "training" / "data" / "hansen_ames" / "Mutagenicity_N6512.csv"


@register("hansen_ames")
def load() -> pd.DataFrame:
    """Return DataFrame[smiles, mol_id, label, inchikey, inchikey14] for Hansen Ames mutagenicity.

    ``label`` is the binary Ames outcome (1 = mutagenic, 0 = non-mutagenic). Each SMILES is standardized
    identically to the exclusion index; rows with an unparseable structure or a missing/invalid label are
    dropped; duplicates by InChIKey take the positive-dominant (max) label.
    """
    df = pd.read_csv(_path())

    labels: dict[str, int] = defaultdict(int)
    rep: dict[str, tuple[str, str, str]] = {}   # inchikey -> (smiles, inchikey14, mol_id)
    for _, r in df.iterrows():
        a = r.get("Activity")
        if pd.isna(a) or int(a) not in (0, 1):
            continue
        std = standardize(str(r["Canonical_Smiles"]))
        if std is None:
            continue
        smiles, ik, ik14, _mw = std
        labels[ik] = max(labels[ik], int(a))
        rep.setdefault(ik, (smiles, ik14, str(r.get("CAS_NO", ""))))

    rows = []
    for ik, y in labels.items():
        smiles, ik14, mol_id = rep[ik]
        rows.append({"smiles": smiles, "mol_id": mol_id,
                     "label": int(y), "inchikey": ik, "inchikey14": ik14})
    return pd.DataFrame(rows)
