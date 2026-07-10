#!/usr/bin/env python
"""druglikeness aggregator - three separate single-source context features (NEVER a gate).

The endpoint surfaces three drug-likeness context flags, each a SEPARATE single-source feature keyed
exactly as the ``lipinski_veber_qed`` model (t19) emits them - they are never combined, thresholded, or
turned into a pass/fail verdict:

    feature               source key            scale / direction
    -------               ----------            -----------------
    lipinski_violations   Lipinski_violations   Ro5 violation count 0-4 (down = more druglike)
    veber_pass            Veber_pass            boolean (True = passes Veber; not a mean -> score None)
    qed                   QED                   [0,1] desirability (up = more druglike)

LANDMINE (task t50, IO_SPEC §30): drug-likeness is CONTEXT read by the lab, never an advance/kill
decision. So this aggregator does no gate math - no threshold, no consensus, no promote/reject scalar.
Each feature carries its single native read; ``lipinski_violations`` and ``qed`` are numeric so the
single-source ensemble mean fills ``score``, while ``veber_pass`` is a boolean and keeps ``score=None``
(a boolean has no mean). Everything else is the shared shape from ``core.aggregate``. See
``docs/ENDPOINTS.md`` for the fuller rationale.
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

# The three context keys this aggregator reads, keyed exactly as lipinski_veber_qed (t19) writes them.
LIPINSKI_KEY = "Lipinski_violations"   # int 0-4; fewer violations = more drug-like (Lipinski 2001)
VEBER_KEY = "Veber_pass"               # bool; pass = more drug-like (Veber 2002)
QED_KEY = "QED"                        # float 0-1; higher = more drug-like (Bickerton et al. 2012)

LIPINSKI = "lipinski_violations"
VEBER = "veber_pass"
QED = "qed"


def _as_output_record(rec: Any) -> OutputRecord:
    return rec if isinstance(rec, OutputRecord) else OutputRecord.model_validate(rec)


def _num(value: Any) -> float | None:
    """Coerce to a finite float, or ``None``. Rejects bool (a flag is not a measurement)."""
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _lipinski_feature(records: Sequence[OutputRecord]) -> Feature:
    """Ro5 violation count - single numeric source (score = the value, uncertainty None)."""
    sources: list[Source] = []
    for rec in records:
        if rec.model == ModelName.lipinski_veber_qed:
            v = _num((rec.endpoint_values or {}).get(LIPINSKI_KEY))
            if v is not None:
                sources.append(Source(model="lipinski_veber_qed", value=v,
                                      note="Lipinski Ro5 violation count"))
    score, uncertainty = ensemble([s.value for s in sources], [s.weight for s in sources])
    return Feature(feature=LIPINSKI, score=score, uncertainty=uncertainty,
                   unit="Ro5 violations 0-4 (down = more druglike)",
                   n_sources=len(sources), sources=sources)


def _veber_feature(records: Sequence[OutputRecord]) -> Feature:
    """Veber pass - a single boolean source; score DEFERRED (a boolean has no mean)."""
    sources: list[Source] = []
    for rec in records:
        if rec.model == ModelName.lipinski_veber_qed:
            b = (rec.endpoint_values or {}).get(VEBER_KEY)
            if isinstance(b, bool):
                sources.append(Source(model="lipinski_veber_qed", value=b,
                                      note="passes Veber rotatable-bond / TPSA rules (True = pass)"))
    return Feature(feature=VEBER, score=None, uncertainty=None,
                   unit="boolean (True = passes Veber)", n_sources=len(sources), sources=sources)


def _qed_feature(records: Sequence[OutputRecord]) -> Feature:
    """QED desirability - single numeric source (score = the value, uncertainty None)."""
    sources: list[Source] = []
    for rec in records:
        if rec.model == ModelName.lipinski_veber_qed:
            v = _num((rec.endpoint_values or {}).get(QED_KEY))
            if v is not None:
                sources.append(Source(model="lipinski_veber_qed", value=v, note="QED desirability"))
    score, uncertainty = ensemble([s.value for s in sources], [s.weight for s in sources])
    return Feature(feature=QED, score=score, uncertainty=uncertainty,
                   unit="QED [0,1] (up = more druglike)", n_sources=len(sources), sources=sources)


def _molecule(mol_id: str, records: Sequence[Any]) -> MoleculeVerdict:
    recs = [_as_output_record(r) for r in records]
    features = [_lipinski_feature(recs), _veber_feature(recs), _qed_feature(recs)]
    return MoleculeVerdict(endpoint=Endpoint.druglikeness, mol_id=mol_id, features=features)


def aggregate(molecules: Mapping[str, Sequence[Any]] | Sequence[Any]) -> EndpointVerdict:
    """Screen druglikeness for a batch: Lipinski violations + Veber pass (score deferred) + QED, per molecule."""
    mols = [_molecule(mid, recs) for mid, recs in normalize_molecules(molecules)]
    return EndpointVerdict(endpoint=Endpoint.druglikeness, molecules=mols, n_molecules=len(mols))
