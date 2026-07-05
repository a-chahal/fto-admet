#!/usr/bin/env python
"""structural_alerts aggregator - the UNION of PAINS / BRENK matches as a SOFT flag (look-closer, not a kill).

Contract (task t47, CLAUDE.md §2/§4, IO_SPEC §2 "structural_alerts", §1 #24): this endpoint collects the
substructure-alert screens and reports, per molecule, the *union* of every matched alert plus per-catalog
counts and a single ``any_hit`` boolean. It runs in the core env (no box, no GPU) and consumes fields
already emitted by the contributing models, selected by endpoint membership in the registry, never by
folder:

    model                  what it emits                                              shape
    -----                  -------------                                              -----
    pains_brenk (t17)      per-catalog matched-alert list + matched-atom substructure  raw.PAINS_matches /
                           + a count, for PAINS and BRENK                              raw.BRENK_matches =
                                                                                       [{name, atoms}, ...]
    admet_ai (generalist)  PAINS_alert / BRENK_alert / NIH_alert COUNT shortcuts       endpoint_values
                           (a count only - no matched-alert names)                     ...<CAT>_alert = int

Two shapes therefore feed in, and they are treated differently because they carry different information:

- **Named matches** (``raw.<CAT>_matches`` = a list of ``{name, atoms}``). These are the authoritative,
  auditable alerts: each one has a name (which published filter fired) and the matched-atom substructure.
  The union is taken over these, deduplicated by ``(catalog, name)``, tracking which models reported each
  alert and the union of the matched atoms. ``PAINS_count`` / ``BRENK_count`` are the number of DISTINCT
  named alerts per catalog in that union. This reader is model-agnostic: any record that emits alerts in
  the ``raw.<CAT>_matches`` shape (e.g. a future toxicophores screen, t18) is unioned in automatically -
  the catalog name is taken from the key prefix, so PAINS/BRENK are not special-cased in the reader.
- **Count shortcuts** (``endpoint_values.<CAT>_alert`` = an int, e.g. ADMET-AI's ``PAINS_alert`` /
  ``BRENK_alert`` / ``NIH_alert``). These carry a count but NO names, so they cannot join the named union
  (there is nothing to name or dedupe). They are surfaced separately as ``cross_check`` signals: they keep
  ADMET-AI's NIH count (which no named source provides) from being silently dropped, and they make a
  cross-model discrepancy visible (e.g. pains_brenk reports 0 named PAINS but ADMET-AI's shortcut says 2).
  A count shortcut > 0 still counts toward ``any_hit`` (it is a real alert even without a name).

LANDMINE (CLAUDE.md §4, IO_SPEC §1 #24, task t47): this is a **SOFT** filter that OVER-flags. A hit means
"look closer", it is NEVER an auto-kill. It matters specifically for this program because the FTO assay is
fluorescence-based and PAINS is enriched for assay-interfering (fluorescent / redox-cycling) scaffolds, so
a PAINS hit on an FTO-series member is a prompt to check the readout for interference, not a
disqualification. This aggregator therefore emits counts + the matched-alert list + a boolean flag and
NOTHING that reads as a pass/fail gate. The consuming decision policy is downstream and out of scope.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.models import Endpoint, ModelName
from core.schemas import OutputRecord

# Catalog labels. PAINS and BRENK are the two the task requires explicit counts for; the union itself is
# open to any catalog a contributing record names (see module docstring), so these are constants for the
# tests to bind to, not an exhaustive closed set.
PAINS = "PAINS"
BRENK = "BRENK"

# Suffix conventions the readers key off. Named matches arrive under ``raw.<CAT>_matches``; count-only
# shortcuts arrive under ``endpoint_values.<CAT>_alert``. The catalog label is the key prefix, upper-cased.
_MATCHES_SUFFIX = "_matches"
_ALERT_SUFFIX = "_alert"


def _as_output_record(rec: Any) -> OutputRecord:
    """Coerce a dict (or an already-built ``OutputRecord``) into an ``OutputRecord`` for uniform access."""
    if isinstance(rec, OutputRecord):
        return rec
    return OutputRecord.model_validate(rec)


class MatchedAlert(BaseModel):
    """One distinct alert in the union: a named filter that fired, with its provenance and substructure.

    Keyed by ``(catalog, name)`` in the union: if two models both report the same catalog+name alert, they
    collapse to ONE entry whose ``models`` lists both reporters and whose ``atoms`` is the union of the
    matched-atom indices each reported. ``atoms`` may be empty if a source reported a hit without atom
    indices; that is a valid, auditable state, not an error.
    """

    model_config = ConfigDict(extra="forbid")

    catalog: str                       # "PAINS" / "BRENK" / ... (from the record's key prefix)
    name: str                          # the published filter description that fired
    models: list[ModelName]            # which model(s) reported this alert (union provenance)
    atoms: list[int] = Field(default_factory=list)  # union of matched-atom indices across reporters


class CountSignal(BaseModel):
    """A count-only shortcut (e.g. ADMET-AI ``PAINS_alert`` / ``BRENK_alert`` / ``NIH_alert``): a number, no names.

    Surfaced apart from the named union because it cannot be deduplicated by name (there are none). It keeps
    counts a named source does not provide (ADMET-AI's NIH) visible, and exposes cross-model discrepancies.
    """

    model_config = ConfigDict(extra="forbid")

    model: ModelName
    catalog: str
    count: int


class MoleculeAlerts(BaseModel):
    """One molecule's structural-alert triage: the union of matched alerts + per-catalog counts + a flag.

    The required soft-flag payload (task t47): ``PAINS_count`` / ``BRENK_count`` (distinct named alerts per
    catalog in the union), ``matched`` (the union list), and ``any_hit`` (any named match OR any count
    shortcut > 0). ``counts`` generalizes the two required counts to every catalog present in the union.
    ``soft_flag`` is always True and ``is_gate`` always False: this is a look-closer flag, NEVER a kill.
    """

    model_config = ConfigDict(extra="forbid")

    mol_id: str
    PAINS_count: int = 0
    BRENK_count: int = 0
    counts: dict[str, int] = Field(default_factory=dict)
    matched: list[MatchedAlert] = Field(default_factory=list)
    any_hit: bool = False
    cross_check: list[CountSignal] = Field(default_factory=list)
    soft_flag: bool = True   # over-flags; a hit means look-closer (CLAUDE.md §4). Never a kill.
    is_gate: bool = False    # explicit: structural alerts do NOT gate/kill a molecule.
    notes: list[str] = Field(default_factory=list)


class EndpointResult(BaseModel):
    """The harmonized structural-alerts result: per-molecule union + counts + matched list + a soft flag.

    Deliberately carries NO pass/fail verdict: the output is a flag, not a gate. The aggregator owns its own
    result shape (an aggregator task may not touch ``core``).
    """

    model_config = ConfigDict(extra="forbid")

    endpoint: Endpoint = Endpoint.structural_alerts
    quantity: str = (
        "union of PAINS / BRENK structural-alert matches: per-catalog counts + the matched-alert list + an "
        "any_hit boolean. A SOFT flag (over-flags; look-closer, NOT an auto-kill), which matters here "
        "because the FTO assay is fluorescence-based and PAINS is enriched for assay-interfering scaffolds."
    )
    molecules: list[MoleculeAlerts]
    n_molecules: int
    notes: list[str] = Field(default_factory=list)


def _named_matches(rec: OutputRecord) -> list[tuple[str, str, list[int]]]:
    """Extract this record's named alerts as ``[(catalog, name, atoms), ...]`` from ``raw.<CAT>_matches``.

    Model-agnostic: any ``raw`` key ending in ``_matches`` whose value is a list of ``{name, atoms}`` dicts
    is read, with the catalog taken from the key prefix (``PAINS_matches`` -> ``PAINS``). A malformed entry
    (missing/empty name, non-list atoms) is skipped rather than raising, so one odd record cannot sink a batch.
    """
    out: list[tuple[str, str, list[int]]] = []
    raw = rec.raw or {}
    for key, value in raw.items():
        if not key.endswith(_MATCHES_SUFFIX) or not isinstance(value, (list, tuple)):
            continue
        catalog = key[: -len(_MATCHES_SUFFIX)].upper()
        for entry in value:
            if not isinstance(entry, Mapping):
                continue
            name = entry.get("name")
            if not name or not isinstance(name, str):
                continue
            raw_atoms = entry.get("atoms") or []
            atoms = [int(a) for a in raw_atoms] if isinstance(raw_atoms, (list, tuple)) else []
            out.append((catalog, name, atoms))
    return out


def _count_shortcuts(rec: OutputRecord) -> list[tuple[str, int]]:
    """Extract this record's count-only shortcuts as ``[(catalog, count), ...]`` from ``endpoint_values.<CAT>_alert``.

    E.g. ADMET-AI's ``PAINS_alert`` / ``BRENK_alert`` / ``NIH_alert``. A ``None`` or non-integer count is
    skipped. The catalog is the key prefix upper-cased (``NIH_alert`` -> ``NIH``).
    """
    out: list[tuple[str, int]] = []
    ev = rec.endpoint_values or {}
    for key, value in ev.items():
        if not key.endswith(_ALERT_SUFFIX) or value is None or isinstance(value, bool):
            continue
        try:
            count = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        out.append((key[: -len(_ALERT_SUFFIX)].upper(), count))
    return out


def _molecule_alerts(mol_id: str, records: Sequence[OutputRecord]) -> MoleculeAlerts:
    """Union the named alerts across a molecule's records; surface count-only shortcuts apart; emit the flag."""
    # Union of named alerts, keyed by (catalog, name). Values accumulate reporting models and matched atoms.
    union: dict[tuple[str, str], dict[str, Any]] = {}
    cross_check: list[CountSignal] = []

    for rec in records:
        for catalog, name, atoms in _named_matches(rec):
            slot = union.setdefault(
                (catalog, name), {"models": set(), "atoms": set()}
            )
            slot["models"].add(rec.model)
            slot["atoms"].update(atoms)
        for catalog, count in _count_shortcuts(rec):
            cross_check.append(CountSignal(model=rec.model, catalog=catalog, count=count))

    matched = [
        MatchedAlert(
            catalog=catalog,
            name=name,
            models=sorted(slot["models"]),
            atoms=sorted(slot["atoms"]),
        )
        for (catalog, name), slot in sorted(union.items())
    ]

    counts: dict[str, int] = {}
    for alert in matched:
        counts[alert.catalog] = counts.get(alert.catalog, 0) + 1

    # any_hit reflects a real alert from EITHER shape: a named match, or a count shortcut > 0 (a hit that
    # simply lacks a name). A soft flag stays soft - any_hit never becomes a kill.
    any_hit = bool(matched) or any(sig.count > 0 for sig in cross_check)

    notes = [
        "SOFT flag (CLAUDE.md §4): a hit means look-closer, NEVER an auto-kill; the FTO assay is "
        "fluorescence-based and PAINS is enriched for assay-interfering scaffolds, so a hit is a prompt "
        "to check the readout for interference, not a disqualification.",
        "the matched list is the UNION over the named-alert screens, deduplicated by (catalog, name); "
        "PAINS_count / BRENK_count are the distinct named alerts per catalog.",
    ]
    if cross_check:
        notes.append(
            "count-only shortcuts (e.g. ADMET-AI PAINS_alert / BRENK_alert / NIH_alert) carry a count but "
            "no names, so they are surfaced in cross_check apart from the named union; a discrepancy vs the "
            "named counts is a look-closer signal, not resolved here."
        )

    return MoleculeAlerts(
        mol_id=mol_id,
        PAINS_count=counts.get(PAINS, 0),
        BRENK_count=counts.get(BRENK, 0),
        counts=counts,
        matched=matched,
        any_hit=any_hit,
        cross_check=cross_check,
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
    """Emit, per molecule, the UNION of PAINS / BRENK matches as a soft flag: counts + matched list + any_hit.

    ``molecules`` is the compound set (see ``_normalize_molecules`` for the accepted shapes); each molecule's
    bundle is a list of its model ``OutputRecord``s. For each molecule the named alerts (``raw.<CAT>_matches``)
    are unioned and deduplicated by ``(catalog, name)``, count-only shortcuts (``endpoint_values.<CAT>_alert``)
    are surfaced apart as cross-checks, and the result is a SOFT flag (counts + matched list + ``any_hit``),
    NEVER a pass/fail gate (CLAUDE.md §4 landmine).
    """
    norm = _normalize_molecules(molecules)
    mols = [_molecule_alerts(mid, [_as_output_record(r) for r in raw_recs]) for mid, raw_recs in norm]

    return EndpointResult(
        molecules=mols,
        n_molecules=len(mols),
        notes=[
            "structural_alerts is the UNION of PAINS / BRENK matches: per-catalog counts + the matched-alert "
            "list + an any_hit boolean. It is a SOFT flag that OVER-flags (look-closer, NOT an auto-kill).",
            "the flag is especially a prompt-to-check here because the FTO assay is fluorescence-based and "
            "PAINS is enriched for assay-interfering scaffolds; the consuming decision policy is downstream.",
        ],
    )
