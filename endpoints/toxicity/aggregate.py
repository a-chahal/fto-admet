#!/usr/bin/env python
"""toxicity aggregator - a BULK substitute panel and a ProTox confirmatory shortlist, KEPT SEPARATE.

Contract (task t49, CLAUDE.md §2/§4, IO_SPEC §2 "toxicity", §3 F-5): this endpoint reports toxicity in
TWO tiers that are emitted as SEPARATE blocks and never merged:

- **Bulk (automatable, coverage/throughput):** the per-endpoint P(toxic) panel built from the classifier
  heads that run in the bulk loop -
    ADMET-AI  DILI / hERG / AMES / Carcinogens_Lagunin / ClinTox / Skin_Reaction  (P(toxic) in [0,1]),
    ADMET-AI  LD50_Zhu                                                            (a MAGNITUDE, not a P),
    ADMETlab  organ-tox heads: nephro / neuro / cyto / immuno / genotox           (P(toxic) in [0,1]),
    toxicophores  BRENK structural-alert hit / count                             (a soft alert flag).
- **Shortlist (confirmatory, richer):** the ProTox 3.0 web read [t39 SOP ledger] -
    LD50 (mg/kg), toxicity class (1-6), and per-endpoint Active/Inactive + probability.

Why two tiers and not one number (task t49, IO_SPEC §2):
- The bulk panel is a COVERAGE / THROUGHPUT substitute, not a quality-equivalence claim. The
  off-target / MIE / respiratory / eco / nutritional ProTox endpoints have NO automatable counterpart,
  so ProTox is the confirmatory read on the shortlist, not a per-molecule bulk column. ``bulk`` therefore
  carries ``is_quality_equivalent = False``.

LANDMINE F-5 (CLAUDE.md §4, IO_SPEC §3 F-5, task t49) - the reason these two blocks are structurally
separate:

  ADMET-AI ``LD50_Zhu`` is ``log(1/(mol/kg))`` with UP = MORE toxic.
  ProTox   ``LD50``     is ``mg/kg``           with LOWER = MORE toxic.

  Different scale AND opposite direction. They are NOT comparable and MUST NOT be merged or converted
  into one another. In this aggregator ``LD50_Zhu`` lives ONLY in ``bulk.magnitude_reads`` (tagged
  ``comparable_to_protox_ld50 = False``) and ProTox ``LD50`` lives ONLY in ``shortlist.ld50_mg_kg``.
  There is no code path, and no output field, that reads or combines both.

NEEDS_AARAN / placeholder note (IO_SPEC §1 #10/#11, F-6): the LITERAL ADMETlab 3.0 CSV column names for
the five organ-tox heads are 5 of the 119 columns that need a single live ``/api/admetCSV`` call to
capture. The keys in ``_ADMETLAB_PROB_HEADS`` are DOCUMENTED PLACEHOLDERS, not verified literals. The
aggregation logic and the canonical endpoint labels are final; when the admetlab3 adapter (t35) captures
the real header, swap only the placeholder KEYS. See the TODO on that constant.

This aggregator runs in the core env (no box, no GPU) and consumes fields already emitted by the
contributing models, identified by ``rec.model`` (the registry primary key), never by folder. It emits a
panel of reads; it carries NO pass/fail verdict. The consuming decision policy is downstream and out of
scope (CLAUDE.md §4a).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.models import Endpoint, ModelName
from core.schemas import OutputRecord

# ---------------------------------------------------------------------------------------------------
# Source maps: which emitted key on which model feeds which canonical toxicity endpoint.
# ---------------------------------------------------------------------------------------------------

# ADMET-AI classification heads whose output is DIRECTLY P(toxic) in [0, 1] (P of the named positive
# class, IO_SPEC §1 #8). Key = the ADMET-AI (TDC) head name in ``endpoint_values``; value = the canonical
# toxicity endpoint label the panel groups on.
_ADMET_AI_PROB_HEADS: dict[str, str] = {
    "DILI": "hepatotoxicity_dili",
    "hERG": "herg_blockade",
    "AMES": "mutagenicity_ames",
    "Carcinogens_Lagunin": "carcinogenicity",
    "ClinTox": "clinical_toxicity",
    "Skin_Reaction": "skin_reaction",
}

# ADMETlab 3.0 organ-tox heads → canonical endpoint. LANDMINE / NEEDS_AARAN (IO_SPEC §1 #10/#11, F-6):
# these KEYS are DOCUMENTED PLACEHOLDERS. The literal ADMETlab CSV column names are 5 of the 119 columns
# that require ONE live ``/api/admetCSV`` call to capture (the admetlab3 adapter task, t35). Do NOT treat
# these key strings as verified literals; when t35 captures the real header, swap the keys here. The
# canonical endpoint labels (the values) and the aggregation logic are final and do not change.
# TODO(t35 / NEEDS_AARAN): replace the placeholder keys below with the real ADMETlab CSV column names.
_ADMETLAB_PROB_HEADS: dict[str, str] = {
    "nephrotoxicity": "nephrotoxicity",
    "neurotoxicity": "neurotoxicity",
    "cytotoxicity": "cytotoxicity",
    "immunotoxicity": "immunotoxicity",
    "genotoxicity": "genotoxicity",
}

# Per-model probability-head maps, keyed by the model that emits them.
_PROB_HEADS: dict[ModelName, dict[str, str]] = {
    ModelName.admet_ai: _ADMET_AI_PROB_HEADS,
    ModelName.admetlab3: _ADMETLAB_PROB_HEADS,
}

# ADMET-AI MAGNITUDE heads: NOT probabilities. Kept as their own scalar read, never folded into a
# P(toxic) and (F-5) never comparable to ProTox LD50. Value = (canonical label, unit, direction).
_ADMET_AI_MAGNITUDE_HEADS: dict[str, tuple[str, str, str]] = {
    "LD50_Zhu": ("acute_oral_ld50_zhu", "log(1/(mol/kg))", "up = more toxic"),
}
_MAGNITUDE_HEADS: dict[ModelName, dict[str, tuple[str, str, str]]] = {
    ModelName.admet_ai: _ADMET_AI_MAGNITUDE_HEADS,
}

# toxicophores (t18) emits these in ``endpoint_values`` (+ matched names in ``raw.tox_alert_names``).
_TOX_ALERT_HIT_KEY = "tox_alert_hit"
_TOX_ALERT_COUNT_KEY = "tox_alert_count"
_TOX_ALERT_CATALOG_KEY = "catalog"
_TOX_ALERT_NAMES_KEY = "tox_alert_names"

# ProTox (t39 SOP) scalar reads. Read from ``endpoint_values`` first, then ``raw`` (the SOP transcription
# shape nests scalars under ``raw.predictions``), so both a flat and a nested record are accepted.
_PROTOX_LD50_KEYS = ("LD50", "ld50", "LD50_mg_kg")
_PROTOX_CLASS_KEYS = ("tox_class", "toxicity_class", "class")
_PROTOX_ACCURACY_KEYS = ("prediction_accuracy", "accuracy")


def _as_output_record(rec: Any) -> OutputRecord:
    """Coerce a dict (or an already-built ``OutputRecord``) into an ``OutputRecord`` for uniform access."""
    if isinstance(rec, OutputRecord):
        return rec
    return OutputRecord.model_validate(rec)


# ---------------------------------------------------------------------------------------------------
# Output schema. The aggregator owns its own result shape (an aggregator task may not touch ``core``).
# ---------------------------------------------------------------------------------------------------


class BulkContribution(BaseModel):
    """One model's P(toxic) for a bulk endpoint. Grouped with the other models on the same endpoint."""

    model_config = ConfigDict(extra="forbid")

    model: ModelName
    p_toxic: float = Field(ge=0.0, le=1.0)  # P of the toxic/positive class, in [0, 1]


