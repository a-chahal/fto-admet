"""pgp - the DERIVED P-gp efflux flag (no env, no run.py, no subprocess).

P-gp is sourced *via the generalists* (SETTLED skeleton, IO_SPEC §1 #16): there is no separate P-gp
service to install. So ``pgp`` is a **virtual / DERIVED model** - it has no ``pixi.toml``, no
``pixi.lock`` and no independently executed ``run.py``. Its value is the ``Pgp_Broccatelli`` head that
ADMET-AI (t21) already emits into ``endpoint_values``.
It exists as a registry entry so provenance is explicit and the distribution (t44) / permeability (t46)
aggregators can query it by endpoint membership.

This module is the tiny, env-free helper those aggregators call: given an already-collected generalist
``OutputRecord`` (the object ``core.dispatch`` produced for ADMET-AI, or its plain-JSON dict
form), it pulls out the P-gp probability and normalizes it to a single efflux flag in ``[0, 1]``. It
does **not** re-run any model and imports nothing from ``core`` (it duck-types the record), so it is
trivially unit-testable on the laptop with no box, GPU or pixi env.

Contract of the returned flag:
- **Range:** ``[0, 1]`` probability of P-gp substrate / inhibitor.
- **Direction:** ``UP = more efflux liability`` - this is already the native direction of
  ``Pgp_Broccatelli`` (P of the positive P-gp class), so NO inversion is applied.
- **Not a gate:** narrow-domain, usable only in-domain; it is one vote in the efflux row of the
  distribution / permeability aggregators, never a stand-alone promote/reject (IO_SPEC §1 #16,
  ``distribution/__init__.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ADMET-AI's TDC head name is a stable literal in that model's ``endpoint_values`` (IO_SPEC §1 #1;
# endpoints/triage/admet_ai). It is the P-gp source.
ADMET_AI_PGP_KEY = "Pgp_Broccatelli"

# Source keys tried in priority order (currently ADMET-AI only).
_PGP_SOURCE_KEYS: tuple[str | None, ...] = (ADMET_AI_PGP_KEY,)


@dataclass(frozen=True)
class PgpFlag:
    """The extracted efflux flag plus which generalist head it came from (for aggregator provenance)."""

    value: float | None
    source_key: str | None
    source_model: str | None


def _endpoint_values(record: Any) -> dict[str, Any]:
    """Pull the ``endpoint_values`` mapping off an ``OutputRecord`` instance or its plain-dict form.

    The helper is used by aggregators that may hold either the validated ``core.schemas.OutputRecord``
    object or the raw JSON dict collected from the model subprocess, so it accepts both and never
    imports ``core``.
    """
    ev = getattr(record, "endpoint_values", None)
    if ev is None and isinstance(record, dict):
        ev = record.get("endpoint_values")
    return ev if isinstance(ev, dict) else {}


def _model_name(record: Any) -> str | None:
    """Best-effort read of the record's ``model`` field (an enum or a plain string), for provenance."""
    model = getattr(record, "model", None)
    if model is None and isinstance(record, dict):
        model = record.get("model")
    if model is None:
        return None
    # ModelName is a StrEnum, so ``str(...)`` yields the value; a plain string passes through.
    return getattr(model, "value", str(model))


def extract_pgp(record: Any) -> PgpFlag:
    """Extract + normalize the P-gp efflux flag from one generalist ``OutputRecord`` (or its dict form).

    Reads ADMET-AI's ``Pgp_Broccatelli`` head.
    Returns a :class:`PgpFlag` whose ``value`` is a probability in ``[0, 1]`` (UP = more efflux
    liability) or ``None`` when the head is absent, null, non-numeric, or out of the ``[0, 1]`` range.
    Out-of-range values are rejected (``None``) rather than silently clamped, so a malformed upstream
    number never masquerades as a real probability.
    """
    ev = _endpoint_values(record)
    for key in _PGP_SOURCE_KEYS:
        if not key or key not in ev:
            continue
        raw = ev[key]
        if raw is None or isinstance(raw, bool):
            # ``None`` = head present but not predicted (e.g. bad SMILES); a bool is not a probability.
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if 0.0 <= value <= 1.0:
            return PgpFlag(value=value, source_key=key, source_model=_model_name(record))
        # Numeric but outside [0, 1]: not a valid probability - reject rather than fabricate/clamp.
        continue
    return PgpFlag(value=None, source_key=None, source_model=None)


def extract_pgp_flag(record: Any) -> float | None:
    """Convenience wrapper returning just the normalized efflux flag (``[0, 1]`` or ``None``)."""
    return extract_pgp(record).value
