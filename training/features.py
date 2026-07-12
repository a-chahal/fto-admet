"""Turn a clean dataset's SMILES into the feature matrix by dispatching the FROZEN models and aggregating.

Runs on the box (where the model envs live). For a feature it dispatches only that feature's contributing
models over the batch (one subprocess per model, weights loaded once), then runs the endpoint's aggregator
per molecule to recover each source's HARMONISED value (the exact Source.value inference uses - e.g. ppb's
1-FuB, lipophilicity's logP->logD). Those columns are the training features X. Cached to
``$FTO_ADMET_ROOT/training/features/<feature>.parquet`` so a re-fit does not re-dispatch.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from core import dispatch
from core.models import Endpoint, ModelName
from core.run import aggregate_records


def screen_smiles(
    smiles: list[str], mol_ids: list[str], *, endpoint: str, feature: str, models: list[str],
) -> pd.DataFrame:
    """Dispatch ``models`` over the batch and return DataFrame indexed by mol_id, one column per model.

    Each cell is that model's harmonised Source ``value`` for ``feature`` (via the endpoint aggregator), or
    NaN if the model did not contribute for that molecule.
    """
    inputs = [{"smiles": s, "mol_id": m} for s, m in zip(smiles, mol_ids)]
    ep = Endpoint(endpoint)
    out_dir = "outputs/training"

    per_model: dict[str, list] = {}
    for name in models:
        recs = dispatch.run_model_batch(ModelName(name), inputs, out_dir)
        per_model[name] = recs  # aligned positionally to inputs

    rows: list[dict] = []
    for i, mid in enumerate(mol_ids):
        recs = [per_model[m][i] for m in models if i < len(per_model.get(m, []))]
        verdict, _ = aggregate_records(ep, recs, mol_id=mid)
        cell: dict = {"mol_id": mid}
        feats = getattr(verdict, "features", []) or []
        f = next((x for x in feats if x.feature == feature), None)
        if f is not None:
            for s in f.sources:
                cell[s.model] = s.value
        rows.append(cell)
    return pd.DataFrame(rows).set_index("mol_id")


def load_or_build_features(
    dataset: pd.DataFrame, *, endpoint: str, feature: str, models: list[str], cache: Path
) -> pd.DataFrame:
    """Cached feature matrix, else dispatch the models over the dataset's SMILES and cache it."""
    if cache.exists():
        return pd.read_parquet(cache)
    X = screen_smiles(
        dataset["smiles"].tolist(), dataset["mol_id"].astype(str).tolist(),
        endpoint=endpoint, feature=feature, models=models,
    )
    cache.parent.mkdir(parents=True, exist_ok=True)
    X.to_parquet(cache)
    return X
