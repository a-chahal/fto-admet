"""Turn a dataset's SMILES into the feature matrix - screening each model ONCE and reusing it everywhere.

Runs on the box. Per contributing model it keeps a raw-output cache keyed by mol_id at
``$FTO_ADMET_ROOT/training/features/_raw/<model>.json``; a molecule already screened for one endpoint is
never re-screened for another (admet_ai, the shared bottleneck, is paid once across all Biogen endpoints
and the whole toxicity panel). Only uncached molecules are dispatched.

Screening is FAULT-TOLERANT: some adapters (opera in particular) exit non-zero on a single bad molecule,
which would sink an all-or-nothing batch. So a failing batch is binary-split until the offending molecule
is isolated (marked ``_failed`` and skipped), and the cache is checkpointed after each chunk so a long
opera/ochem screen survives an interruption. Then the endpoint's aggregator runs per molecule to recover
each source's HARMONISED value.

Run endpoints SEQUENTIALLY - the raw cache is written per model, so concurrent runs would race on it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from core import dispatch
from core.config import get_config
from core.dispatch import DispatchError
from core.models import Endpoint, ModelName

from core.run import aggregate_records

_CHUNK = 200


def _raw_cache_path(model: str) -> Path:
    return Path(get_config().root) / "training" / "features" / "_raw" / f"{model}.json"


def _screen_chunk(model: str, chunk: list[tuple[str, str]], cache: dict[str, dict]) -> None:
    """Screen ``chunk`` (list of (smiles, mol_id)); on failure binary-split to isolate the bad molecule.

    A bad molecule is isolated in O(log n) extra batch runs, marked ``{"_failed": True}`` so it is skipped
    and never re-screened. Everything else in the chunk still gets cached.
    """
    inputs = [{"smiles": s, "mol_id": m} for s, m in chunk]
    try:
        recs = dispatch.run_model_batch(ModelName(model), inputs, f"outputs/training/_raw/{model}")
        for (s, m), rec in zip(chunk, recs):
            cache[m] = rec.model_dump(mode="json")
    except DispatchError:
        if len(chunk) == 1:
            cache[chunk[0][1]] = {"_failed": True}
            return
        mid = len(chunk) // 2
        _screen_chunk(model, chunk[:mid], cache)
        _screen_chunk(model, chunk[mid:], cache)


def _ensure_screened(model: str, smiles: list[str], mol_ids: list[str]) -> dict[str, dict]:
    """Screen ``model`` over UNCACHED molecules (chunked, fault-tolerant, checkpointed). Returns {mol_id: rec}."""
    path = _raw_cache_path(model)
    cache: dict[str, dict] = json.loads(path.read_text()) if path.exists() else {}
    need = [(s, m) for s, m in zip(smiles, mol_ids) if m not in cache]
    if not need:
        return cache
    path.parent.mkdir(parents=True, exist_ok=True)
    for i in range(0, len(need), _CHUNK):
        _screen_chunk(model, need[i:i + _CHUNK], cache)
        path.write_text(json.dumps(cache))          # checkpoint so a long screen survives interruption
    return cache


def screen_smiles(
    smiles: list[str], mol_ids: list[str], *, endpoint: str, feature: str, models: list[str],
) -> pd.DataFrame:
    """DataFrame indexed by mol_id, one column per model: its harmonised Source ``value`` for ``feature``."""
    ep = Endpoint(endpoint)
    caches = {m: _ensure_screened(m, smiles, mol_ids) for m in models}
    rows: list[dict] = []
    for mid in mol_ids:
        recs = [caches[m][mid] for m in models
                if mid in caches[m] and not caches[m][mid].get("_failed")]
        verdict, _ = aggregate_records(ep, recs, mol_id=mid)
        cell: dict = {"mol_id": mid}
        f = next((x for x in (getattr(verdict, "features", []) or []) if x.feature == feature), None)
        if f is not None:
            for s in f.sources:
                # Use the harmonised value; fall back to the source's native ``raw`` when the aggregator
                # left it OFF the common scale (value=None) - e.g. CardioGenAI's pIC50 on the P(block)
                # feature, or the bbb mixed-scale reads. Per-source calibration reconciles the scale, so a
                # natively-predicted value is not discarded just because it is on a different scale.
                cell[s.model] = s.value if s.value is not None else s.raw
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