class BulkEndpoint(BaseModel):
    """One bulk toxicity endpoint's per-endpoint P(toxic): the contributing model probabilities + their mean.

    ``p_toxic`` is the mean of ``contributions`` - a defensible consensus BECAUSE every contribution is
    already a probability of the SAME toxic class on the SAME [0,1] scale (unlike the cross-scale reads in
    distribution / permeability, nothing here is averaged across incompatible units). Provenance is kept:
    ``contributions`` lists each model's value so the mean is auditable, not a black box.
    """

    model_config = ConfigDict(extra="forbid")

    endpoint: str
    kind: str = "probability"
    contributions: list[BulkContribution]
    p_toxic: float = Field(ge=0.0, le=1.0)


class MagnitudeRead(BaseModel):
    """A NON-probability toxicity scalar (ADMET-AI ``LD50_Zhu``). Kept as its own read, never a P(toxic).

    F-5 landmine made structural: ``comparable_to_protox_ld50`` is ALWAYS False. ``LD50_Zhu``
    (log(1/(mol/kg)), up = more toxic) is on a different scale and opposite direction to ProTox ``LD50``
    (mg/kg, lower = more toxic); this field exists so a downstream reader can never mistake one for the
    other or average them.
    """

    model_config = ConfigDict(extra="forbid")

    endpoint: str
    model: ModelName
    value: float
    unit: str
    direction: str
    comparable_to_protox_ld50: bool = False


