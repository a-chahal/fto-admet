"""ChEMBL temporal hERG (Kv11.1 / KCNH2) patch-clamp pIC50 loader - the hERG regression target.

File: ``$FTO_ADMET_ROOT/training/data/chembl_temporal_herg/herg_clean.csv`` (built on the box from a
ChEMBL_37 REST pull of target CHEMBL240; see that dir's PROVENANCE.txt for the exact query + filters).
The clean CSV already carries the relation ("="), validity, and patch-clamp method filters; this loader
adds the TEMPORAL slice, standardization, pIC50 conversion, and per-compound median aggregation.

hERG is the most-contaminated endpoint (BayeshERG's training union alone is ~319k molecules). The only
defensible clean signal is a ChEMBL slice published AFTER the frozen models' ~2020-2021 training
snapshots; the trainer then InChIKey-subtracts the model unions on top. ``min_year`` (default 2021) sets
the temporal cut using ChEMBL ``document_year`` as a publication-date proxy. Counts by cut (unique
standardized compounds): >=2021 -> 395, >=2022 -> 168, >=2023 -> 63. Labels: pIC50 = 9 - log10(IC50_nM),
multiple measurements per compound aggregated to the MEDIAN. Identity transform (recipe herg__hERG_block).
"""

from __future__ import annotations

import math
import os
from collections import defaultdict
from pathlib import Path
from statistics import median

import pandas as pd

from training.datasets import register
from training.standardize import standardize


def _path() -> Path:
    root = Path(os.environ.get("FTO_ADMET_ROOT", "."))
    return root / "training" / "data" / "chembl_temporal_herg" / "herg_clean.csv"


@register("chembl_temporal_herg")
def load(min_year: int = 2021, patch_clamp_only: bool = False) -> pd.DataFrame:
    """Return DataFrame[smiles, mol_id, label, inchikey, inchikey14] for the temporal hERG slice.

    ``min_year`` keeps only measurements from ChEMBL documents dated on/after that year (temporal
    leakage defense; default 2021). ``patch_clamp_only`` restricts to rows whose ChEMBL assay
    description carries an explicit electrophysiology keyword (the ``patch_clamp_explicit`` flag), a
    stricter but smaller slice. Each SMILES is standardized identically to the exclusion index; IC50
    (nM) is converted to pIC50 = 9 - log10(IC50_nM); multiple measurements per standardized compound
    are aggregated to the median pIC50. Rows with an unparseable structure are dropped.
    """
    df = pd.read_csv(_path())

    # accumulate pIC50 per standardized InChIKey, remembering one representative smiles/mol_id
    pics: dict[str, list[float]] = defaultdict(list)
    rep: dict[str, tuple[str, str, str]] = {}   # inchikey -> (smiles, inchikey14, mol_id)
    for _, r in df.iterrows():
        year = r.get("document_year")
        if pd.isna(year) or int(year) < min_year:
            continue
        if patch_clamp_only and not bool(r.get("patch_clamp_explicit", 0)):
            continue
        ic50_nm = r.get("standard_value_nM")
        if pd.isna(ic50_nm) or float(ic50_nm) <= 0:
            continue
        std = standardize(str(r["canonical_smiles"]))
        if std is None:
            continue
        smiles, ik, ik14, _mw = std
        pics[ik].append(9.0 - math.log10(float(ic50_nm)))
        rep.setdefault(ik, (smiles, ik14, str(r["molecule_chembl_id"])))

    rows = []
    for ik, values in pics.items():
        smiles, ik14, mol_id = rep[ik]
        rows.append({"smiles": smiles, "mol_id": mol_id,
                     "label": float(median(values)), "inchikey": ik, "inchikey14": ik14})
    return pd.DataFrame(rows)
