#!/usr/bin/env python
"""lipophilicity aggregator - a logD consensus, anchored to the measured series logD ~= 1.

Contract (CLAUDE.md §2): ``aggregate(records: list[OutputRecord]) -> EndpointResult``. It runs in the
core env (no box, no GPU): it only consumes already-collected ``OutputRecord``s and harmonizes them
onto one common quantity.

Common quantity = **logD (log units) at pH 7.4**, anchored to the measured series logD ~= 1
(IO_SPEC §2 lipophilicity; task t40). The three contributing lenses (IO_SPEC §1 #20/#21/#22):

    model            field                       kind    transform onto the logD axis
    -----            -----                       ----    ----------------------------
    rdkit_crippen    logP_crippen (WLOGP lens)   logP    logP -> logD via the shared pKa (F-12)
    swissadme        Consensus_logP (3-lens mean) logP   logP -> logD via the shared pKa (F-12)
    opera            LogD_pred (+ Conf_index_LogD) logD   identity; carry the native confidence

LANDMINE F-12 (the point of this file): for the di-basic FTO series **logP != logD** at pH 7.4. A raw
logP lens must NOT be dropped into a logD consensus unconverted - that silently corrupts the number.
So every logP lens is passed through a Henderson-Hasselbalch conversion using a single shared pKa
BEFORE it is allowed into the consensus; a logP lens with no available pKa is carried but kept OUT of
the consensus (its ``logd`` stays ``None``) and noted. Each lens records whether it is native logD or a
converted logP, so the mix is always auditable.

DEFERRED boundaries honored here (CLAUDE.md §4a; wired to a placeholder, never invented):
- **F-13 (single shared pKa source).** BBB Score / CNS MPO / SFI / this aggregator must all share ONE
  pKa. That source is undecided. The placeholder is OPERA's own ``pKa_b_pred`` (basic pKa, since FTO is
  basic), read from the OPERA records if present; an explicit ``pka=`` overrides it for injection/test.
  TODO: replace with the single project-wide pKa source once F-13 is decided.
- **F-16 (the FTO di-cation protonation/tautomer model).** The compound is di-basic; the honest
  multi-site micro-pKa conversion is undecided. The placeholder is the standard monoprotic H-H
  (one pKa, base by default). It will NOT reconcile logP to logD for a genuinely di-protic center - and
  that is fine: the residual divergence surfaces as *spread*, which raises the flag and defers to the
  measured anchor. We do not fabricate a di-cation formula to force convergence.
- **Spread -> calibrated confidence.** Turning the lens spread into a calibrated uncertainty is the
  DEFERRED AD/calibration policy. Here the spread drives a documented low/high heuristic flag only; the
  thresholds are named constants marked as heuristics, not a calibrated cut.

The uncertainty signal is the **spread across lenses** (IO_SPEC §2: convergence = trust; scatter -> lean
on measured logD ~= 1). A consensus far from the measured anchor also lowers trust (task t40): a number
far from logD ~= 1 should raise the flag, not be believed.
"""

from __future__ import annotations

import math
import statistics
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.models import Endpoint, ModelName
from core.schemas import OutputRecord

# --------------------------------------------------------------------------------------------------
# Constants (measured anchor + heuristic flag thresholds). The thresholds are HEURISTICS: calibration
# is DEFERRED (CLAUDE.md §4a), so they are named and documented, not presented as a calibrated cut.
# --------------------------------------------------------------------------------------------------
MEASURED_LOGD_ANCHOR = 1.0   # the measured FTO series logD (IO_SPEC §2 / task t40)
DEFAULT_PH = 7.4             # physiological pH for the logD definition

# Range (max - min) across the logD lenses at or below which the lenses are considered converged.
# HEURISTIC (log units); the calibrated cut is DEFERRED.
SPREAD_RANGE_TRUST = 1.0
# How far the consensus may sit from the measured anchor before trust drops. HEURISTIC (log units).
ANCHOR_TOLERANCE = 2.0


class Lens(BaseModel):
    """One contributing lipophilicity lens, harmonized onto the logD axis.

    ``raw_kind`` records whether the model natively emits logP or logD; ``converted`` is True iff a
    logP->logD Henderson-Hasselbalch step was applied. ``logd`` is the value on the common axis (``None``
    for a logP lens that had no pKa to convert with - such a lens is carried but excluded from the
    consensus, never averaged in raw). ``confidence`` carries a native reliability signal (OPERA's
    ``Conf_index_LogD``), if the model emits one.
    """

    model_config = ConfigDict(extra="forbid")

    model: ModelName
    label: str
    raw_kind: str  # "logP" | "logD"
    raw_value: float
    logd: float | None
    converted: bool
    confidence: float | None = None