class AlertSignal(BaseModel):
    """A structural-alert read (toxicophores, BRENK): a soft over-flag, not a probability and not a kill."""

    model_config = ConfigDict(extra="forbid")

    model: ModelName
    catalog: str | None = None
    hit: bool | None = None
    count: int | None = None
    names: list[str] = Field(default_factory=list)
    soft_flag: bool = True  # over-flags; a hit means look-closer, NEVER an auto-kill (IO_SPEC §28).


class BulkPanel(BaseModel):
    """The bulk-substitute block: per-endpoint P(toxic) + magnitude reads + alert signals, all automatable.

    ``is_quality_equivalent`` is False on purpose (task t49): the bulk panel is a coverage/throughput
    substitute. Several ProTox endpoints (off-target / MIE / respiratory / eco / nutritional) have no
    automatable counterpart, so bulk coverage does not equal ProTox-quality coverage.
    """

    model_config = ConfigDict(extra="forbid")

    tier: str = "bulk"
    probability_panel: list[BulkEndpoint] = Field(default_factory=list)
    magnitude_reads: list[MagnitudeRead] = Field(default_factory=list)
    alerts: list[AlertSignal] = Field(default_factory=list)
    is_quality_equivalent: bool = False
    notes: list[str] = Field(default_factory=list)


class ProToxEndpointCall(BaseModel):
    """One ProTox per-endpoint prediction: an Active/Inactive call + its probability (verbatim)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    call: str | None = None  # "Active" (toxic) / "Inactive"
    probability: float | None = None


class ProToxShortlist(BaseModel):
    """The ProTox 3.0 confirmatory read for a shortlisted molecule (t39 SOP). SEPARATE from the bulk panel.

    ``ld50_mg_kg`` is ProTox's LD50 in mg/kg (LOWER = more toxic). It has a DIFFERENT field name, unit,
    and direction from the bulk ``LD50_Zhu`` magnitude read - see F-5. The two never share a field.
    """

    model_config = ConfigDict(extra="forbid")

    tier: str = "shortlist"
    model: ModelName = ModelName.protox
    ld50_mg_kg: float | None = None  # mg/kg, LOWER = more toxic (NOT comparable to bulk LD50_Zhu, F-5)
    ld50_unit: str = "mg/kg"
    ld50_direction: str = "lower = more toxic"
    tox_class: int | None = None  # acute oral tox class 1-6 (1 = most toxic, 6 = least)
    prediction_accuracy: float | None = None  # ProTox's reported per-prediction confidence (percent)
    endpoints: list[ProToxEndpointCall] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class MoleculeToxicity(BaseModel):
    """One molecule's toxicity read: the bulk panel and the ProTox shortlist, as two SEPARATE blocks."""

    model_config = ConfigDict(extra="forbid")

    mol_id: str
    bulk: BulkPanel
    shortlist: ProToxShortlist | None = None
    notes: list[str] = Field(default_factory=list)


class EndpointResult(BaseModel):
    """The toxicity result: per molecule, a bulk-substitute panel and a ProTox confirmatory shortlist.

    Deliberately carries NO merged toxicity scalar and NO pass/fail verdict. The two tiers stay separate
    (F-5); the output is a set of reads, and the consuming decision policy is downstream (CLAUDE.md §4a).
    """

    model_config = ConfigDict(extra="forbid")

    endpoint: Endpoint = Endpoint.toxicity
    quantity: str = (
        "toxicity in two SEPARATE tiers: a bulk-substitute per-endpoint P(toxic) panel (ADMET-AI + "
        "ADMETlab organ-tox heads + toxicophores alerts) and a ProTox confirmatory shortlist (LD50 mg/kg, "
        "class 1-6, per-endpoint Active/Inactive + prob). ADMET-AI LD50_Zhu (log 1/(mol/kg), up=toxic) is "
        "NEVER merged with ProTox LD50 (mg/kg, lower=toxic) - different scale and opposite direction (F-5)."
    )
    molecules: list[MoleculeToxicity]
    n_molecules: int
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------------------------------
# Readers.
# ---------------------------------------------------------------------------------------------------


def _coerce_prob(value: Any) -> float | None:
    """Coerce a value to a probability in [0, 1]; return None (skip, never fabricate) if it cannot be."""
    if value is None or isinstance(value, bool):
        return None
    try:
        p = float(value)
    except (TypeError, ValueError):
        return None
    if p < 0.0 or p > 1.0:
        return None
    return p


