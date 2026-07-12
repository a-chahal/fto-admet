"""Biogen ADME loader (Fang et al., JCIM 2023) - the clean, non-ChEMBL source for 4 endpoints.

File: ``$FTO_ADMET_ROOT/training/data/biogen_adme_2023/biogen.csv`` (public, molecularinformatics repo).
Each of the 4 usable columns is a LOG value; only the target column's non-null rows are returned. Molecules
are standardized identically to the exclusion index (for leakage subtraction). Solubility (LOG ug/mL) is
converted to log(mol/L) using RDKit MW so it matches ADMET-AI's Solubility_AqSolDB scale (the per-molecule
log(MW) term cannot be absorbed by a constant calibration).
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import pandas as pd

from training.datasets import register
from training.standardize import standardize

# our target key -> (raw Biogen column, conversion). "ugml_to_logmolar" needs MW; others are identity.
_COLUMNS: dict[str, tuple[str, str]] = {
    "solubility": ("LOG SOLUBILITY PH 6.8 (ug/mL)", "ugml_to_logmolar"),
    # Biogen gives LOG(% unbound); the ppb feature is fraction_bound, so convert: fb = 1 - 10^log / 100.
    "ppb": ("LOG PLASMA PROTEIN BINDING (HUMAN) (% unbound)", "log_pctunbound_to_fraction_bound"),
    "hlm_clint": ("LOG HLM_CLint (mL/min/kg)", "identity"),          # already log
    "mdr1_mdck_er": ("LOG MDR1-MDCK ER (B-A/A-B)", "identity"),      # already log
}


def _path() -> Path:
    root = Path(os.environ.get("FTO_ADMET_ROOT", "."))
    return root / "training" / "data" / "biogen_adme_2023" / "biogen.csv"


@register("biogen_adme_2023")
def load(target: str = "solubility") -> pd.DataFrame:
    """Return DataFrame[smiles, mol_id, label, inchikey, inchikey14] for one Biogen ``target``.

    ``target`` selects the column (solubility / ppb / hlm_clint / mdr1_mdck_er). Standardizes each SMILES,
    converts the label if needed, and drops rows with a null label or an unparseable structure.
    """
    if target not in _COLUMNS:
        raise KeyError(f"biogen: unknown target {target!r} (have {list(_COLUMNS)})")
    col, conv = _COLUMNS[target]
    df = pd.read_csv(_path())
    rows = []
    for _, r in df.iterrows():
        y = r.get(col)
        if pd.isna(y):
            continue
        std = standardize(str(r["SMILES"]))
        if std is None:
            continue
        smiles, ik, ik14, mw = std
        label = float(y)
        if conv == "ugml_to_logmolar":
            label = label - 3.0 - math.log10(mw)                 # log(ug/mL) -> log(mol/L)
        elif conv == "log_pctunbound_to_fraction_bound":
            label = 1.0 - (10.0 ** label) / 100.0                # log(% unbound) -> fraction bound (0-1)
        rows.append({"smiles": smiles, "mol_id": str(r["Internal ID"]),
                     "label": label, "inchikey": ik, "inchikey14": ik14})
    return pd.DataFrame(rows)
