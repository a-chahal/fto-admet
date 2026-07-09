#!/usr/bin/env python
"""triage aggregator - the funnel-entry generalist summary. FLAGS ONLY, no kills.

Contract (task t51, CLAUDE.md §2, IO_SPEC §2 "triage"/§1 #1-#3, SETTLED §7 "Phase 1 - flags only,
no kills here"): this is the FIRST thing a molecule meets in the funnel. It runs in the core env (no
box, no GPU) and summarizes the two cross-cutting generalists into a compact per-property flag table:

    model       role                                     native confidence signal
    -----       ----                                     -------------------------
    admet_ai    BROAD baseline (ADMET-AI v2)             none (INDIRECT: cross-model spread only)
    admetlab3   BROAD (119 heads, DMPNN + descriptors)   per-endpoint high/low Youden confidence FLAG

The headline design rule (task t51, SETTLED §7): **triage FLAGS, it never KILLS.** No threshold here
promotes or rejects a molecule; there is no pass/fail verdict, no gate, no kill. Every field this
aggregator emits is a routing hint (a flag), and every ``PropertyFlag.is_gate`` is explicitly False.

UNCERTAINTY = CROSS-MODEL SPREAD (INDIRECT), per the task and IO_SPEC §1 #1: where the generalists that
report the SAME property DIVERGE, the divergence flag is raised. A single generalist is NEVER authority
(task t51 landmine): a property reported by exactly one model is marked ``single_source`` (not
cross-checked), never "confident". ADMETlab's high/low confidence flag FEEDS the confidence read on top
of the spread signal (surfaced per property).

CROSS-MODEL MATCHING, and an honest limit (F-6, NEEDS_AARAN). Cross-model spread can only be computed
for properties the models report under the SAME canonical key. Here:
  - ``admet_ai`` heads are canonical named columns (``hERG`` / ``BBB_Martins`` / the CYP heads / ...),
    read as emitted (IO_SPEC §1 #1).
  - ``admetlab3``'s 119 literal column names are a build-time live read (F-6, NEEDS_AARAN): they are NOT
    hardcoded here. Its heads are read as emitted and surface as their own rows; a *semantic crosswalk*
    that would let an ADMETlab head share a canonical key with an ADMET-AI head needs that captured header
    and is a documented TODO (below), NOT invented. So in real data spread fires where key names coincide;
    the synthetic test drives the divergence logic directly. This is deliberate: fabricating a name
    crosswalk before the header is captured is exactly the kind of guess CLAUDE.md §5 forbids.

EXCLUSIONS (task t51 / F-17): ADMET-AI's ``VDss_Lombardo`` and ``Half_Life_Obach`` are already absent
from ``endpoint_values`` (the t21 adapter quarantines them in ``raw``). This aggregator ONLY reads
``endpoint_values`` and additionally guards those two names, so they can never be resurrected here.

DEFERRED (CLAUDE.md §4a; wired to a documented boundary, never invented):
  - The divergence threshold on probability-scale values is a coarse TRIAGE default; the calibrated
    AD / decision policy that would turn a flag into a promote/reject call is DEFERRED.
  - A numeric divergence cut for NON-probability scales (regression heads) needs per-property units and
    calibration -> the raw spread is recorded but does NOT raise a flag on those scales (DEFERRED).
  - Only ADMETlab's explicit high/low flag drives a native low-confidence mark (a calibrated cutoff on
    any other native signal is DEFERRED).
  - The ADMET-AI VDss/half-life exclusion (F-17) is honored by only reading ``endpoint_values``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.models import Endpoint, ModelName
from core.schemas import OutputRecord

# --------------------------------------------------------------------------------------------------
# The two cross-cutting generalists this triage view summarizes (IO_SPEC §1 #1-#2). Read by model
# identity, never by folder. A record from any other model is ignored (triage is generalist-only).
# --------------------------------------------------------------------------------------------------
GENERALISTS: frozenset[ModelName] = frozenset(
    {ModelName.admet_ai, ModelName.admetlab3}
)

# ADMET-AI heads the model itself reports as worse-than-the-mean (F-17). Already absent from
# endpoint_values (t21 quarantines them in raw); guarded here too so they can NEVER be resurrected.
EXCLUDED_R2_NEGATIVE: frozenset[str] = frozenset({"VDss_Lombardo", "Half_Life_Obach"})

# Coarse TRIAGE divergence threshold for probability-scale values (all reads in [0, 1]). Two generalists
# whose probabilities straddle a gap this wide are "divergent". This is a documented heuristic, not a
# calibrated cut (the calibrated AD/decision policy is DEFERRED, CLAUDE.md §4a).
PROB_SPREAD_FLAG = 0.4

# Confidence read labels (a routing hint, NEVER a gate). "single_source" is deliberately distinct from
# "ok": a single generalist is never authority (task t51 landmine), so it is not "confident".
CONF_LOW = "low"                    # generalists diverge, or a native low-confidence signal is present
CONF_OK = "ok"                      # >= 2 generalists agree and no native low-confidence signal
CONF_SINGLE = "single_source"       # only one generalist reports it -> not cross-checked, not authority
CONF_NONE = "none"                  # no numeric value to read

# ADMETlab per-endpoint confidence flag values (Youden high/low, IO_SPEC §1 #2).
CONF_FLAG_LOW = "low"
CONF_FLAG_HIGH = "high"


def _as_output_record(rec: Any) -> OutputRecord:
    """Coerce a dict (or an already-built ``OutputRecord``) into an ``OutputRecord`` for uniform access."""
    if isinstance(rec, OutputRecord):
        return rec
    return OutputRecord.model_validate(rec)


def _scalar(value: Any) -> float | int | bool | None:
    """Coerce an endpoint value to a JSON-safe scalar for the flag table; non-numeric strings -> None value."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _numeric(value: Any) -> float | None:
    """The comparable numeric view of a read's value for spread (bool -> 0/1); None if not numeric."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    return None


class GeneralistRead(BaseModel):
    """One generalist's read of one property: the raw value + any native confidence signal it carried.

    ``native_conf_flag`` is ADMETlab's per-endpoint Youden high/low flag, surfaced as context; the value
    itself is NEVER averaged across models (only same-scale spread is computed, see below).
    """

    model_config = ConfigDict(extra="forbid")

    model: ModelName
    field: str
    value: float | int | bool | None
    native_conf_flag: str | None = None


class PropertyFlag(BaseModel):
    """One row of the triage flag table: one property, every generalist that reported it, and the flags.

    ``spread`` is max-min across the numeric reads (``None`` for a single read or non-numeric values).
    ``prob_scale`` records whether every read sat in [0, 1] (the only scale on which the divergence flag
    fires; a non-probability spread is recorded but does NOT raise a flag - DEFERRED). ``divergent`` is
    the raised uncertainty flag (cross-model spread). ``confidence`` folds spread + native signals into a
    routing label. ``is_gate`` is always False and stated explicitly: triage flags, it never kills.
    """

    model_config = ConfigDict(extra="forbid")

    property: str
    reads: list[GeneralistRead]
    n_models: int
    spread: float | None = None
    prob_scale: bool = False
    divergent: bool = False
    confidence: str = CONF_NONE
    is_gate: bool = False   # explicit: a triage flag NEVER terminates a molecule (SETTLED §7).
    notes: list[str] = Field(default_factory=list)


class MoleculeTriage(BaseModel):
    """One molecule's funnel-entry triage view: the per-property flag table + a compact divergence summary."""

    model_config = ConfigDict(extra="forbid")

    mol_id: str
    present: bool
    properties: list[PropertyFlag] = Field(default_factory=list)
    n_properties: int = 0
    divergent_properties: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class EndpointResult(BaseModel):
    """The triage result: a per-molecule generalist flag table. FLAGS ONLY - deliberately no gate/kill.

    There is intentionally NO promote/reject scalar or pass/fail verdict anywhere: triage routes, it does
    not terminate. The aggregator owns its own result shape (an aggregator task may not touch ``core``).
    """

    model_config = ConfigDict(extra="forbid")

    endpoint: Endpoint = Endpoint.triage
    quantity: str = (
        "funnel-entry generalist summary: a per-property flag table over ADMET-AI v2 / ADMETlab 3.0. "
        "Uncertainty = cross-model spread (divergent generalists raise the flag); a single "
        "generalist is never authority. FLAGS ONLY - no threshold, gate, kill, or pass/fail verdict."
    )
    molecules: list[MoleculeTriage]
    n_molecules: int
    notes: list[str] = Field(default_factory=list)
    deferred: list[str] = Field(default_factory=list)


