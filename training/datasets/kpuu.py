"""Kp,uu,brain compilation loader - the clean experimental target for the distribution/bbb_penetration feature.

File: ``$FTO_ADMET_ROOT/training/data/kpuu_brain_compilation/kpuu_compilation.csv`` (built on the box; see
that dir's PROVENANCE.txt). The compilation is the 157-compound, de-duplicated Kp,uu,brain table from the
supplementary material of Ryu et al. 2024 (Front. Drug Discov. 4:1360732, CC-BY 4.0), which itself fuses 41
primary microdialysis / brain-slice / homogenate sources (Friden 2009, Summerfield 2016, Kodaira 2011, ...).
The authors publish canonical SMILES per compound; one upstream SMILES error (mesoridazine listed with
methotrexate's structure) is corrected during the build from ChEMBL. See PROVENANCE.txt.

The DECIDED target is Kp,uu (NOT logBB, NOT a binary BBB flag). Kp,uu spans orders of magnitude, so the
label is returned in log10 space (recipe distribution__bbb_penetration transform: log). This mirrors the
biogen loader convention: the loader delivers the label already in its final modeling scale, since the
trainer consumes ``data["label"]`` directly and does not re-apply the recipe transform.

Every SMILES is standardized identically to the exclusion index (for InChIKey leakage subtraction). Optional
filters expose the technique / species / refined-subset columns so the trainer can restrict the set (e.g. to
rat microdialysis only) without touching this file; the defaults return all 157 compounds.
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
    return root / "training" / "data" / "kpuu_brain_compilation" / "kpuu_compilation.csv"


@register("kpuu_brain_compilation")
def load(
    refined_only: bool = False,
    animal: str | None = None,
    exclude_homogenate: bool = False,
) -> pd.DataFrame:
    """Return DataFrame[smiles, mol_id, label, inchikey, inchikey14] for the Kp,uu,brain compilation.

    ``label`` = log10(Kp,uu). ``mol_id`` is the compound name. Each SMILES is standardized identically to
    the exclusion index; if two rows collapse to the same InChIKey the Kp,uu values are aggregated to the
    median before taking log10. Rows with an unparseable structure or a non-positive Kp,uu are dropped.

    Filters (all default to keeping everything):
      ``refined_only``      keep only the authors' refined subset (homogenate + known P-gp/BCRP substrates
                            already excluded upstream; ``in_refined == YES``).
      ``animal``            keep only rows whose species set contains this value (e.g. ``"Rat"``).
      ``exclude_homogenate`` drop compounds whose only technique is brain homogenate (less direct Kp,uu).
    """
    df = pd.read_csv(_path())

    # accumulate Kp,uu per standardized InChIKey, remembering one representative smiles/name/ik14
    kpuus: dict[str, list[float]] = defaultdict(list)
    rep: dict[str, tuple[str, str, str]] = {}   # inchikey -> (smiles, inchikey14, name)
    for _, r in df.iterrows():
        if refined_only and str(r.get("in_refined", "")).strip().upper() != "YES":
            continue
        if animal is not None and animal not in str(r.get("animals", "")).split(";"):
            continue
        if exclude_homogenate and str(r.get("techniques", "")).strip() == "Homog":
            continue
        kp = r.get("kpuu")
        if pd.isna(kp) or float(kp) <= 0:
            continue
        std = standardize(str(r["smiles"]))
        if std is None:
            continue
        smiles, ik, ik14, _mw = std
        kpuus[ik].append(float(kp))
        rep.setdefault(ik, (smiles, ik14, str(r["name"])))

    rows = []
    for ik, values in kpuus.items():
        smiles, ik14, name = rep[ik]
        rows.append({"smiles": smiles, "mol_id": name,
                     "label": float(math.log10(median(values))),
                     "inchikey": ik, "inchikey14": ik14})
    return pd.DataFrame(rows)
