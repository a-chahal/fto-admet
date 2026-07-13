"""NICEATM / ICE LLNA skin sensitization loader - the skin_reaction binary target.

File: ``$FTO_ADMET_ROOT/training/data/niceatm_llna/llna_ice.txt``, the NICEATM/ICE curated LLNA reference
export "OECD Defined Approach to Skin Sensitization LLNA (R)" (dated 2024-06-13), obtained from the NIEHS
DASS App repository (github.com/NIEHS/DASS, www/ice_references/). Columns include CASRN, Curated.name,
DTXSID, Original SMILES, QSAR Ready SMILES, "LLNA Binary hazard reference classification"
(1 = sensitizer, 0 = non-sensitizer), and the potency subcategorization.

IMPORTANT SIZE CAVEAT (see PROVENANCE.txt): this is the small OECD Guideline 497 defined-approach reference
set (156 chemicals: 123 sensitizers / 33 non-sensitizers), which is a curated SUBSET that overlaps the TDC
Alves-2015 skin_reaction set. It is NOT the full ~1000-chemical NICEATM LLNA superset the recipe's leakage
note assumes; that larger export is only available through the interactive ICE portal
(ice.ntp.niehs.nih.gov, JS query/export), which has no stable bulk-download URL. After Alves-2015 leakage
subtraction the surviving count may fall below the trainer's floor; the trainer will refuse rather than
train on too little, which is the correct behavior.

Recipe target skin_reaction (dataset ``niceatm_llna``, label ``sensitizer``, logit transform, logistic
calibration).
"""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path

import pandas as pd

from training.datasets import register
from training.standardize import standardize

_LABEL = "LLNA Binary hazard reference classification"


def _path() -> Path:
    root = Path(os.environ.get("FTO_ADMET_ROOT", "."))
    return root / "training" / "data" / "niceatm_llna" / "llna_ice.txt"


@register("niceatm_llna")
def load() -> pd.DataFrame:
    """Return DataFrame[smiles, mol_id, label, inchikey, inchikey14] for NICEATM/ICE LLNA sensitization.

    ``label`` is the binary LLNA hazard call (1 = sensitizer, 0 = non-sensitizer). The ``Original SMILES``
    is standardized identically to the exclusion index (falling back to ``QSAR Ready SMILES`` when the
    original is missing); rows with an unparseable structure or a missing label are dropped; duplicate
    InChIKeys take the positive-dominant (max) label.
    """
    df = pd.read_csv(_path(), sep="\t", encoding="latin-1")
    df.columns = [c.strip() for c in df.columns]

    labels: dict[str, int] = defaultdict(int)
    rep: dict[str, tuple[str, str, str]] = {}   # inchikey -> (smiles, inchikey14, mol_id)
    for _, r in df.iterrows():
        y = r.get(_LABEL)
        if pd.isna(y) or int(y) not in (0, 1):
            continue
        src = r.get("Original SMILES")
        if not isinstance(src, str) or not src.strip():
            src = r.get("QSAR Ready SMILES")
        if not isinstance(src, str) or not src.strip():
            continue
        std = standardize(src)
        if std is None:
            continue
        smiles, ik, ik14, _mw = std
        labels[ik] = max(labels[ik], int(y))
        rep.setdefault(ik, (smiles, ik14, str(r.get("CASRN", ""))))

    rows = []
    for ik, y in labels.items():
        smiles, ik14, mol_id = rep[ik]
        rows.append({"smiles": smiles, "mol_id": mol_id,
                     "label": int(y), "inchikey": ik, "inchikey14": ik14})
    return pd.DataFrame(rows)