class EndpointResult(BaseModel):
    """The harmonized lipophilicity result: one consensus logD, the per-lens breakdown, and the flag.

    This is the first aggregator to land, so ``EndpointResult`` is defined here (the aggregators own
    their result shape until/unless a shared one is promoted into ``core``; a model task may not touch
    ``core``). The shape is deliberately generic-consensus: a common ``quantity``, a ``consensus`` scalar,
    the contributing ``lenses``, the spread, and the low/high flag with its reasons.
    """

    model_config = ConfigDict(extra="forbid")

    endpoint: Endpoint = Endpoint.lipophilicity
    quantity: str = "logD (log units, pH 7.4)"
    consensus: float | None
    lenses: list[Lens]
    n_lenses: int
    spread_range: float | None
    spread_std: float | None
    spread_flag: str  # "low" | "high" - the convergence flag (task t40 done-criteria)
    trust: bool
    recommend_measured_anchor: bool
    flag_reasons: list[str]
    measured_anchor: float = MEASURED_LOGD_ANCHOR
    pka_used: float | None
    pka_source: str | None
    pka_kind: str | None
    notes: list[str] = Field(default_factory=list)
    deferred: list[str] = Field(default_factory=list)


def logp_to_logd(logp: float, pka: float, ph: float = DEFAULT_PH, kind: str = "base") -> float:
    """Henderson-Hasselbalch logP -> logD at ``ph`` for a monoprotic center (the DEFERRED F-16 placeholder).

    ``logD = logP + log10(f_neutral)`` where ``f_neutral`` is the neutral fraction:
    - base:  ``f_neutral = 1 / (1 + 10**(pKa - pH))``  -> ``logD = logP - log10(1 + 10**(pKa - pH))``
    - acid:  ``f_neutral = 1 / (1 + 10**(pH - pKa))``  -> ``logD = logP - log10(1 + 10**(pH - pKa))``

    This is the standard single-pKa relation. The FTO series is di-basic (F-16), so the true conversion
    is multi-site; that decision is DEFERRED and this monoprotic form is the documented placeholder. Any
    residual logP/logD gap it leaves for a di-protic center shows up downstream as lens spread (which
    raises the flag), rather than being papered over with an invented di-cation formula.
    """
    if kind == "base":
        exponent = pka - ph
    elif kind == "acid":
        exponent = ph - pka
    else:  # pragma: no cover - guarded input
        raise ValueError(f"kind must be 'base' or 'acid', got {kind!r}")
    return float(logp - math.log10(1.0 + 10.0 ** exponent))


def _as_output_record(rec: Any) -> OutputRecord:
    """Coerce a dict (or an already-built ``OutputRecord``) into an ``OutputRecord`` for uniform access."""
    if isinstance(rec, OutputRecord):
        return rec
    return OutputRecord.model_validate(rec)


def _resolve_pka(
    records: list[OutputRecord],
    override: float | None,
    override_kind: str | None,
) -> tuple[float | None, str | None, str | None]:
    """Pick the single shared pKa (value, source, kind). F-13 DEFERRED: OPERA is the placeholder source.

    Precedence: an explicit ``override`` (kind defaults to base, since FTO is basic) wins; otherwise
    OPERA's ``pKa_b_pred`` (basic) is preferred, falling back to ``pKa_a_pred`` (acidic). Returns
    ``(None, None, None)`` when no pKa is available - in which case logP lenses cannot be converted and
    are kept out of the consensus (F-12).
    """
    if override is not None:
        return float(override), "injected", (override_kind or "base")

    pka_b: float | None = None
    pka_a: float | None = None
    for rec in records:
        if rec.model != ModelName.opera:
            continue
        ev = rec.endpoint_values or {}
        if ev.get("pKa_b") is not None and pka_b is None:
            pka_b = float(ev["pKa_b"])  # type: ignore[arg-type]
        if ev.get("pKa_a") is not None and pka_a is None:
            pka_a = float(ev["pKa_a"])  # type: ignore[arg-type]

    if pka_b is not None:
        return pka_b, "opera:pKa_b", "base"
    if pka_a is not None:
        return pka_a, "opera:pKa_a", "acid"
    return None, None, None


def _logp_lens(
    model: ModelName,
    label: str,
    logp: float,
    pka: float | None,
    ph: float,
    kind: str | None,
) -> Lens:
    """Build a logP lens, converting to logD via the shared pKa when one is available (F-12)."""
    if pka is None:
        # No shared pKa: a raw logP MUST NOT enter the logD consensus (F-12). Carry it, exclude it.
        return Lens(model=model, label=label, raw_kind="logP", raw_value=logp, logd=None, converted=False)
    logd = logp_to_logd(logp, pka, ph=ph, kind=kind or "base")
    return Lens(model=model, label=label, raw_kind="logP", raw_value=logp, logd=logd, converted=True)


