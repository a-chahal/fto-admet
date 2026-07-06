#!/usr/bin/env python
"""ppb aggregator - a plasma-protein-binding consensus on ONE common quantity: fraction bound (0-1).

Contract (task t45, CLAUDE.md §2, IO_SPEC §2 "ppb" + §3 F-7): this endpoint has NO model of its own
(no ``ModelName`` maps to ``Endpoint.ppb``). It runs in the core env (no box, no GPU) and consumes
fields already emitted by three cross-cutting sources, harmonizing them onto a single common axis:

    common quantity = fraction bound (0-1);  direction: UP = more bound (less free)

    source (model -> field)          native scale         transform onto fraction bound
    -----------------------          ------------         -----------------------------
    ochem_ppb  -> % bound (primary)  % bound              pct / 100
    admet_ai   -> PPBR_AZ            % bound              pct / 100
    opera      -> FuB                fraction UNBOUND     1 - FuB   (the inversion; the landmine)

LANDMINE (task t45 / IO_SPEC §3 F-7): the three sources are on TWO different representations. OCHEM and
ADMET-AI are PERCENT bound (divide by 100); OPERA's ``FuB`` is FRACTION UNBOUND (invert: 1 - FuB). A
missed inversion or a %/fraction mixup silently corrupts the consensus (an FuB of 0.1 means 90% bound,
not 10%). Each source is therefore normalized on its OWN documented scale BEFORE it enters the
consensus, and every source records its native scale + the transform applied, so the mix is auditable.

Unlike an incompatible-scale endpoint (permeability/distribution, where averaging is meaningless), here
all three sources DO land on the same physical quantity, so a numeric consensus (the mean fraction
bound) is meaningful. But sources with different assays/training sets can diverge; per the orchestrator
brief we do NOT hide divergence behind a single fused number. So the consensus is reported ALONGSIDE the
spread across sources (range + std), and a wide spread flips a ``confident`` flag off and raises the
uncertainty note. Convergence = trust; scatter -> the number is soft. This mirrors the lipophilicity
aggregator's spread-as-confidence design (task t40).

Not a gate (PPB is a modulator, not a hard filter): a single tool is acceptable and cross-checks are
optional, so the aggregator tolerates ANY subset of the three sources being present (IO_SPEC §2).

DEFERRED boundaries honored here (CLAUDE.md §4a; wired to a documented placeholder, never invented):
- F-7 (OCHEM unit + field name). IO_SPEC §3 F-7 marks the OCHEM response unit (fraction vs %) and JSON
  field names as UNVERIFIED pending a live docs.ochem.eu / model-service read. This aggregator follows
  the t45 brief + orchestrator note (the t36 adapter emits % bound; divide by 100) and reads the OCHEM
  % bound value from a documented candidate-key set (``OCHEM_PCT_BOUND_KEYS``). Reconciling the exact
  emitted key + confirming the unit is the t36 adapter's live residue; a divergence is FLAGGED here, not
  silently reinterpreted. See the note attached to any OCHEM source whose raw % value looks fractional.
- Spread -> calibrated confidence. Turning the source spread into a calibrated uncertainty is the
  DEFERRED AD/calibration policy; here the spread drives a documented low/high heuristic flag only, with
  the threshold a named constant (not a calibrated cut).
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.models import Endpoint, ModelName
from core.schemas import OutputRecord

# --------------------------------------------------------------------------------------------------
# Source field names. These are the ONLY keys this aggregator reads. Each source is normalized onto the
# common fraction-bound axis on its OWN native scale before any consensus is taken.
# --------------------------------------------------------------------------------------------------
ADMET_AI_KEY = "PPBR_AZ"  # admet_ai (t21): plasma-protein-binding rate, PERCENT bound (%); /100 -> fraction.
# OPERA (t33) emits FuB (fraction UNBOUND, 0-1) as its own OutputRecord. The adapter's emitted key is
# "FuB"; the t45 brief names it "FuB_pred". Accept both so a rename on either side does not silently drop
# the source (the inversion 1 - FuB is what matters, not the exact key).
OPERA_FUB_KEYS: tuple[str, ...] = ("FuB", "FuB_pred")
# OCHEM PPB (t36) emits % bound. Its exact emitted key is UNVERIFIED (F-7; the t36 adapter is not live
# yet), so a documented candidate set is tried in order. RECONCILE with the t36 adapter's real key once
# it lands; do NOT treat this list as a verified contract.
OCHEM_PCT_BOUND_KEYS: tuple[str, ...] = (
    "PPB",
    "ppb",
    "percent_bound",
    "PPB_percent",
    "pct_bound",
    "plasma_protein_binding",
)

# Native-scale labels (recorded on each source so the transform is auditable).
SCALE_PCT_BOUND = "% bound"
SCALE_FRACTION_UNBOUND = "fraction unbound"

# Spread flag literals (kept as constants so tests bind to them, not to raw strings).
LOW = "low"
HIGH = "high"
NA = "n/a"

# Heuristic: the range (max - min) across the per-source fraction-bound values at or below which the
# sources are considered converged (a trustworthy consensus). Fraction units. The calibrated cut is
# DEFERRED (CLAUDE.md §4a); this is a named heuristic, not a calibrated threshold.
SPREAD_RANGE_TRUST = 0.15


class PPBSource(BaseModel):
    """One plasma-protein-binding source, harmonized onto the common fraction-bound axis.

    ``native_scale`` names the scale the model emits on (``% bound`` or ``fraction unbound``) and
    ``transform`` states exactly what was applied to reach ``fraction_bound`` - so the %/fraction and the
    OPERA inversion are always visible for audit. ``fraction_bound`` is the value on the common axis (UP =
    more bound). ``confidence`` / ``ad_in_domain`` carry any native reliability signal (OCHEM's accuracy /
    AD, OPERA's ``Conf_index`` / ``AD``); ADMET-AI's PPBR head emits none. ``primary`` marks OCHEM, the
    designated primary tool for this endpoint (IO_SPEC §2).
    """

    model_config = ConfigDict(extra="forbid")

    model: ModelName
    field: str
    native_scale: str
    transform: str
    raw_value: float
    fraction_bound: float
    confidence: float | None = None
    ad_in_domain: bool | None = None
    primary: bool = False
    notes: list[str] = Field(default_factory=list)


class MoleculePPB(BaseModel):
    """One molecule's plasma-protein-binding read: a fraction-bound consensus + the spread-as-confidence.

    ``consensus`` is the mean of the present sources' ``fraction_bound`` (``None`` when no source is
    present). ``spread_range`` / ``spread_std`` are the divergence across sources; ``spread_flag`` and
    ``confident`` turn that spread into a documented low/high heuristic (convergence = trust). All sources
    stay visible in ``sources`` so a wide spread is never hidden behind the single consensus number.
    """

    model_config = ConfigDict(extra="forbid")

    mol_id: str
    consensus: float | None
    sources: list[PPBSource] = Field(default_factory=list)
    n_sources: int = 0
    spread_range: float | None = None
    spread_std: float | None = None
    spread_flag: str = NA          # "low" | "high" | "n/a" (fewer than 2 sources)
    confident: bool = False
    notes: list[str] = Field(default_factory=list)


class EndpointResult(BaseModel):
    """The harmonized ppb result: one fraction-bound consensus per molecule, plus the per-source breakdown.

    The aggregator owns its own result shape (an aggregator task may not touch ``core``). Direction on the
    common axis is UP = more bound (less free). Not a gate; a single source is acceptable.
    """

    model_config = ConfigDict(extra="forbid")

    endpoint: Endpoint = Endpoint.ppb
    quantity: str = (
        "fraction bound (0-1); UP = more bound (less free). Consensus = mean of the present sources' "
        "fraction bound, normalized each on its OWN scale (OCHEM/ADMET-AI % -> /100; OPERA FuB -> 1 - FuB); "
        "reported alongside the cross-source spread as the confidence signal. Not a gate (modulator)."
    )
    molecules: list[MoleculePPB]
    n_molecules: int
    notes: list[str] = Field(default_factory=list)
    deferred: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------------------------------
# Per-scale normalizers. Each takes ONE source value on its native scale and returns fraction bound. This
# is the ONLY place a raw value is transformed; the %/fraction split and the OPERA inversion live here.
# --------------------------------------------------------------------------------------------------
def pct_to_fraction_bound(pct: float) -> float:
    """Normalize a PERCENT-bound value (OCHEM / ADMET-AI) to fraction bound: ``pct / 100``."""
    return float(pct) / 100.0


def fub_to_fraction_bound(fub: float) -> float:
    """Invert OPERA's FRACTION-UNBOUND (``FuB``) to fraction bound: ``1 - FuB`` (the F-7 inversion).

    This is the landmine: ``FuB = 0.1`` means the molecule is 90% bound, not 10%. Dropping ``FuB`` into
    the consensus without inverting silently corrupts it.
    """
    return 1.0 - float(fub)


def _as_output_record(rec: Any) -> OutputRecord:
    """Coerce a dict (or an already-built ``OutputRecord``) into an ``OutputRecord`` for uniform access."""
    if isinstance(rec, OutputRecord):
        return rec
    return OutputRecord.model_validate(rec)


def _native_confidence(rec: OutputRecord) -> tuple[float | None, bool | None]:
    """Pull a native reliability signal off a record's ``uncertainty`` envelope (confidence + AD-in-domain).

    Prefers the generic scalar ``confidence`` (e.g. OCHEM's accuracy estimate), then OPERA's
    ``conf_index``; ``ad_in_domain`` is OPERA's ``AD`` flag. Returns ``(None, None)`` when the record
    carries no uncertainty (ADMET-AI's PPBR head emits none).
    """
    unc = rec.uncertainty
    if unc is None:
        return None, None
    conf = unc.confidence if unc.confidence is not None else unc.conf_index
    return conf, unc.ad_in_domain


def _first_present(ev: Mapping[str, Any], keys: Sequence[str]) -> tuple[str, Any] | None:
    """Return the first ``(key, value)`` in ``ev`` whose key is in ``keys`` and whose value is not None."""
    for k in keys:
        if ev.get(k) is not None:
            return k, ev[k]
    return None


def _range_note(source: PPBSource) -> None:
    """Attach a soft, NON-destructive sanity note when a normalized value is implausible (F-7 tripwire).

    A fraction bound outside [0, 1] means a unit error upstream; and a PERCENT-bound source whose RAW
    value already sits in [0, 1] may in fact be a fraction that should NOT have been divided by 100 (the
    F-7 %/fraction ambiguity). We flag both but never rewrite the value: silently reinterpreting is the
    exact landmine. The reader/AD policy decides; the aggregator only surfaces.
    """
    if not (0.0 <= source.fraction_bound <= 1.0):
        source.notes.append(
            f"normalized fraction_bound {source.fraction_bound:.4f} is outside [0, 1] - likely a unit "
            "error upstream; surfaced, not clamped."
        )
    if source.native_scale == SCALE_PCT_BOUND and 0.0 <= source.raw_value <= 1.0:
        source.notes.append(
            f"raw % value {source.raw_value:.4f} already lies in [0, 1]; if the source actually emits a "
            "FRACTION (F-7, unverified), the /100 here is wrong. Reconcile against the live unit."
        )


def _sources_for_molecule(records: Sequence[OutputRecord]) -> list[PPBSource]:
    """Extract every present ppb source from one molecule's records, each normalized onto fraction bound."""
    sources: list[PPBSource] = []

    for rec in records:
        ev = rec.endpoint_values or {}

        if rec.model == ModelName.ochem_ppb:
            hit = _first_present(ev, OCHEM_PCT_BOUND_KEYS)
            if hit is not None:
                key, raw = hit
                conf, ad = _native_confidence(rec)
                src = PPBSource(
                    model=ModelName.ochem_ppb, field=key, native_scale=SCALE_PCT_BOUND,
                    transform="pct / 100", raw_value=float(raw), fraction_bound=pct_to_fraction_bound(float(raw)),
                    confidence=conf, ad_in_domain=ad, primary=True,
                )
                _range_note(src)
                sources.append(src)

        elif rec.model == ModelName.admet_ai:
            if ev.get(ADMET_AI_KEY) is not None:
                raw = float(ev[ADMET_AI_KEY])  # type: ignore[arg-type]
                src = PPBSource(
                    model=ModelName.admet_ai, field=ADMET_AI_KEY, native_scale=SCALE_PCT_BOUND,
                    transform="pct / 100", raw_value=raw, fraction_bound=pct_to_fraction_bound(raw),
                )
                _range_note(src)
                sources.append(src)

        elif rec.model == ModelName.opera:
            hit = _first_present(ev, OPERA_FUB_KEYS)
            if hit is not None:
                key, raw = hit
                conf, ad = _native_confidence(rec)
                src = PPBSource(
                    model=ModelName.opera, field=key, native_scale=SCALE_FRACTION_UNBOUND,
                    transform="1 - FuB", raw_value=float(raw), fraction_bound=fub_to_fraction_bound(float(raw)),
                    confidence=conf, ad_in_domain=ad,
                )
                _range_note(src)
                sources.append(src)
        # any other model in the record set is not a ppb source -> ignored

    return sources


def _molecule_read(mol_id: str, records: Sequence[OutputRecord]) -> MoleculePPB:
    """Build one molecule's ppb read: normalize each source, take the mean consensus, flag the spread."""
    sources = _sources_for_molecule(records)
    notes: list[str] = []

    if not sources:
        return MoleculePPB(
            mol_id=mol_id,
            consensus=None,
            spread_flag=NA,
            confident=False,
            notes=["no ppb source (OCHEM PPB / ADMET-AI PPBR_AZ / OPERA FuB) present."],
        )

    values = [s.fraction_bound for s in sources]
    consensus = float(statistics.fmean(values))

    if len(values) > 1:
        spread_range: float | None = float(max(values) - min(values))
        spread_std: float | None = float(statistics.stdev(values))
        if spread_range <= SPREAD_RANGE_TRUST:
            spread_flag = LOW
            confident = True
            notes.append(
                f"sources converge (range {spread_range:.3f} <= {SPREAD_RANGE_TRUST} fraction units): "
                "the consensus is trustworthy."
            )
        else:
            spread_flag = HIGH
            confident = False
            notes.append(
                f"sources diverge (range {spread_range:.3f} > {SPREAD_RANGE_TRUST} fraction units): the "
                "mean is reported but SOFT; all per-source values are surfaced, not fused away."
            )
    else:
        spread_range = None
        spread_std = None
        spread_flag = NA
        confident = False
        notes.append(
            "only one ppb source present: a single tool is acceptable (not a gate), but with no "
            "cross-check the consensus carries no spread-based confidence."
        )

    notes.append(
        "each source is normalized on its OWN scale before averaging (OCHEM/ADMET-AI % -> /100; OPERA "
        "FuB -> 1 - FuB); no %/fraction value is ever averaged with an unconverted one (F-7)."
    )

    return MoleculePPB(
        mol_id=mol_id,
        consensus=consensus,
        sources=sources,
        n_sources=len(sources),
        spread_range=spread_range,
        spread_std=spread_std,
        spread_flag=spread_flag,
        confident=confident,
        notes=notes,
    )


def _normalize_molecules(
    molecules: Mapping[str, Sequence[Any]] | Sequence[Any],
) -> list[tuple[str, list[Any]]]:
    """Normalize the accepted input shapes to ``[(mol_id, records), ...]`` (same contract as the siblings).

    Accepts: a Mapping ``{mol_id: records}``; a sequence of ``(mol_id, records)`` pairs; a sequence of
    dicts ``{"mol_id"|"id": ..., "records": [...]}``; or a bare sequence of record-lists (id defaults to a
    positional ``mol_<i>``). A record-list is never mistaken for an ``(id, records)`` pair because a
    pair's first element is a ``str`` while a record-list's first element is a record/dict.
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
    """Harmonize the ppb sources onto a fraction-bound consensus per molecule, spread carried as confidence.

    ``molecules`` is the compound set (see ``_normalize_molecules`` for the accepted shapes); each
    molecule's bundle is a list of its model ``OutputRecord``s. For each molecule every present source
    (OCHEM % bound, ADMET-AI PPBR_AZ % bound, OPERA FuB fraction UNBOUND) is normalized onto fraction
    bound on its OWN scale - the OPERA inversion (1 - FuB) and the %/fraction split are the F-7 landmine
    handled in the per-scale normalizers - then averaged into a consensus. The cross-source spread is
    reported alongside as the confidence signal (convergence = trust); a wide spread flips ``confident``
    off but the mean and all per-source values are still surfaced, never fused away. Any subset of the
    three sources is tolerated (not a gate).
    """
    norm = _normalize_molecules(molecules)
    mols = [_molecule_read(mid, [_as_output_record(r) for r in raw_recs]) for mid, raw_recs in norm]

    return EndpointResult(
        molecules=mols,
        n_molecules=len(mols),
        notes=[
            "common quantity = fraction bound (0-1), UP = more bound; consensus = mean of the present "
            "sources after each is normalized on its own scale.",
            "OPERA emits FRACTION UNBOUND (FuB): it is inverted (1 - FuB) before entering the consensus; a "
            "missed inversion or a %/fraction mixup silently corrupts the number (IO_SPEC §3 F-7).",
            "spread across sources is the confidence signal: convergence -> trust; divergence -> the mean "
            "is reported but flagged soft, with every per-source value kept visible (no fused-away number).",
            "not a gate (PPB is a modulator): any subset of the three sources is accepted.",
        ],
        deferred=[
            "F-7: the OCHEM response UNIT (fraction vs %) and its JSON field name are UNVERIFIED pending a "
            "live docs.ochem.eu / t36-adapter read. This aggregator follows the t45 brief (OCHEM emits % "
            "-> /100) and reads the % field from a candidate-key set; reconcile the exact key + unit with "
            "the live t36 adapter. Divergences are flagged per-source, never silently reinterpreted.",
            "spread -> calibrated confidence is DEFERRED (AD/calibration policy); the SPREAD_RANGE_TRUST "
            "threshold here is a documented heuristic, not a calibrated cut.",
        ],
    )
