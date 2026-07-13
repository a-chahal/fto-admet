"""Original Tox21 Challenge (2014) loader - the 12 nuclear-receptor / stress-response pathway targets.

File: ``$FTO_ADMET_ROOT/training/data/tox21_original/tox21_labels.csv``, derived on the box from the
ORIGINAL Tox21 Data Challenge training set ``tox21_10k_data_all.sdf`` (NIH/NCATS Tripod,
https://tripod.nih.gov/tox21/challenge/data.jsp). This is the authentic challenge data, NOT the
TDC/MoleculeNet repack (which dissolves the challenge splits and zero-fills missing labels). Each SDF
record carries a subset of the 12 assay outcomes as properties; the conversion script read every record
with RDKit, extracted the canonical SMILES + DSSTox_CID + the 12 assay columns, and wrote one CSV row per
compound (11761 rows; 3 records were unparseable). A blank cell means the compound was NOT tested in that
assay and is dropped for that pathway.

The loader takes ``assay=`` (one of the 12 recipe keys) and returns only the rows measured in that assay,
with the binary label (1 = active/toxic, 0 = inactive). Duplicate structures (by standardized InChIKey) are
aggregated positive-dominant (max), matching the other binary tox loaders. Recipe feature_group tox21
(label ``assay_label``, logit transform, logistic calibration).
"""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path

import pandas as pd

from training.datasets import register
from training.standardize import standardize

# recipe key -> CSV column (same key; the raw SDF tags NR-AR / SR-p53 were normalized during conversion).
ASSAYS = ("nr_ar", "nr_ar_lbd", "nr_ahr", "nr_aromatase", "nr_er", "nr_er_lbd",
          "nr_ppar_gamma", "sr_are", "sr_atad5", "sr_hse", "sr_mmp", "sr_p53")


def _path() -> Path:
    root = Path(os.environ.get("FTO_ADMET_ROOT", "."))
    return root / "training" / "data" / "tox21_original" / "tox21_labels.csv"


@register("tox21_original")
def load(assay: str = "nr_ar") -> pd.DataFrame:
    """Return DataFrame[smiles, mol_id, label, inchikey, inchikey14] for one Tox21 ``assay`` pathway.

    ``assay`` selects the pathway column (one of the 12 keys in ``ASSAYS``). Only compounds actually tested
    in that assay (non-blank cell) are returned; each SMILES is standardized identically to the exclusion
    index; rows with an unparseable structure are dropped; duplicate InChIKeys take the positive-dominant
    (max) label.
    """
    if assay not in ASSAYS:
        raise KeyError(f"tox21_original: unknown assay {assay!r} (have {list(ASSAYS)})")
    df = pd.read_csv(_path())

    labels: dict[str, int] = defaultdict(int)
    rep: dict[str, tuple[str, str, str]] = {}   # inchikey -> (smiles, inchikey14, mol_id)
    for _, r in df.iterrows():
        v = r.get(assay)
        if pd.isna(v) or str(v).strip() == "":
            continue
        y = int(float(v))
        if y not in (0, 1):
            continue
        std = standardize(str(r["smiles"]))
        if std is None:
            continue
        smiles, ik, ik14, _mw = std
        labels[ik] = max(labels[ik], y)
        rep.setdefault(ik, (smiles, ik14, str(r.get("mol_id", ""))))

    rows = []
    for ik, y in labels.items():
        smiles, ik14, mol_id = rep[ik]
        rows.append({"smiles": smiles, "mol_id": mol_id,
                     "label": int(y), "inchikey": ik, "inchikey14": ik14})
    return pd.DataFrame(rows)
