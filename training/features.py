"""Turn a dataset's SMILES into the feature matrix - screening each model ONCE and reusing it everywhere.

Runs on the box. For each contributing model it keeps a raw-output cache keyed by mol_id at
``$FTO_ADMET_ROOT/training/features/_raw/<model>.json``; a molecule already screened for one endpoint is
never re-screened for another (admet_ai, the shared bottleneck, is paid once across all Biogen endpoints
and the whole toxicity panel). Only uncached molecules are dispatched. Then the endpoint's aggregator runs
per molecule to recover each source's HARMONISED value (the exact Source.value inference uses).

Run endpoints SEQUENTIALLY - the raw cache is written per model, so concurrent runs would race on it (and
on the dispatch out-dirs). Sequential + cache = each model screened ~once total, later endpoints near-instant.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from core import dispatch
from core.config import get_config
from core.models import Endpoint, ModelName
from core.run import aggregate_records


def _raw_cache_path(model: str) -> Path:
    return Path(get_config().root) / "training" / "features" / "_raw" / f"{model}.json"


def _ensure_screened(model: str, smiles: list[str], mol_ids: list[str]) -> dict[str, dict]:
    """Screen ``model`` over any UNCACHED molecules; return {mol_id: raw_record_dict}. Reused across endpoints."""
    path = _raw_cache_path(model)
    cache: dict[str, dict] = json.loads(path.read_text()) if path.exists() else {}
    need = [(s, m) for s, m in zip(smiles, mol_ids) if m not in cache]
    if need:
        inputs = [{"smiles": s, "mol_id": m} for s, m in need]
        recs = dispatch.run_model_batch(ModelName(model), inputs, f"outputs/training/_raw/{model}")
        for (s, m), rec in zip(need, recs):
            cache[m] = rec.model_dump(mode="json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache))
    return cache


def screen_smiles(
    smiles: list[str], mol_ids: list[str], *, endpoint: str, feature: str, models: list[str],
) -> pd.DataFrame:
    """DataFrame indexed by mol_id, one column per model: its harmonised Source ``value`` for ``feature``."""
    ep = Endpoint(endpoint)
    caches = {m: _ensure_screened(m, smiles, mol_ids) for m in models}
    rows: list[dict] = []
    for mid in mol_ids:
        recs = [caches[m][mid] for m in models if mid in caches[m]]
        verdict, _ = aggregate_records(ep, recs, mol_id=mid)
        cell: dict = {"mol_id": mid}
        f = next((x for x in (getattr(verdict, "features", []) or []) if x.feature == feature), None)
        if f is not None:
            for s in f.sources:
                cell[s.model] = s.value
        rows.append(cell)
    return pd.DataFrame(rows).set_index("mol_id")


def load_or_build_features(
    dataset: pd.DataFrame, *, endpoint: str, feature: str, models: list[str], cache: Path
) -> pd.DataFrame:
    """Cached feature matrix, else screen (reusing the per-model raw cache) and store it."""
    if cache.exists():
        return pd.read_parquet(cache)
    X = screen_smiles(
        dataset["smiles"].tolist(), dataset["mol_id"].astype(str).tolist(),
        endpoint=endpoint, feature=feature, models=models,
    )
    cache.parent.mkdir(parents=True, exist_ok=True)
    X.to_parquet(cache)
    return X
