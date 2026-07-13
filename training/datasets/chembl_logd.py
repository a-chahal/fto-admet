"""ChEMBL logD distribution-coefficient loader - the experimental lipophilicity source for logD fusion.

File: ``$FTO_ADMET_ROOT/training/data/chembl_temporal_logD/chembl_logd_raw.csv`` (gitignored, fetched from
the ChEMBL REST API on the box; see PROVENANCE.txt in the same folder).

The raw file is one ChEMBL activity per row (a single logD measurement) for ``standard_type`` in
{LogD, LogD7.4}, ``assay_type`` in {P (physicochemical), A (ADMET)} - i.e. genuine octanol/buffer
distribution coefficients, NOT bioactivity. Each row already carries the assay pH we parsed from the
ChEMBL assay description / units (see the fetch step): a float ``ph`` when stated and a coarse ``ph_bucket``
in {6.5, 7.0, 7.4, unspecified}. Records at a clearly non-physiological pH (outside 6.5/7.0/7.4) were
dropped at fetch time; ``unspecified`` = a distribution coefficient with no pH stated in the assay text.

NOTE on the recipe's ``assay_type=B``: real ChEMBL logD records are Physicochemical (``P``), with a small
ADMET (``A``) tail - never Binding (``B``). The recipe's ``B`` was a mis-guess; this loader filters on the
verified P/A physchem slice (done at fetch time). Nothing here is a bioactivity assay.

Standardization is identical to the exclusion index (salt-strip / neutralize / canonical tautomer ->
InChIKey), so InChIKeys line up for the trainer's leakage subtraction. logD is already log space
(transform = identity); no unit conversion is applied.

Aggregation: multiple measurements of the same standardized compound are collapsed to a single **median**
logD, keyed by (full InChIKey, pH bucket). Aggregation never crosses pH buckets - a compound measured at
both pH 7.0 and pH 7.4 yields two independent rows if both buckets are loaded. ``load()`` selects one pH
bucket at a time (default 7.4), so within a single call the aggregation key reduces to the InChIKey.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from training.datasets import register
from training.standardize import standardize

_BUCKETS = {"6.5", "7.0", "7.4", "unspecified"}


def _path() -> Path:
    root = Path(os.environ.get("FTO_ADMET_ROOT", "."))
    return root / "training" / "data" / "chembl_temporal_logD" / "chembl_logd_raw.csv"


def _bucket_key(ph: float | str) -> str:
    """Normalize a caller's ``ph`` to a raw-file ``ph_bucket`` string."""
    if isinstance(ph, str):
        s = ph.strip().lower()
        if s in _BUCKETS:
            return s
        ph = float(s)
    for b in (6.5, 7.0, 7.4):
        if abs(float(ph) - b) < 1e-6:
            return f"{b:.1f}"
    raise ValueError(f"chembl_logd: ph must be one of 6.5/7.0/7.4/'unspecified', got {ph!r}")


@register("chembl_temporal_logD")
def load(ph: float | str = 7.4, include_unspecified: bool = False) -> pd.DataFrame:
    """Return DataFrame[smiles, mol_id, label, inchikey, inchikey14] of experimental logD at one pH.

    ``ph`` selects the pH bucket (6.5, 7.0, 7.4, or "unspecified"); default 7.4. Set
    ``include_unspecified=True`` to fold the no-pH-stated distribution coefficients into the selected
    bucket (useful when the chosen pH slice is thin and the unspecified records are conventionally at
    physiological pH). ``label`` is the per-compound median logD; ``mol_id`` is the lexicographically
    smallest contributing ChEMBL id. Rows with an unparseable structure are dropped.
    """
    want = _bucket_key(ph)
    df = pd.read_csv(_path(), dtype={"ph_bucket": str, "molecule_chembl_id": str})
    keep = {want}
    if include_unspecified:
        keep.add("unspecified")
    df = df[df["ph_bucket"].isin(keep)]

    recs = []
    for _, r in df.iterrows():
        std = standardize(str(r["canonical_smiles"]))
        if std is None:
            continue
        smiles, ik, ik14, _mw = std
        recs.append({"smiles": smiles, "inchikey": ik, "inchikey14": ik14,
                     "mol_id": str(r["molecule_chembl_id"]), "label": float(r["logd"])})
    if not recs:
        return pd.DataFrame(columns=["smiles", "mol_id", "label", "inchikey", "inchikey14"])

    std_df = pd.DataFrame(recs)
    # median logD per standardized compound (within the single pH bucket loaded here).
    agg = (std_df.groupby("inchikey", as_index=False)
                 .agg(smiles=("smiles", "first"),
                      inchikey14=("inchikey14", "first"),
                      mol_id=("mol_id", "min"),
                      label=("label", "median")))
    return agg[["smiles", "mol_id", "label", "inchikey", "inchikey14"]].reset_index(drop=True)