def _conf_flags(rec: OutputRecord) -> dict[str, str]:
    """Read ADMETlab's per-endpoint Youden high/low confidence flags from the shared Uncertainty envelope.

    Documented convention (CLAUDE.md §3): a multi-head generalist carries its per-property high/low flags
    in ``uncertainty.extra["confidence_flags"]`` as a ``{property: "high"|"low"}`` map. If the adapter is
    not yet wired that way (ADMETlab's literal columns are NEEDS_AARAN, F-6), this simply returns empty and
    the confidence read falls back to cross-model spread. TODO: confirm the exact sub-shape once the
    ADMETlab adapter and its captured header land.
    """
    unc = rec.uncertainty
    if unc is None or not unc.extra:
        return {}
    cf = unc.extra.get("confidence_flags")
    if isinstance(cf, Mapping):
        return {str(k): str(v).lower() for k, v in cf.items()}
    return {}


def _reads_for_record(rec: OutputRecord) -> list[tuple[str, GeneralistRead]]:
    """Extract ``(canonical_property, GeneralistRead)`` pairs from one generalist record.

    Non-generalist records are ignored (triage is generalist-only). The two R^2-negative ADMET-AI heads
    are guarded out even if a stray adapter ever emitted them (F-17).
    """
    if rec.model not in GENERALISTS:
        return []

    ev = rec.endpoint_values or {}
    out: list[tuple[str, GeneralistRead]] = []

    conf_flags = _conf_flags(rec)
    for key, val in ev.items():
        if key in EXCLUDED_R2_NEGATIVE:  # never resurrect VDss_Lombardo / Half_Life_Obach (F-17)
            continue
        out.append(
            (key, GeneralistRead(model=rec.model, field=key, value=_scalar(val), native_conf_flag=conf_flags.get(key)))
        )
    return out


