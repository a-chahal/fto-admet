"""FDA temporal-holdout human clearance loader (post-2018 approvals; recipe ``clearance__systemic_cl``).

There is NO clean legacy human-IV-CL benchmark: Lombardo 2018 (~1,352 compounds) is near-exhaustive for the
public domain and is pksmart's training set, so a legacy split would leak. Instead this is a deliberately
SMALL TEMPORAL HOLD-OUT: recent FDA approvals (post-2018, mostly 2019-2025) whose human systemic (total
plasma) clearance was published in the FDA clinical pharmacology review, the drug label, or primary PK
literature. Post-2018 approval makes them defensibly out of Lombardo 2018 (the leakage set the trainer
subtracts by InChIKey).

File: ``$FTO_ADMET_ROOT/training/data/fda_temporal_cl/fda_temporal_cl.csv``. The curated ``cl_ml_min_kg``
column is total plasma clearance in mL/min/kg (the units pksmart / Lombardo 2018 use). Every raw reported
value, its original units, and the exact conversion are kept alongside in the CSV (and in PROVENANCE.txt)
so each number is auditable. Molecules are standardized identically to the exclusion index (RDKit:
largest-fragment, uncharge, canonical tautomer) so the InChIKeys line up for leakage subtraction.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from training.datasets import register
from training.standardize import standardize


def _path() -> Path:
    root = Path(os.environ.get("FTO_ADMET_ROOT", "."))
    return root / "training" / "data" / "fda_temporal_cl" / "fda_temporal_cl.csv"


@register("fda_temporal_cl")
def load() -> pd.DataFrame:
    """Return DataFrame[smiles, mol_id, label, inchikey, inchikey14] for the FDA temporal CL hold-out.

    ``label`` is human systemic (total plasma) clearance in mL/min/kg. Each row's SMILES is re-standardized
    here (not trusted from the CSV) so the InChIKey matches the exclusion index; rows with a null label or an
    unparseable structure are dropped.
    """
    df = pd.read_csv(_path())
    rows = []
    for _, r in df.iterrows():
        y = r.get("cl_ml_min_kg")
        if pd.isna(y):
            continue
        std = standardize(str(r["smiles"]))
        if std is None:
            continue
        smiles, ik, ik14, _mw = std
        rows.append({"smiles": smiles, "mol_id": str(r["drug_name"]),
                     "label": float(y), "inchikey": ik, "inchikey14": ik14})
    return pd.DataFrame(rows)
