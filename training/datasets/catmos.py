"""EPA/NICEATM CATMoS rat acute oral toxicity (LD50) loader - the acute_ld50 regression target.

File: ``$FTO_ADMET_ROOT/training/data/catmos/catmos_ld50.csv`` (built on the box from Additional file 2 of
Mansouri et al., J Cheminform 2019, 11:58, "SAR and QSAR modeling of a large collection of LD50 rat acute
oral toxicity data"; see that dir's PROVENANCE.txt for the exact source + curation). The CSV carries the
QSAR-ready SMILES, the CASRN, the CATMoS ID, and the experimental ``logLD50_mmol_kg`` = log10(LD50 in
mmol/kg body weight). This loader standardizes each SMILES and converts the label to the ADMET-AI / TDC
LD50 scale: neg_log_mol_per_kg = -log10(LD50 in mol/kg) = 3 - log10(LD50 in mmol/kg), where HIGHER means
MORE toxic (smaller LD50). Verified against anchors: strychnine -> 5.0 (very toxic), ethanol -> 0.80
(non-toxic). Recipe target acute_ld50 (transform identity, units neg_log_mol_per_kg).

Only rows with a parseable structure and a non-null experimental LD50 are returned; multiple entries that
standardize to the same InChIKey are aggregated to the median neg-log LD50.
"""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path
from statistics import median

import pandas as pd

from training.datasets import register
from training.standardize import standardize


def _path() -> Path:
    root = Path(os.environ.get("FTO_ADMET_ROOT", "."))
    return root / "training" / "data" / "catmos" / "catmos_ld50.csv"


@register("catmos")
def load() -> pd.DataFrame:
    """Return DataFrame[smiles, mol_id, label, inchikey, inchikey14] for CATMoS rat oral LD50.

    ``label`` is neg_log_mol_per_kg = 3 - log10(LD50 in mmol/kg) (higher = more toxic). Each SMILES is
    standardized identically to the exclusion index; rows with an unparseable structure or a null LD50 are
    dropped; multiple measurements per standardized compound are aggregated to the median.
    """
    df = pd.read_csv(_path())

    vals: dict[str, list[float]] = defaultdict(list)
    rep: dict[str, tuple[str, str, str]] = {}   # inchikey -> (smiles, inchikey14, mol_id)
    for _, r in df.iterrows():
        y = r.get("logLD50_mmol_kg")
        if pd.isna(y):
            continue
        std = standardize(str(r["SMILES"]))
        if std is None:
            continue
        smiles, ik, ik14, _mw = std
        vals[ik].append(3.0 - float(y))                 # log10(mmol/kg) -> -log10(mol/kg)
        rep.setdefault(ik, (smiles, ik14, str(r.get("ID", r.get("CASRN", "")))))

    rows = []
    for ik, ys in vals.items():
        smiles, ik14, mol_id = rep[ik]
        rows.append({"smiles": smiles, "mol_id": mol_id,
                     "label": float(median(ys)), "inchikey": ik, "inchikey14": ik14})
    return pd.DataFrame(rows)
