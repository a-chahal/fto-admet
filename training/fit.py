"""Fit per-source calibration + fusion weights for one feature.

Two stages, matching the FusionSpec (score = Sum wi * gi(xi) + intercept):

1. per-source calibration gi: identity for continuous same-scale sources (the fusion weight absorbs the
   linear correction, so a separate slope is non-identifiable); logistic (Platt-style) when a probability
   source must be mapped monotonically onto a continuous target.
2. fusion weights: NNLS (non-negative, interpretable convex combination) or Ridge for a continuous target;
   LogisticRegression for a binary target. Regularization handles the correlated-source multicollinearity.

Small-data guidance (CLAUDE.md / our design): keep calibration LINEAR below a few hundred points; the few
parameters (one weight per source + intercept) need only ~10-20 points each; conformal wants ~100 for the
calibration split.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import nnls
from sklearn.linear_model import LogisticRegression, Ridge


def calibrate_source(x: np.ndarray, y: np.ndarray, kind: str) -> list[float]:
    """Fit a source's calibration params. identity -> []; linear -> [a, b]; logistic -> [a, b] (Platt)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if kind == "identity":
        return []
    if kind == "linear":
        a, b = np.polyfit(x, y, 1)
        return [float(a), float(b)]
    if kind == "logistic":
        # Platt-style: fit sigmoid(a*x + b) to y in [0,1] via logistic regression on the single feature.
        lr = LogisticRegression(C=1e6).fit(x.reshape(-1, 1), (y >= 0.5).astype(int))
        return [float(lr.coef_[0][0]), float(lr.intercept_[0])]
    raise ValueError(f"unknown calibration kind: {kind}")


def _apply_calibration(x: np.ndarray, kind: str, params: list[float]) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    if kind == "identity":
        return x
    a, b = (list(params) + [1.0, 0.0])[:2]
    if kind == "linear":
        return a * x + b
    if kind == "logistic":
        return 1.0 / (1.0 + np.exp(-(a * x + b)))
    raise ValueError(kind)


def fit_fusion(
    calibrated: np.ndarray, y: np.ndarray, method: str = "nnls", regularization: float = 0.1
) -> tuple[dict[int, float], float]:
    """Fit weights + intercept over the calibrated source matrix ``calibrated`` (n x k) -> (weights, b).

    ``nnls``: non-negative least squares (interpretable, no sign flips). ``ridge``: L2 (allows negatives).
    ``logistic``: for a binary target. Returns ``({col_index: weight}, intercept)``.
    """
    C = np.asarray(calibrated, dtype=float)
    y = np.asarray(y, dtype=float)
    n, k = C.shape
    A = np.hstack([C, np.ones((n, 1))])                # append intercept column
    if method == "nnls":
        coef, _ = nnls(A, y)                           # non-negative on weights AND intercept
        weights = {i: float(coef[i]) for i in range(k)}
        return weights, float(coef[k])
    if method in ("ridge", "linear"):   # "linear" = OLS/ridge; used for single-source features
        r = Ridge(alpha=regularization, fit_intercept=True).fit(C, y)
        return {i: float(r.coef_[i]) for i in range(k)}, float(r.intercept_)
    if method == "logistic":
        lr = LogisticRegression(C=1.0 / max(regularization, 1e-6)).fit(C, (y >= 0.5).astype(int))
        return {i: float(lr.coef_[0][i]) for i in range(k)}, float(lr.intercept_[0])
    raise ValueError(f"unknown fusion method: {method}")
