"""k-fold scaffold cross-validation for a trained feature: a tighter, CI'd read on the fusion uplift.

The trainer commits ONE 60/20/20 scaffold split, so a small endpoint's metric rides on a ~30-40 molecule
test slice (wide CI). This harness instead runs ``k`` scaffold-disjoint folds and POOLS the out-of-fold
predictions, so every molecule is a test point exactly once and the metric is computed on the whole set.
It reports the pooled point metric (R2 for regression, AUC for classification), the best single source, the
fusion uplift, and a bootstrap 90% CI on that uplift. It is a MEASUREMENT tool only: it reuses the cached
feature matrix (no re-screening), touches no conformal, and writes no spec.

Run: ``python -m training.cv --feature <endpoint>__<feature> --root /zfs/... [--k 5]``.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import expit
from sklearn.metrics import roc_auc_score

from training import fit as fitmod
from training import split as splitmod
from training import datasets as ds
# Importing train_endpoint registers every dataset loader and gives us its data-prep helpers.
from training.train_endpoint import _load_recipe, _subtract_leakage


def _r2(t: np.ndarray, p: np.ndarray) -> float:
    return float(1 - np.sum((t - p) ** 2) / np.sum((t - t.mean()) ** 2))


def _metric(y: np.ndarray, pred_or_col: np.ndarray, is_clf: bool) -> float:
    if is_clf:
        return float(roc_auc_score(y, pred_or_col))
    return _r2(y, pred_or_col)


def cv(feature_key: str, *, root: Path, k: int = 5, boot: int = 5000) -> None:
    r = _load_recipe(feature_key)
    tgt, srcs = r["target"], r["sources"]
    models = [s["model"] for s in srcs]
    is_clf = r["fusion"]["method"] == "logistic"

    data = ds.load(tgt["dataset"], **tgt.get("loader_kwargs", {}))
    data, _ = _subtract_leakage(data, r.get("leakage", {}).get("exclude_models", []),
                                root / "training" / "exclusion_index" / "index.parquet")
    cache = root / "training" / "features" / f"{feature_key}.parquet"
    if not cache.exists():
        raise SystemExit(f"no cached feature matrix at {cache}; run the trainer for this feature first.")
    X = pd.read_parquet(cache)
    data2 = data.drop_duplicates("mol_id").set_index("mol_id")
    df = X.join(data2["label"], how="inner").dropna(subset=models + ["label"])
    y = df["label"].to_numpy(float)
    smiles = [str(data2["smiles"].get(mid, "")) for mid in df.index]
    n = len(df)

    # k scaffold-disjoint folds; refit per fold on the other k-1, predict the held-out fold (out-of-fold).
    folds = splitmod.scaffold_kfold(smiles, k=k, seed=0)
    oof_fused = np.full(n, np.nan)
    oof_cols = np.full((n, len(srcs)), np.nan)
    reg = r["fusion"].get("regularization")
    for te in folds:
        if len(te) == 0:
            continue
        tr = np.setdiff1d(np.arange(n), te)
        cols = []
        for j, s in enumerate(srcs):
            x = df[s["model"]].to_numpy(float)
            p = fitmod.calibrate_source(x[tr], y[tr], s["calibration"])
            gx = fitmod._apply_calibration(x, s["calibration"], p)
            cols.append(gx)
            oof_cols[te, j] = gx[te]
        C = np.column_stack(cols)
        w, b = fitmod.fit_fusion(C[tr], y[tr], method=r["fusion"]["method"],
                                 regularization=0.1 if reg is None else float(reg))
        wv = np.array([w[i] for i in range(len(srcs))])
        oof_fused[te] = (C @ wv + b)[te]

    fused_pred = expit(oof_fused) if is_clf else oof_fused
    fused_m = _metric(y, fused_pred, is_clf)
    singles = [_metric(y, oof_cols[:, j], is_clf) for j in range(len(srcs))]
    bestj = int(np.argmax(singles))
    label = "AUC" if is_clf else "R2"
    print(f"{feature_key}: {k}-fold scaffold CV (pooled out-of-fold, n={n})")
    print(f"  fused {label}={fused_m:.4f}  best single={models[bestj]} {label}={singles[bestj]:.4f}  "
          f"uplift={fused_m - singles[bestj]:+.4f}")
    print(f"  per-source {label}: {{{', '.join(f'{models[j]}: {singles[j]:.3f}' for j in range(len(srcs)))}}}")

    # Bootstrap the pooled out-of-fold pairs for a CI on the uplift.
    rng = np.random.default_rng(0)
    best_col = oof_cols[:, bestj]
    diffs = []
    for _ in range(boot):
        idx = rng.integers(0, n, n)
        yb = y[idx]
        if is_clf and len(np.unique(yb)) < 2:
            continue
        diffs.append(_metric(yb, fused_pred[idx], is_clf) - _metric(yb, best_col[idx], is_clf))
    diffs = np.array(diffs)
    print(f"  bootstrap uplift: mean={diffs.mean():+.4f}  90% CI=[{np.percentile(diffs,5):+.4f}, "
          f"{np.percentile(diffs,95):+.4f}]  P(uplift>0)={(diffs>0).mean():.3f}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m training.cv")
    p.add_argument("--feature", required=True)
    p.add_argument("--root", type=Path, default=None)
    p.add_argument("--k", type=int, default=5)
    a = p.parse_args(argv)
    cv(a.feature, root=a.root or Path(os.environ.get("FTO_ADMET_ROOT", ".")), k=a.k)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
