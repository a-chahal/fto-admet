"""Turn a clean dataset's SMILES into the feature matrix by screening the FROZEN models on the box.

This is the bridge between the trainer (local) and the pipeline (box): it batch-screens the dataset's
SMILES through ``core.screen`` on Rosenbluth, then pulls, per molecule, each contributing model's
harmonized source value for the target feature. Those columns are the training features X; the dataset's
experimental label is y.

Cached to ``$FTO_ADMET_ROOT/training/features/<feature>.parquet`` so a re-fit does not re-screen.

INTEGRATION POINT: the box-screen call is intentionally a thin wrapper - it reuses the exact screening
path a normal run uses, so the training features are identical to inference features. Fill
``screen_smiles`` against the real box invocation when we wire the first endpoint.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def screen_smiles(smiles: list[str], mol_ids: list[str], *, endpoint: str, feature: str) -> pd.DataFrame:
    """Batch-screen SMILES on the box and return per-molecule source values for ``endpoint/feature``.

    Returns a DataFrame indexed by mol_id with one column per contributing model (its harmonized Source
    ``value`` for this feature). Implemented by driving ``core.screen`` over the .smi on Rosenbluth and
    reading each molecule's ``endpoints[endpoint].verdict.features[feature].sources``.

    TODO(wire): call the box screen (ssh rosenbluth 'pixi run python -m core.screen --input <smi> ...'),
    parse the cards, and pivot sources -> columns. Left as the single integration point so the fit/conformal
    path can be validated on a cached matrix first.
    """
    raise NotImplementedError(
        "screen_smiles: wire to the box core.screen for the first endpoint (see docstring)."
    )


def load_or_build_features(
    dataset: pd.DataFrame, *, endpoint: str, feature: str, cache: Path
) -> pd.DataFrame:
    """Return the cached feature matrix if present, else screen the dataset's SMILES and cache it."""
    if cache.exists():
        return pd.read_parquet(cache)
    X = screen_smiles(
        dataset["smiles"].tolist(), dataset["mol_id"].astype(str).tolist(),
        endpoint=endpoint, feature=feature,
    )
    cache.parent.mkdir(parents=True, exist_ok=True)
    X.to_parquet(cache)
    return X