def _property_flag(prop: str, reads: list[GeneralistRead]) -> PropertyFlag:
    """Build one flag-table row: compute cross-model spread, the divergence flag, and the confidence read.

    Spread and the divergence flag are computed ONLY across same-scale numeric reads. On the probability
    scale (all reads in [0, 1]) a spread wider than ``PROB_SPREAD_FLAG`` raises ``divergent``. On any other
    numeric scale the spread is recorded but does NOT raise a flag (a calibrated per-property cut is
    DEFERRED). The confidence read: ``low`` if divergent OR a native low-confidence signal is present;
    ``ok`` if >= 2 generalists agree; ``single_source`` if only one generalist reports it (never authority).
    """
    numerics = [n for n in (_numeric(r.value) for r in reads) if n is not None]
    n_models = len(reads)

    spread: float | None = None
    prob_scale = False
    divergent = False
    if len(numerics) >= 2:
        spread = max(numerics) - min(numerics)
        prob_scale = all(0.0 <= n <= 1.0 for n in numerics)
        if prob_scale and spread > PROB_SPREAD_FLAG:
            divergent = True

    native_low = any(r.native_conf_flag == CONF_FLAG_LOW for r in reads)

    if not numerics:
        confidence = CONF_NONE
    elif divergent or native_low:
        confidence = CONF_LOW
    elif n_models >= 2:
        confidence = CONF_OK
    else:
        confidence = CONF_SINGLE

    notes: list[str] = []
    if divergent:
        notes.append(
            f"cross-model spread {spread:.3f} (> {PROB_SPREAD_FLAG}) on the probability scale: the "
            "generalists DIVERGE -> uncertainty flag raised (INDIRECT confidence signal)."
        )
    if spread is not None and not prob_scale:
        notes.append(
            "reads are on a non-probability scale: the numeric spread is recorded but does NOT raise a "
            "divergence flag (a calibrated per-property cut is DEFERRED, CLAUDE.md §4a)."
        )
    if native_low:
        notes.append("a native low-confidence signal (ADMETlab Youden low flag) is present -> confidence = low.")
    if confidence == CONF_SINGLE:
        notes.append("only ONE generalist reports this property: a single generalist is never authority (not cross-checked).")

    return PropertyFlag(
        property=prop,
        reads=reads,
        n_models=n_models,
        spread=spread,
        prob_scale=prob_scale,
        divergent=divergent,
        confidence=confidence,
        notes=notes,
    )


