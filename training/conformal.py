"""Normalized (input-dependent) split-conformal calibration.

The interval half-width is ``Q * scale(x)`` where ``scale(x)`` is a per-molecule difficulty estimate
(the calibrated source disagreement, or a native sigma). Dividing the residual by ``scale(x)`` before
taking the quantile is what makes the width ride on the input (wide where models disagree) while keeping
the finite-sample coverage guarantee - the fix for vanilla conformal's constant width.

Reference: Lei et al., "Distribution-Free Predictive Inference for Regression," JASA 2018 (locally
weighted / normalized nonconformity).
"""

from __future__ import annotations

import numpy as np


def normalized_conformal_quantile(
    residuals: np.ndarray, scales: np.ndarray, alpha: float = 0.1, floor: float = 0.0
) -> float:
    """Fit Q on a calibration split: the ``(1-alpha)`` empirical quantile of ``|residual| / scale``.

    ``residuals = y_true - y_pred`` and ``scales = scale(x)`` on the held-out calibration set. A finite-
    sample correction (``ceil((n+1)(1-alpha))/n``) gives the distribution-free coverage guarantee.
    """
    r = np.abs(np.asarray(residuals, dtype=float))
    s = np.maximum(np.asarray(scales, dtype=float), floor)
    s[s <= 0] = floor if floor > 0 else 1.0            # avoid division by zero for degenerate scales
    nonconf = r / s
    n = len(nonconf)
    if n == 0:
        raise ValueError("empty calibration set")
    level = min(1.0, np.ceil((n + 1) * (1.0 - alpha)) / n)
    return float(np.quantile(nonconf, level, method="higher"))


def empirical_coverage(
    residuals: np.ndarray, scales: np.ndarray, quantile: float, floor: float = 0.0
) -> float:
    """Fraction of held-out points whose true value falls inside ``pred +/- Q*scale`` (should be >= 1-alpha)."""
    r = np.abs(np.asarray(residuals, dtype=float))
    s = np.maximum(np.asarray(scales, dtype=float), floor)
    return float(np.mean(r <= quantile * s))
