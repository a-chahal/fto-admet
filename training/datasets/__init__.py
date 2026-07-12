"""Clean-dataset loaders: name -> a standardized (smiles, mol_id, label, inchikey) DataFrame.

Each loader (a) reads a clean source from ``$FTO_ADMET_ROOT/training/data/<source>/``, (b) standardizes
every molecule identically (RDKit: largest-fragment, uncharge, canonical tautomer), and (c) computes the
full InChIKey used for leakage subtraction against the exclusion index. Registered by the ``dataset`` name
used in the recipes (biogen_adme_2023, kpuu_brain_compilation, chembl_temporal_logD, dilirank, catmos, ...).

INTEGRATION POINT: the concrete file parsing depends on each source's real layout, filled as we download
them. The registry + the standardize/InChIKey contract are fixed here so the trainer is source-agnostic.
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

# name -> loader. Loaders are registered as their source files land under /zfs training/data/.
REGISTRY: dict[str, Callable[..., pd.DataFrame]] = {}


def register(name: str) -> Callable[[Callable[..., pd.DataFrame]], Callable[..., pd.DataFrame]]:
    def deco(fn: Callable[..., pd.DataFrame]) -> Callable[..., pd.DataFrame]:
        REGISTRY[name] = fn
        return fn
    return deco


def load(name: str, **kw) -> pd.DataFrame:
    """Load a registered clean dataset -> DataFrame[smiles, mol_id, label, inchikey]."""
    if name not in REGISTRY:
        raise KeyError(f"no loader registered for dataset {name!r}; add one under training/datasets/")
    return REGISTRY[name](**kw)
