"""Carcinogenic Potency Database (CPDB) loader - the carcinogenicity binary target.

File: ``$FTO_ADMET_ROOT/training/data/cpdb/cpdb_carcinogen.csv``, built on the box from the authoritative
CPDB by Gold et al. (cpdb.thomas-slone.org): the per-chemical rodent carcinogenicity summary
(``CPDBChemical.xls``, sheet "Rats and Mice") joined by CAS to the CPDB structure export
(``chemical-structures.tab``, SMILES). See that dir's PROVENANCE.txt for the exact derivation.

Binary call (rodent carcinogenicity, the classic CPDB endpoint and the ancestral superset of the
ADMET-AI/TDC Carcinogens_Lagunin 278 set): a chemical is a carcinogen (1) if it has a positive result in
rat or mouse (a numeric TD50 or a listed target-site organ in either species/sex); a non-carcinogen (0) if
it was tested in rodents but negative in all (an en-dash "-" call); chemicals with no rodent test data are
excluded. 1343 chemicals carry both a structure and a call (748 positive / 595 negative).

Recipe target carcinogenicity (dataset ``cpdb``, label ``carcinogen``, logit transform, logistic
calibration). De-dup by InChIKey is positive-dominant (max), consistent with the other binary tox loaders.
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
    return root / "training" / "data" / "cpdb" / "cpdb_carcinogen.csv"


@register("cpdb")
def load() -> pd.DataFrame:
    """Return DataFrame[smiles, mol_id, label, inchikey, inchikey14] for CPDB rodent carcinogenicity.

    ``label`` is the binary carcinogen call (1 = carcinogenic in rat/mouse, 0 = tested negative). Each
    SMILES is standardized identically to the exclusion index; rows with an unparseable structure are
    dropped; duplicate InChIKeys take the positive-dominant (max) label.
    """
    df = pd.read_csv(_path())

    labels: dict[str, int] = defaultdict(int)
    rep: dict[str, tuple[str, str, str]] = {}   # inchikey -> (smiles, inchikey14, mol_id)
    for _, r in df.iterrows():
        y = r.get("carcinogen")
        if pd.isna(y) or int(y) not in (0, 1):
            continue
        std = standardize(str(r["SMILES"]))
        if std is None:
            continue
        smiles, ik, ik14, _mw = std
        labels[ik] = max(labels[ik], int(y))
        rep.setdefault(ik, (smiles, ik14, str(r.get("CAS", ""))))

    rows = []
    for ik, y in labels.items():
        smiles, ik14, mol_id = rep[ik]
        rows.append({"smiles": smiles, "mol_id": mol_id,
                     "label": int(y), "inchikey": ik, "inchikey14": ik14})
    return pd.DataFrame(rows)
