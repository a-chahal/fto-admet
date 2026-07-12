#!/usr/bin/env python
"""structural_alerts aggregator - deterministic per-catalog alert COUNTS as soft look-closer features.

Three single-source count features, each a plain integer tally from one model (no ensemble, no fusion):

    feature   source                     native key                  meaning
    -------   ------                     ----------                  -------
    pains     pains_brenk (t17)          endpoint_values.PAINS_count  # of PAINS substructure matches
    brenk     pains_brenk (t17)          endpoint_values.BRENK_count  # of BRENK substructure matches
    nih       pains_brenk (t17)          endpoint_values.NIH_count    # of NIH/MLSMR substructure matches

These are DETERMINISTIC counts, not predictions: there is no real uncertainty over a substructure tally, so
``uncertainty`` is always ``None``. Counts are NEVER ensembled across models (a count from one filter set is
not commensurable with a count from another), so each feature carries exactly one source and its score is
that source's count. The named matches that back each pains_brenk count live in the model's own
``rec.raw["<CAT>_matches"]`` (a list of ``{name, atoms}``); those names are summarized into the Source
``note`` (``raw`` stays scalar, never a list per the shared shape).

LANDMINE (CLAUDE.md §4, IO_SPEC §1 #24, task t47): this is a SOFT signal that OVER-flags. A non-zero count
means "look closer", it is NEVER an auto-kill. It matters here because the FTO assay is fluorescence-based
and PAINS is enriched for assay-interfering (fluorescent / redox-cycling) scaffolds, so a PAINS hit on an
FTO-series member is a prompt to check the readout for interference, not a disqualification. This aggregator
emits counts and NOTHING that reads as a pass/fail gate; the consuming decision policy is downstream and out
of scope. See ``docs/ENDPOINTS.md`` for the fuller rationale.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from core.aggregate import (
    EndpointVerdict,
    Feature,
    MoleculeVerdict,
    Source,
    ensemble,
    normalize_molecules,
)
from core.models import Endpoint, ModelName
from core.schemas import OutputRecord

# Feature names (constants for the tests to bind to).
PAINS = "pains"
BRENK = "brenk"
NIH = "nih"

# The ONLY native keys this aggregator reads, per model (verified against the adapters).
PAINS_COUNT_KEY = "PAINS_count"        # pains_brenk: int count of PAINS matches
BRENK_COUNT_KEY = "BRENK_count"        # pains_brenk: int count of BRENK matches
NIH_COUNT_KEY = "NIH_count"            # pains_brenk: int count of NIH/MLSMR matches
PAINS_MATCHES_KEY = "PAINS_matches"    # pains_brenk raw: [{name, atoms}, ...] backing the PAINS count
BRENK_MATCHES_KEY = "BRENK_matches"    # pains_brenk raw: [{name, atoms}, ...] backing the BRENK count
NIH_MATCHES_KEY = "NIH_matches"        # pains_brenk raw: [{name, atoms}, ...] backing the NIH count


def _as_output_record(rec: Any) -> OutputRecord:
    return rec if isinstance(rec, OutputRecord) else OutputRecord.model_validate(rec)


def _num(value: Any) -> float | None:
    """Coerce to a finite float, or ``None`` (a source with no numeric count is simply dropped)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _match_names(rec: OutputRecord, matches_key: str) -> str | None:
    """Join the ``name`` of each match dict in ``rec.raw[matches_key]`` into a note string, else ``None``.

    The per-match list (names + matched atoms) stays in the model's own ``rec.raw``; only a joined summary of
    the names lands in the Source ``note`` (``raw`` is a scalar and never carries a list).
    """
    items = (rec.raw or {}).get(matches_key)
    if not isinstance(items, (list, tuple)):
        return None
    names = [str(e["name"]) for e in items if isinstance(e, Mapping) and e.get("name")]
    return ", ".join(names) if names else None


def _count_feature(
    records: Sequence[OutputRecord],
    *,
    model: ModelName,
    key: str,
    feature: str,
    unit: str,
    matches_key: str | None = None,
) -> Feature:
    """One single-source count feature: the tally from ``model``'s ``key``, uncertainty always ``None``.

    Counts are deterministic and never ensembled across models, so the feature carries exactly one source
    (the ``model``'s count) and its score is that count. When ``matches_key`` is given, the backing match
    names from ``rec.raw`` are summarized into the Source ``note``.
    """
    sources: list[Source] = []
    for rec in records:
        if rec.model != model:
            continue
        count = _num((rec.endpoint_values or {}).get(key))
        if count is None:
            continue
        note: str | None = None
        if matches_key is not None:
            names = _match_names(rec, matches_key)
            note = f"matched: {names}" if names else "no named matches"
        sources.append(Source(model=model.value, value=count, note=note))
    # Single deterministic count: ensemble over the lone value gives the count; uncertainty is not meaningful.
    score, _ = ensemble([s.value for s in sources], [s.weight for s in sources])
    return Feature(feature=feature, score=score, uncertainty=None, unit=unit,
                   n_sources=len(sources), sources=sources)


def _molecule(mol_id: str, records: Sequence[Any]) -> MoleculeVerdict:
    recs = [_as_output_record(r) for r in records]
    features = [
        _count_feature(recs, model=ModelName.pains_brenk, key=PAINS_COUNT_KEY, feature=PAINS,
                       unit="count of PAINS matches (0 = clean)", matches_key=PAINS_MATCHES_KEY),
        _count_feature(recs, model=ModelName.pains_brenk, key=BRENK_COUNT_KEY, feature=BRENK,
                       unit="count of BRENK matches (0 = clean)", matches_key=BRENK_MATCHES_KEY),
        _count_feature(recs, model=ModelName.pains_brenk, key=NIH_COUNT_KEY, feature=NIH,
                       unit="count of NIH/MLSMR matches (0 = clean)", matches_key=NIH_MATCHES_KEY),
    ]
    return MoleculeVerdict(endpoint=Endpoint.structural_alerts, mol_id=mol_id, features=features)


def aggregate(molecules: Mapping[str, Sequence[Any]] | Sequence[Any]) -> EndpointVerdict:
    """Screen structural alerts for a batch: deterministic pains / brenk / nih counts (soft look-closer flags)."""
    mols = [_molecule(mid, recs) for mid, recs in normalize_molecules(molecules)]
    return EndpointVerdict(endpoint=Endpoint.structural_alerts, molecules=mols, n_molecules=len(mols))