def _coerce_float(value: Any) -> float | None:
    """Coerce a value to a float; return None if it cannot be (a bool is not a numeric read here)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_present(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    """Return the value of the first key present with a non-None value, else None."""
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _bulk_panel(records: Sequence[OutputRecord]) -> BulkPanel:
    """Build the bulk-substitute block: per-endpoint P(toxic) + magnitude reads + toxicophores alerts."""
    # endpoint label -> [(model, p_toxic), ...], preserving discovery order of endpoints.
    prob_groups: dict[str, list[tuple[ModelName, float]]] = {}
    magnitude_reads: list[MagnitudeRead] = []
    alerts: list[AlertSignal] = []

    for rec in records:
        ev = rec.endpoint_values or {}

        # Probability heads (ADMET-AI classifiers + ADMETlab organ-tox), grouped by canonical endpoint.
        for src_key, endpoint in _PROB_HEADS.get(rec.model, {}).items():
            p = _coerce_prob(ev.get(src_key))
            if p is None:
                continue
            prob_groups.setdefault(endpoint, []).append((rec.model, p))

        # Magnitude heads (ADMET-AI LD50_Zhu): a scalar read, NEVER a probability, NEVER merged (F-5).
        for src_key, (label, unit, direction) in _MAGNITUDE_HEADS.get(rec.model, {}).items():
            v = _coerce_float(ev.get(src_key))
            if v is None:
                continue
            magnitude_reads.append(
                MagnitudeRead(
                    endpoint=label,
                    model=rec.model,
                    value=v,
                    unit=unit,
                    direction=direction,
                    comparable_to_protox_ld50=False,
                )
            )

        # toxicophores structural-alert read (soft flag).
        if rec.model == ModelName.toxicophores:
            hit = ev.get(_TOX_ALERT_HIT_KEY)
            count = ev.get(_TOX_ALERT_COUNT_KEY)
            names = rec.raw.get(_TOX_ALERT_NAMES_KEY) if isinstance(rec.raw, Mapping) else None
            alerts.append(
                AlertSignal(
                    model=rec.model,
                    catalog=ev.get(_TOX_ALERT_CATALOG_KEY),
                    hit=hit if isinstance(hit, bool) else None,
                    count=int(count) if isinstance(count, int) and not isinstance(count, bool) else None,
                    names=list(names) if isinstance(names, (list, tuple)) else [],
                )
            )

    probability_panel = [
        BulkEndpoint(
            endpoint=endpoint,
            contributions=[BulkContribution(model=m, p_toxic=p) for m, p in group],
            p_toxic=sum(p for _, p in group) / len(group),
        )
        for endpoint, group in prob_groups.items()
    ]

    notes = [
        "bulk = automatable COVERAGE/THROUGHPUT substitute, NOT a quality-equivalence claim "
        "(is_quality_equivalent=False): the off-target/MIE/respiratory/eco/nutritional ProTox endpoints "
        "have no automatable counterpart (shortlist only).",
        "per-endpoint P(toxic) is the mean of same-endpoint, same-scale [0,1] probabilities; LD50_Zhu is "
        "a MAGNITUDE (log 1/(mol/kg)) kept out of every probability and NOT comparable to ProTox LD50 "
        "(mg/kg) - F-5; toxicophores is a SOFT alert flag, not a probability and not a kill.",
    ]
    if any(rec.model == ModelName.admetlab3 for rec in records):
        notes.append(
            "ADMETlab organ-tox head keys are PLACEHOLDERS: the literal CSV column names need one live "
            "/api/admetCSV call (NEEDS_AARAN, t35 / F-6); the aggregation and endpoint labels are final."
        )

    return BulkPanel(
        probability_panel=probability_panel,
        magnitude_reads=magnitude_reads,
        alerts=alerts,
        notes=notes,
    )


def _protox_endpoints(raw: Mapping[str, Any]) -> list[ProToxEndpointCall]:
    """Read ProTox per-endpoint Active/Inactive calls from ``raw.endpoints`` or ``raw.predictions.endpoints``."""
    endpoints_map: Any = raw.get("endpoints")
    if endpoints_map is None:
        preds = raw.get("predictions")
        if isinstance(preds, Mapping):
            endpoints_map = preds.get("endpoints")
    if not isinstance(endpoints_map, Mapping):
        return []
    out: list[ProToxEndpointCall] = []
    for name, entry in endpoints_map.items():
        if isinstance(entry, Mapping):
            out.append(
                ProToxEndpointCall(
                    name=str(name),
                    call=entry.get("call"),
                    probability=_coerce_prob(entry.get("probability")),
                )
            )
    return out


def _protox_shortlist(records: Sequence[OutputRecord]) -> ProToxShortlist | None:
    """Build the ProTox confirmatory shortlist from any ``protox`` record; None if the molecule has none."""
    protox = next((rec for rec in records if rec.model == ModelName.protox), None)
    if protox is None:
        return None

    ev = protox.endpoint_values or {}
    raw = protox.raw if isinstance(protox.raw, Mapping) else {}
    # SOP transcription nests scalars under raw.predictions; accept either a flat or nested record.
    nested = raw.get("predictions") if isinstance(raw.get("predictions"), Mapping) else {}

    def _scalar(keys: Sequence[str]) -> Any:
        v = _first_present(ev, keys)
        if v is not None:
            return v
        v = _first_present(raw, keys)
        if v is not None:
            return v
        return _first_present(nested, keys) if isinstance(nested, Mapping) else None

    ld50_raw = _scalar(_PROTOX_LD50_KEYS)
    class_raw = _scalar(_PROTOX_CLASS_KEYS)
    accuracy_raw = _scalar(_PROTOX_ACCURACY_KEYS)

    ld50 = _coerce_float(ld50_raw.get("value") if isinstance(ld50_raw, Mapping) else ld50_raw)
    class_val = class_raw.get("value") if isinstance(class_raw, Mapping) else class_raw
    tox_class = int(class_val) if isinstance(class_val, (int, float)) and not isinstance(class_val, bool) else None
    accuracy = _coerce_float(accuracy_raw.get("value") if isinstance(accuracy_raw, Mapping) else accuracy_raw)

    endpoints = _protox_endpoints(nested if isinstance(nested, Mapping) and "endpoints" in nested else raw)

    return ProToxShortlist(
        ld50_mg_kg=ld50,
        tox_class=tox_class,
        prediction_accuracy=accuracy,
        endpoints=endpoints,
        notes=[
            "ProTox is the CONFIRMATORY shortlist read (web SOP, t39): richer than bulk and the only "
            "source for off-target/MIE/respiratory/eco/nutritional tox.",
            "ld50_mg_kg (mg/kg, lower=toxic) is NOT comparable to bulk LD50_Zhu (log 1/(mol/kg), up=toxic) "
            "- different scale and opposite direction (F-5); the two are never merged.",
        ],
    )


def _molecule_toxicity(mol_id: str, records: Sequence[OutputRecord]) -> MoleculeToxicity:
    """Build one molecule's two-tier read: the bulk panel and the ProTox shortlist, kept separate."""
    return MoleculeToxicity(
        mol_id=mol_id,
        bulk=_bulk_panel(records),
        shortlist=_protox_shortlist(records),
        notes=[
            "two SEPARATE tiers: bulk-substitute panel (automatable) and ProTox confirmatory shortlist. "
            "There is NO merged toxicity scalar and NO path that combines LD50_Zhu with ProTox LD50 (F-5)."
        ],
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
    """Emit, per molecule, a bulk-substitute P(toxic) panel and a ProTox confirmatory shortlist, KEPT SEPARATE.

    ``molecules`` is the compound set (see ``_normalize_molecules`` for the accepted shapes); each molecule's
    bundle is a list of its model ``OutputRecord``s. The bulk panel is built from the automatable heads
    (ADMET-AI + ADMETlab organ-tox + toxicophores); the shortlist is the ProTox web read. ADMET-AI
    ``LD50_Zhu`` and ProTox ``LD50`` are structurally separate and are NEVER merged or converted (F-5).
    """
    norm = _normalize_molecules(molecules)
    mols = [_molecule_toxicity(mid, [_as_output_record(r) for r in raw_recs]) for mid, raw_recs in norm]

    return EndpointResult(
        molecules=mols,
        n_molecules=len(mols),
        notes=[
            "toxicity is reported in TWO SEPARATE tiers: a bulk-substitute per-endpoint P(toxic) panel "
            "(automatable coverage/throughput) and a ProTox confirmatory shortlist (the richer read).",
            "F-5 landmine: ADMET-AI LD50_Zhu (log 1/(mol/kg), up=toxic) is NOT comparable to ProTox LD50 "
            "(mg/kg, lower=toxic) - different scale AND opposite direction; they are kept as separate "
            "reads and there is no path that merges or converts one into the other.",
        ],
    )
