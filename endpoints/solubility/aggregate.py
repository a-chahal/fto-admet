#!/usr/bin/env python
"""solubility aggregator - two SEPARATE single-source entities: aqueous solubility and formulation risk.

The endpoint holds TWO distinct entities that must never be fused (the landmine, F-4-style):

    feature              source                          scale / direction
    -------              ------                          -----------------
    aqueous_solubility   admet_ai Solubility_AqSolDB      thermodynamic log S, up = more soluble
    formulation_risk     sfi SFI                          Solubility Forecast Index, down = lower risk

The load-bearing point of this file: SFI and log S are DIFFERENT entities on unrelated scales pointing in
OPPOSITE directions (SFI lower = better; log S higher = better). They are NOT averaged, co-ranked, or
otherwise combined - each is carried as its own single-source feature with its own native direction spelled
out in the unit string. Averaging them (or negating SFI to fuse it into a logS scale) would be wrong.
Everything else - each ``score`` is the single native value, ``uncertainty`` is None (one source) - is the
shared shape from ``core.aggregate``. See ``docs/ENDPOINTS.md`` for the fuller rationale.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from core.aggregate import (
    EndpointVerdict,
    Feature,
    MoleculeVerdict,
    Source,
    normalize_molecules,
)
from core.fusion import fuse
from core.models import Endpoint, ModelName
from core.schemas import OutputRecord

# The ONLY native keys this aggregator reads, per model (verified against the adapters).
ADMET_AI_KEY = "Solubility_AqSolDB"    # admet_ai: thermodynamic aqueous solubility, log(mol/L), up = more soluble
SFI_KEY = "SFI"                        # sfi: Solubility Forecast Index, down = more soluble / lower risk

AQUEOUS = "aqueous_solubility"
FORMULATION = "formulation_risk"


def _as_output_record(rec: Any) -> OutputRecord:
    return rec if isinstance(rec, OutputRecord) else OutputRecord.model_validate(rec)


def _num(value: Any) -> float | None:
    """Coerce to a finite float, or ``None`` (a source with no numeric value never enters the mean)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _aqueous_feature(records: Sequence[OutputRecord]) -> Feature:
    """Thermodynamic aqueous solubility (log S) from the generalist; single source."""
    sources: list[Source] = []
    for rec in records:
        if rec.model == ModelName.admet_ai:
            v = _num((rec.endpoint_values or {}).get(ADMET_AI_KEY))
            if v is not None:
                sources.append(Source(model="admet_ai", value=v, note="AqSolDB log S (up = more soluble)"))
    score, uncertainty = fuse(Endpoint.solubility, AQUEOUS, sources)   # trained spec if present, else equal-weight
    return Feature(feature=AQUEOUS, score=score, uncertainty=uncertainty,
                   unit="log(mol/L) (up = more soluble)", n_sources=len(sources), sources=sources)


def _formulation_feature(records: Sequence[OutputRecord]) -> Feature:
    """Solubility Forecast Index - a DIFFERENT entity from log S; single source, never fused."""
    sources: list[Source] = []
    for rec in records:
        if rec.model == ModelName.sfi:
            v = _num((rec.endpoint_values or {}).get(SFI_KEY))
            if v is not None:
                sources.append(Source(model="sfi", value=v,
                                      note="different entity from thermodynamic solubility; not fused with logS"))
    score, uncertainty = fuse(Endpoint.solubility, FORMULATION, sources)   # untrained -> equal-weight fallback
    return Feature(feature=FORMULATION, score=score, uncertainty=uncertainty,
                   unit="Solubility Forecast Index (down = more soluble / lower formulation risk)",
                   n_sources=len(sources), sources=sources)


def _molecule(mol_id: str, records: Sequence[Any]) -> MoleculeVerdict:
    recs = [_as_output_record(r) for r in records]
    features = [_aqueous_feature(recs), _formulation_feature(recs)]
    return MoleculeVerdict(endpoint=Endpoint.solubility, mol_id=mol_id, features=features)


def aggregate(molecules: Mapping[str, Sequence[Any]] | Sequence[Any]) -> EndpointVerdict:
    """Screen solubility for a batch: aqueous solubility (log S) + formulation risk (SFI), kept separate."""
    mols = [_molecule(mid, recs) for mid, recs in normalize_molecules(molecules)]
    return EndpointVerdict(endpoint=Endpoint.solubility, molecules=mols, n_molecules=len(mols))
