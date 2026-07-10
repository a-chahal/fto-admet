#!/usr/bin/env python
"""synthesizability aggregator - two separate single-source features on two different entities.

Synthesizability holds two DISTINCT entities that must never share a feature (different questions,
different scales, different directions):

    feature                model     native key   scale / direction
    -------                -----     ----------   -----------------
    synthetic_complexity   sascore   SAscore      1-10, LOWER = easier to synthesize (INVERTED)
    route_findability      rascore   RAscore      0-1,  HIGHER = a synthetic route is more likely findable

``synthetic_complexity`` is a fast heuristic on structural complexity (Ertl & Schuffenhauer 2009);
``route_findability`` is a machine-learned "second opinion" on whether a retrosynthetic route exists.
They answer different things, so they are two separate single-source features, never averaged into one
number. Each is carried in the shared shape from ``core.aggregate``: a single source -> ``ensemble``
returns ``(value, None)`` (no spread from one read). The SAscore direction (LOWER = easier) is not
transformed here; it is recorded in the unit string so the reader keeps the inversion straight.
See ``docs/ENDPOINTS.md`` for the fuller rationale.
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

# The ONLY native keys this aggregator reads, per model (verified against the adapters).
SASCORE_KEY = "SAscore"   # sascore: float 1-10, LOWER = easier to synthesize (Ertl & Schuffenhauer 2009)
RASCORE_KEY = "RAscore"   # rascore: float 0-1, HIGHER = a synthetic route is more likely findable

COMPLEXITY = "synthetic_complexity"
FINDABILITY = "route_findability"


def _as_output_record(rec: Any) -> OutputRecord:
    return rec if isinstance(rec, OutputRecord) else OutputRecord.model_validate(rec)


def _num(value: Any) -> float | None:
    """Coerce to a finite float, or ``None`` (a source with no numeric value never enters the feature)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _complexity_feature(records: Sequence[OutputRecord]) -> Feature:
    """Synthetic complexity from SAscore (single source; LOWER = easier, recorded in the unit)."""
    sources: list[Source] = []
    for rec in records:
        if rec.model == ModelName.sascore:
            v = _num((rec.endpoint_values or {}).get(SASCORE_KEY))
            if v is not None:
                sources.append(Source(model="sascore", value=v, note="SAscore; lower = easier to synthesize"))
    score, uncertainty = ensemble([s.value for s in sources], [s.weight for s in sources])
    return Feature(feature=COMPLEXITY, score=score, uncertainty=uncertainty,
                   unit="SAscore 1-10 (down = easier to synthesize)",
                   n_sources=len(sources), sources=sources)


def _findability_feature(records: Sequence[OutputRecord]) -> Feature:
    """Route findability from RAscore (single source; a DIFFERENT entity from SAscore complexity)."""
    sources: list[Source] = []
    for rec in records:
        if rec.model == ModelName.rascore:
            v = _num((rec.endpoint_values or {}).get(RASCORE_KEY))
            if v is not None:
                sources.append(Source(model="rascore", value=v,
                                      note="different entity from SAscore complexity"))
    score, uncertainty = ensemble([s.value for s in sources], [s.weight for s in sources])
    return Feature(feature=FINDABILITY, score=score, uncertainty=uncertainty,
                   unit="P(retrosynthesis route exists) [0,1] (up = easier)",
                   n_sources=len(sources), sources=sources)


def _molecule(mol_id: str, records: Sequence[Any]) -> MoleculeVerdict:
    recs = [_as_output_record(r) for r in records]
    features = [_complexity_feature(recs), _findability_feature(recs)]
    return MoleculeVerdict(endpoint=Endpoint.synthesizability, mol_id=mol_id, features=features)


def aggregate(molecules: Mapping[str, Sequence[Any]] | Sequence[Any]) -> EndpointVerdict:
    """Screen synthesizability for a batch: synthetic_complexity + route_findability, two separate entities."""
    mols = [_molecule(mid, recs) for mid, recs in normalize_molecules(molecules)]
    return EndpointVerdict(endpoint=Endpoint.synthesizability, molecules=mols, n_molecules=len(mols))