def aggregate(
    records: list[OutputRecord] | list[dict[str, Any]],
    *,
    pka: float | None = None,
    pka_kind: str | None = None,
    ph: float = DEFAULT_PH,
    measured_anchor: float = MEASURED_LOGD_ANCHOR,
) -> EndpointResult:
    """Harmonize the lipophilicity lenses onto a logD consensus, with the spread/anchor trust flag.

    ``pka`` (with optional ``pka_kind`` in ``{"base","acid"}``) injects the single shared pKa; when it is
    ``None`` the placeholder source (OPERA ``pKa_b_pred``, F-13) is read from the records. logP lenses are
    converted to logD BEFORE entering the consensus; logD lenses pass through. The consensus is the mean
    of the lenses on the logD axis; the spread across them is the uncertainty signal.
    """
    recs = [_as_output_record(r) for r in records]
    pka_used, pka_source, kind = _resolve_pka(recs, pka, pka_kind)

    lenses: list[Lens] = []
    notes: list[str] = []

    for rec in recs:
        ev = rec.endpoint_values or {}
        if rec.model == ModelName.rdkit_crippen:
            v = ev.get("logP_crippen")
            if v is None:
                continue
            lenses.append(_logp_lens(ModelName.rdkit_crippen, "WLOGP (RDKit Crippen)", float(v), pka_used, ph, kind))
        elif rec.model == ModelName.swissadme:
            v = ev.get("Consensus_logP")
            if v is None:
                continue
            lenses.append(
                _logp_lens(ModelName.swissadme, "SwissADME reproduced logP consensus", float(v), pka_used, ph, kind)
            )
        elif rec.model == ModelName.opera:
            v = ev.get("LogD")
            if v is None:
                continue  # OPERA pKa/LogP/other records are not logD lenses; pKa handled in _resolve_pka
            conf = rec.uncertainty.conf_index if rec.uncertainty is not None else None
            lenses.append(
                Lens(
                    model=ModelName.opera,
                    label="OPERA LogD_pred",
                    raw_kind="logD",
                    raw_value=float(v),
                    logd=float(v),
                    converted=False,
                    confidence=conf,
                )
            )
        # any other model in the record set is not a lipophilicity lens -> ignored

    # Lenses that reached the common axis (native logD, or a logP successfully converted).
    on_axis = [l for l in lenses if l.logd is not None]
    unconverted = [l for l in lenses if l.logd is None]
    if unconverted:
        names = ", ".join(f"{l.model} ({l.raw_value:+.2f})" for l in unconverted)
        notes.append(
            f"no shared pKa available: {len(unconverted)} logP lens/es kept OUT of the logD consensus "
            f"(F-12, never averaged raw): {names}. Provide a pKa (F-13) to include them."
        )

    values = [l.logd for l in on_axis if l.logd is not None]
    if values:
        consensus: float | None = float(statistics.fmean(values))
        spread_range: float | None = float(max(values) - min(values))
        spread_std: float | None = float(statistics.stdev(values)) if len(values) > 1 else 0.0
    else:
        consensus = None
        spread_range = None
        spread_std = None
        notes.append("no lens reached the logD axis: consensus undefined; lean fully on measured logD ~= 1.")

    # Flag logic. spread_flag is the pure convergence signal (task t40 done-criteria). Trust also
    # requires the consensus to sit near the measured anchor (task t40: a consensus far from logD ~= 1
    # should raise the flag, not be trusted).
    flag_reasons: list[str] = []
    if spread_range is None:
        spread_flag = "high"
        flag_reasons.append("no logD lens available")
    elif spread_range <= SPREAD_RANGE_TRUST:
        spread_flag = "low"
        flag_reasons.append(f"lenses converge (range {spread_range:.2f} <= {SPREAD_RANGE_TRUST} log units)")
    else:
        spread_flag = "high"
        flag_reasons.append(f"lenses scatter (range {spread_range:.2f} > {SPREAD_RANGE_TRUST} log units)")

    far_from_anchor = consensus is not None and abs(consensus - measured_anchor) > ANCHOR_TOLERANCE
    if far_from_anchor:
        flag_reasons.append(
            f"consensus {consensus:.2f} is > {ANCHOR_TOLERANCE} log units from measured logD ~= {measured_anchor}"
        )

    trust = spread_flag == "low" and not far_from_anchor and consensus is not None
    recommend_measured_anchor = not trust

    return EndpointResult(
        consensus=consensus,
        lenses=lenses,
        n_lenses=len(on_axis),
        spread_range=spread_range,
        spread_std=spread_std,
        spread_flag=spread_flag,
        trust=trust,
        recommend_measured_anchor=recommend_measured_anchor,
        flag_reasons=flag_reasons,
        measured_anchor=measured_anchor,
        pka_used=pka_used,
        pka_source=pka_source,
        pka_kind=kind,
        notes=notes,
        deferred=[
            "F-13: single shared pKa source is DEFERRED; placeholder = OPERA pKa_b_pred (or injected pka=).",
            "F-16: di-cation (di-basic) protonation model is DEFERRED; placeholder = monoprotic H-H.",
            "spread -> calibrated confidence is DEFERRED (AD/calibration policy); thresholds here are heuristics.",
        ],
    )
