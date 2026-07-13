"""Apply a trained FusionSpec at inference - pure arithmetic, no sklearn (CLAUDE.md dependency discipline).

``fuse(endpoint, feature, sources)`` is the drop-in replacement for ``core.aggregate.ensemble`` inside an
aggregator. It loads the feature's committed spec (``core/fusion/specs/<endpoint>__<feature>.json``) and:

- **no spec yet** -> falls back to exactly the current behaviour (``ensemble`` = equal-weight mean + std),
  so aggregators migrate to training one feature at a time and nothing breaks in the meantime;
- **spec present** -> calibrates each source (``gᵢ``), computes ``score = Σ wᵢ·gᵢ(valueᵢ) + intercept``,
  and returns the normalized-conformal half-width ``Q·scale(x)`` as the uncertainty. A mixed-scale feature
  (whose sources are on incompatible raw scales) gets a real score for the first time here, because the
  per-source calibration is exactly what makes those sources commensurable.

Returns ``(score, uncertainty)`` - the same shape ``ensemble`` returns - so the ``Feature`` shape is
unchanged until we choose to surface explicit interval bounds.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from core.aggregate import Source, ensemble
from core.fusion.spec import FusionSpec, SourceCalibration, UncertaintySpec

_SPECS_DIR = Path(__file__).parent / "specs"


def spec_path(endpoint: str, feature: str) -> Path:
    """Path of the committed spec for ``(endpoint, feature)`` (may not exist)."""
    return _SPECS_DIR / f"{endpoint}__{feature}.json"


def load_spec(endpoint: str, feature: str) -> FusionSpec | None:
    """Load the committed FusionSpec, or ``None`` when the feature has not been trained yet."""
    path = spec_path(str(endpoint), feature)
    if not path.exists():
        return None
    return FusionSpec.model_validate_json(path.read_text(encoding="utf-8"))


def _num(value: Any) -> float | None:
    """A finite float, or ``None`` (bools are flags, not measurements, and are rejected)."""
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _calibrate(cal: SourceCalibration, value: Any) -> float | None:
    """Map one source's harmonized value onto the target scale via its calibration ``gᵢ``.

    A boolean is coerced to a 0/1 indicator here (unlike the equal-weight ensemble, which rejects bools):
    a trained calibration of a binary flag - e.g. BOILED-Egg's in-yolk BBB call - is a meaningful 0/1
    feature, and the trainer already fits it as 0/1, so inference must read it the same way.
    """
    if isinstance(value, bool):
        value = float(value)
    x = _num(value)
    if x is None:
        return None
    if cal.kind == "identity":
        return x
    a, b = (list(cal.params) + [1.0, 0.0])[:2]
    if cal.kind == "linear":
        return a * x + b
    if cal.kind == "logistic":
        return 1.0 / (1.0 + math.exp(-(a * x + b)))
    return x  # pragma: no cover - schema-guarded


def _population_std(values: Sequence[float]) -> float:
    """Population std over the calibrated source values (the disagreement scale). 0 for < 2 values."""
    xs = [v for v in values if isinstance(v, (int, float))]
    if len(xs) < 2:
        return 0.0
    mean = sum(xs) / len(xs)
    return math.sqrt(sum((x - mean) ** 2 for x in xs) / len(xs))


def _conformal_halfwidth(u: UncertaintySpec, calibrated: Sequence[float]) -> float | None:
    """The normalized-conformal interval half-width ``Q * scale(x)`` (``None`` if uncertainty is off)."""
    if u.method == "none" or u.quantile is None:
        return None
    if u.scale == "constant":
        base = u.constant_width or 0.0
    elif u.scale == "disagreement_std":
        base = _population_std(calibrated)
    else:  # "native_sigma" is supplied per-source upstream; not available from values alone here
        base = 0.0
    return u.quantile * max(base, u.scale_floor)


def apply_spec(spec: FusionSpec, sources: Sequence[Source]) -> tuple[float | None, float | None]:
    """Apply a loaded spec to a molecule's sources: ``(score, uncertainty)``. Pure; unit-testable.

    Each spec source is calibrated from the matching model's harmonized ``value``; a spec source with no
    matching present value uses its ``impute_value`` (training mean) so the linear sum is not biased, or
    is dropped when no impute is given. ``score`` is ``Σ wᵢ·gᵢ + intercept``; ``uncertainty`` is the
    normalized-conformal half-width over the calibrated values.
    """
    present: dict[str, float] = {}
    for s in sources:
        cal = next((c for c in spec.sources if c.model == s.model), None)
        if cal is None:
            continue
        # Calibrate the source's native ``raw`` when the spec fit it from raw (from_raw: a source the
        # aggregator leaves off the common scale, e.g. CardioGenAI's pIC50), else its harmonized ``value``.
        # A ``value`` source that is absent (None) calibrates to None below and is dropped/imputed - so a
        # source that merely failed to harmonize (e.g. logD's crippen with no pKa) is NOT read from raw.
        cv = _calibrate(cal, s.raw if cal.from_raw else s.value)
        if cv is not None:
            present[s.model] = cv

    if not present:
        return None, None

    total = spec.fusion.intercept
    calibrated: list[float] = []
    for cal in spec.sources:
        weight = spec.fusion.weights.get(cal.model, 0.0)
        if cal.model in present:
            cv = present[cal.model]
        elif cal.impute_value is not None:
            cv = cal.impute_value
        else:
            continue  # source absent and no impute: drop its term (documented degraded fallback)
        total += weight * cv
        calibrated.append(cv)

    if spec.fusion.link == "logistic":               # classification: the weighted sum is a logit
        total = 1.0 / (1.0 + math.exp(-total))       # -> squash to a probability in [0,1]
    return total, _conformal_halfwidth(spec.uncertainty, calibrated)


def fuse(endpoint: str, feature: str, sources: Sequence[Source]) -> tuple[float | None, float | None]:
    """Score a feature: apply its trained spec if present, else fall back to the equal-weight ensemble.

    Drop-in for ``ensemble([s.value ...], [s.weight ...])`` inside an aggregator. Until a
    ``core/fusion/specs/<endpoint>__<feature>.json`` exists, behaviour is identical to today
    (equal-weight mean + disagreement std); once it does, the trained calibration + weights + conformal
    interval take over with no aggregator code change.
    """
    spec = load_spec(str(endpoint), feature)
    if spec is None:
        return ensemble([s.value for s in sources], [s.weight for s in sources])
    return apply_spec(spec, list(sources))
