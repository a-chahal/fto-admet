#!/usr/bin/env python
"""metabolism aggregator - three separate features: hepatocyte CLint, microsomal CLint, site-of-metabolism.

The metabolism endpoint answers TWO different questions kept completely separate (F-2, CLAUDE.md §4):

    feature              sources                                   scale / status
    -------              -------                                   --------------
    hepatocyte_clint     admet_ai Clearance_Hepatocyte_AZ          uL/min/10^6 cells (single source,
                                                                   low-weight/qualitative F-17)
    microsomal_clint     admet_ai Clearance_Microsome_AZ           uL/min/mg (single source, low-weight
                                                                   F-17). Kept SEPARATE from hepatocyte -
                                                                   different unit/matrix, never combined.
    site_of_metabolism   fame3r max_som_probability (scored),      max per-atom P(SoM), [0,1] (up = labile).
                         smartcyp top_som_score (concordance)      SMARTCyp Score is a different kJ/mol
                                                                   scale (lower = SoM), carried as an
                                                                   un-fused concordance read (value=None).

The load-bearing science is F-2: SMARTCyp ``Score`` (lower = SoM, kJ/mol energy scale) and FAME3R
probability (higher = SoM, 0-1) run in OPPOSITE directions on INCOMPATIBLE scales, so they must NEVER be
averaged. The site-of-metabolism feature is therefore scored on the FAME3R probability alone (a single
numeric source); SMARTCyp's top-atom Score is carried as a Source with ``value=None`` (visible, never
folded into the score). The per-atom tables each model ships stay in that model's own ``rec.raw`` - they
are not copied here. Everything else - the shared shape, the ensemble mean/std for the single-source
features - is the ``core.aggregate`` contract. See ``docs/ENDPOINTS.md`` for the fuller rationale.
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
ADMET_AI_HEPATOCYTE = "Clearance_Hepatocyte_AZ"   # uL/min/10^6 cells
ADMET_AI_MICROSOME = "Clearance_Microsome_AZ"     # uL/min/mg
FAME3R_MAX_PROB = "max_som_probability"           # [0,1], higher = more labile atom
FAME3R_TOP_ATOM = "top_som_atom_index"
SMARTCYP_TOP_SCORE = "top_som_score"              # kJ/mol scale, LOWER = more likely SoM
SMARTCYP_TOP_ATOM = "top_som_atom_index"

HEPATOCYTE = "hepatocyte_clint"
MICROSOME = "microsomal_clint"
SOM = "site_of_metabolism"

HEPATOCYTE_UNIT = "uL/min/10^6 cells (up = faster clearance / less stable)"
MICROSOME_UNIT = "uL/min/mg (up = faster clearance)"
SOM_UNIT = "max per-atom P(SoM) [0,1] (up = more labile)"
QUALITATIVE_NOTE = "low-weight/qualitative (F-17)"
SMARTCYP_SCORE_UNIT = "kJ/mol SMARTCyp Score"


def _as_output_record(rec: Any) -> OutputRecord:
    return rec if isinstance(rec, OutputRecord) else OutputRecord.model_validate(rec)


def _num(value: Any) -> float | None:
    """Coerce to a finite float, or ``None`` (a source with no numeric value never enters the mean)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _single_source_feature(
    records: Sequence[OutputRecord], model: ModelName, key: str, name: str, unit: str, note: str,
) -> Feature:
    """A single-source CLint feature: one model's value, ``score = value``, ``uncertainty = None``."""
    sources: list[Source] = []
    for rec in records:
        if rec.model == model:
            v = _num((rec.endpoint_values or {}).get(key))
            if v is not None:
                sources.append(Source(model=model.value, value=v, note=note))
    score, uncertainty = ensemble([s.value for s in sources], [s.weight for s in sources])
    return Feature(feature=name, score=score, uncertainty=uncertainty, unit=unit,
                   n_sources=len(sources), sources=sources)


def _som_feature(records: Sequence[OutputRecord]) -> Feature:
    """Site of metabolism: FAME3R max probability is scored; SMARTCyp top Score is carried, NOT fused (F-2).

    FAME3R's ``max_som_probability`` is the only numeric source (the score). SMARTCyp's ``top_som_score``
    is on a different kJ/mol scale running the opposite direction, so it joins as a concordance Source with
    ``value=None`` (its native Score in ``raw``) and is never averaged into the probability. The per-atom
    tables stay in each model's ``rec.raw``.
    """
    sources: list[Source] = []
    for rec in records:
        ev = rec.endpoint_values or {}
        if rec.model == ModelName.fame3r:
            prob = _num(ev.get(FAME3R_MAX_PROB))
            if prob is not None:
                sources.append(Source(
                    model="fame3r", value=prob,
                    note=f"max per-atom P(SoM); top atom idx={ev.get(FAME3R_TOP_ATOM)}",
                ))
        elif rec.model == ModelName.smartcyp:
            score = _num(ev.get(SMARTCYP_TOP_SCORE))
            if score is not None:
                sources.append(Source(
                    model="smartcyp", value=None, raw=score, raw_unit=SMARTCYP_SCORE_UNIT,
                    note=(f"SMARTCyp top SoM atom idx={ev.get(SMARTCYP_TOP_ATOM)}; lower Score = more "
                          "likely SoM (different scale, not fused)"),
                ))
    score, uncertainty = ensemble([s.value for s in sources], [s.weight for s in sources])
    return Feature(feature=SOM, score=score, uncertainty=uncertainty, unit=SOM_UNIT,
                   n_sources=len(sources), sources=sources)


def _molecule(mol_id: str, records: Sequence[Any]) -> MoleculeVerdict:
    recs = [_as_output_record(r) for r in records]
    features = [
        _single_source_feature(recs, ModelName.admet_ai, ADMET_AI_HEPATOCYTE, HEPATOCYTE,
                               HEPATOCYTE_UNIT, QUALITATIVE_NOTE),
        _single_source_feature(recs, ModelName.admet_ai, ADMET_AI_MICROSOME, MICROSOME,
                               MICROSOME_UNIT, QUALITATIVE_NOTE),
        _som_feature(recs),
    ]
    return MoleculeVerdict(endpoint=Endpoint.metabolism, mol_id=mol_id, features=features)


def aggregate(molecules: Mapping[str, Sequence[Any]] | Sequence[Any]) -> EndpointVerdict:
    """Screen metabolism for a batch: hepatocyte CLint + microsomal CLint + site-of-metabolism per molecule.

    The two CLint features are kept SEPARATE (different units/matrices, never combined, F-3/F-17). The
    site-of-metabolism feature is scored on the FAME3R probability alone; SMARTCyp's Score is carried as an
    un-fused concordance read (opposite direction, incompatible scale, F-2).
    """
    mols = [_molecule(mid, recs) for mid, recs in normalize_molecules(molecules)]
    return EndpointVerdict(endpoint=Endpoint.metabolism, molecules=mols, n_molecules=len(mols))