def _triage_for(mol_id: str, records: Sequence[OutputRecord]) -> MoleculeTriage:
    """Assemble one molecule's funnel-entry flag table from its generalist records. FLAGS ONLY."""
    grouped: dict[str, list[GeneralistRead]] = {}
    for rec in records:
        for prop, read in _reads_for_record(rec):
            grouped.setdefault(prop, []).append(read)

    # Deterministic order: property name, so the flag table is stable across runs.
    props = [_property_flag(prop, grouped[prop]) for prop in sorted(grouped)]
    divergent = [p.property for p in props if p.divergent]

    notes = [
        "funnel-entry triage: a per-property flag table over the generalists. FLAGS ONLY - nothing here "
        "promotes, rejects, or kills a molecule (SETTLED §7).",
    ]
    if not props:
        notes.append("no generalist (admet_ai / admetlab3) read present in the bundle.")
    if divergent:
        notes.append(f"{len(divergent)} propert{'y' if len(divergent) == 1 else 'ies'} flagged divergent (cross-model spread).")

    return MoleculeTriage(
        mol_id=mol_id,
        present=bool(props),
        properties=props,
        n_properties=len(props),
        divergent_properties=divergent,
        notes=notes,
    )


def _normalize_molecules(
    molecules: Mapping[str, Sequence[Any]] | Sequence[Any],
) -> list[tuple[str, list[Any]]]:
    """Normalize the accepted input shapes to ``[(mol_id, records), ...]`` (same contract as the other aggregators).

    Accepts: a Mapping ``{mol_id: records}``; a sequence of ``(mol_id, records)`` pairs; a sequence of dicts
    ``{"mol_id"|"id": ..., "records": [...]}``; or a bare sequence of record-lists (id defaults to a
    positional ``mol_<i>``). A record-list is never mistaken for an ``(id, records)`` pair because a pair's
    first element is a ``str`` while a record-list's first element is a record/dict.
    """
    if isinstance(molecules, Mapping):
        return [(str(mid), list(recs)) for mid, recs in molecules.items()]

    out: list[tuple[str, list[Any]]] = []
    for i, item in enumerate(molecules):
        if isinstance(item, Mapping) and "records" in item:
            mid = item.get("mol_id") or item.get("id") or f"mol_{i}"
            out.append((str(mid), list(item["records"])))
        elif (
            isinstance(item, (tuple, list))
            and len(item) == 2
            and isinstance(item[0], str)
            and isinstance(item[1], (list, tuple))
        ):
            out.append((item[0], list(item[1])))
        else:
            out.append((f"mol_{i}", list(item)))
    return out


def aggregate(
    molecules: Mapping[str, Sequence[Any]] | Sequence[Any],
) -> EndpointResult:
    """Summarize the three generalists into the funnel-entry triage flag table per molecule. FLAGS ONLY.

    ``molecules`` is the compound set (see ``_normalize_molecules`` for accepted shapes); each molecule's
    bundle is a list of its model ``OutputRecord``s. For each molecule the generalist reads are grouped by
    canonical property; the uncertainty flag is raised where the generalists that share a property DIVERGE
    (cross-model spread); a single generalist is never authority. There is deliberately no threshold, gate,
    kill, or pass/fail verdict: triage routes, it never terminates a compound (SETTLED §7).
    """
    norm = _normalize_molecules(molecules)
    mols = [_triage_for(mid, [_as_output_record(r) for r in raw_recs]) for mid, raw_recs in norm]

    return EndpointResult(
        molecules=mols,
        n_molecules=len(mols),
        notes=[
            "triage is the funnel entry: a compact per-property flag table over ADMET-AI v2 / ADMETlab 3.0. "
            "FLAGS ONLY - no kills at this stage (SETTLED §7).",
            "uncertainty = cross-model spread (INDIRECT): divergent generalists raise the flag. A single "
            "generalist is never authority; ADMET-AI VDss/half-life stay excluded (F-17).",
            "ADMETlab's Youden high/low flag feeds the confidence read on top of the spread signal.",
        ],
        deferred=[
            "the divergence threshold on the probability scale is a coarse TRIAGE default; the calibrated "
            "AD / decision policy that would turn a flag into a promote/reject call is DEFERRED (CLAUDE.md §4a).",
            "a numeric divergence cut for non-probability (regression) scales is DEFERRED: that spread is "
            "surfaced, not thresholded.",
            "a SEMANTIC cross-model name crosswalk (so an ADMETlab head can share a canonical key with an "
            "ADMET-AI head) needs ADMETlab's captured 119-column header (F-6, NEEDS_AARAN) and is NOT "
            "invented here; until then spread fires only where key names already coincide.",
        ],
    )
