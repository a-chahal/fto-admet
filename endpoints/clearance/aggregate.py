#!/usr/bin/env python
"""clearance aggregator - three DECOMPOSED clearance features that are NEVER merged across units.

Clearance is the pipeline's weakest endpoint and the one place where a naive "combine the numbers" is
actively wrong. The clearance predictions live in different units and matrices, so the honest shared read
is NOT one number: it is three separately labeled features, each carrying its own unit string, kept apart
on purpose (F-3, CLAUDE.md §4):

    feature           sources                                    unit                     role
    -------           -------                                    ----                     ----
    hepatocyte_clint  opera Clint + admet_ai Clearance_          uL/min/10^6 cells        CLEAN 2-source
                      Hepatocyte_AZ (SAME units)                                          ensemble (mean/std)
    systemic_cl       pksmart CL_mL_min_kg (+ fold-error)        mL/min/kg                single-source, IV CL
    microsomal_clint  admet_ai Clearance_Microsome_AZ           uL/min/mg                single-source CLint

LANDMINE (the entire point of this file - F-3, CLAUDE.md §4): **NEVER combine clearance numbers across
units.** No mean, no sum, no ratio across the three features. They are different units AND different
matrices (hepatocyte CLint vs whole-body i.v. CL vs microsomal CLint), so any arithmetic across them is
meaningless. The renal-vs-hepatic fork is resolved by EXPERIMENT, not by the models.

The only within-feature fusion allowed is ``hepatocyte_clint``: OPERA ``Clint`` and ADMET-AI hepatocyte
clearance share the SAME assay units ("uL/min/10^6 cells"), so they form a clean same-scale ensemble
(score = mean, uncertainty = std). ``systemic_cl`` surfaces the PKSmart whole-body CL with its native
fold-error in the note (the CL number is ranking-only, R^2=0.31, and never presented without its
fold-error). ``microsomal_clint`` is the ADMET-AI microsomal head, a different assay/unit, single-source.

Everything else - the shared shape, the mean/std math - is ``core.aggregate``. See ``docs/ENDPOINTS.md``
for the fuller rationale.
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

# The ONLY native keys this aggregator reads, per model (verified against the adapters). Every value is
# routed into its own labeled feature and never combined with another across units.
OPERA_CLINT = "Clint"
ADMET_AI_HEPATOCYTE = "Clearance_Hepatocyte_AZ"
ADMET_AI_MICROSOME = "Clearance_Microsome_AZ"
PKSMART_CL = "CL_mL_min_kg"
PKSMART_FOLD_ERROR_KEY = "cl_fold_error"  # in pksmart uncertainty.extra (the CL fold factor)

HEPATOCYTE_CLINT = "hepatocyte_clint"
SYSTEMIC_CL = "systemic_cl"
MICROSOMAL_CLINT = "microsomal_clint"

HEPATOCYTE_CLINT_UNIT = "uL/min/10^6 cells (up = faster clearance)"
SYSTEMIC_CL_UNIT = "mL/min/kg (whole-body IV clearance, up = faster)"
MICROSOMAL_CLINT_UNIT = "uL/min/mg (up = faster clearance)"


def _as_output_record(rec: Any) -> OutputRecord:
    return rec if isinstance(rec, OutputRecord) else OutputRecord.model_validate(rec)


def _num(value: Any) -> float | None:
    """Coerce to a finite float, or ``None`` (a source with no numeric value never enters the mean)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _hepatocyte_feature(records: Sequence[OutputRecord]) -> Feature:
    """Hepatocyte CLint: OPERA Clint + ADMET-AI hepatocyte clearance on the SAME units (clean ensemble)."""
    sources: list[Source] = []
    for rec in records:
        ev = rec.endpoint_values or {}
        if rec.model == ModelName.opera:
            v = _num(ev.get(OPERA_CLINT))
            if v is not None:
                sources.append(Source(model="opera", value=v, note="OPERA Clint (uL/min/10^6 cells)"))
        elif rec.model == ModelName.admet_ai:
            v = _num(ev.get(ADMET_AI_HEPATOCYTE))
            if v is not None:
                sources.append(Source(model="admet_ai", value=v,
                                      note="ADMET-AI hepatocyte CLint (uL/min/10^6 cells); low-weight/qualitative (F-17)"))
    score, uncertainty = ensemble([s.value for s in sources], [s.weight for s in sources])
    return Feature(feature=HEPATOCYTE_CLINT, score=score, uncertainty=uncertainty,
                   unit=HEPATOCYTE_CLINT_UNIT, n_sources=len(sources), sources=sources)


def _systemic_feature(records: Sequence[OutputRecord]) -> Feature:
    """Systemic (whole-body i.v.) CL from PKSmart; single source, native fold-error carried in the note."""
    sources: list[Source] = []
    for rec in records:
        if rec.model != ModelName.pksmart:
            continue
        v = _num((rec.endpoint_values or {}).get(PKSMART_CL))
        if v is None:
            continue
        unc = rec.uncertainty
        low = unc.fold_error_low if unc is not None else None
        high = unc.fold_error_high if unc is not None else None
        cl_fold = (unc.extra or {}).get(PKSMART_FOLD_ERROR_KEY) if unc is not None else None
        note = f"fold-error low={low} high={high} cl_fold={cl_fold}"
        sources.append(Source(model="pksmart", value=v, note=note))
    score, uncertainty = ensemble([s.value for s in sources], [s.weight for s in sources])
    return Feature(feature=SYSTEMIC_CL, score=score, uncertainty=uncertainty,
                   unit=SYSTEMIC_CL_UNIT, n_sources=len(sources), sources=sources)


def _microsomal_feature(records: Sequence[OutputRecord]) -> Feature:
    """Microsomal CLint from ADMET-AI; a different assay/unit from hepatocyte CLint, single source."""
    sources: list[Source] = []
    for rec in records:
        if rec.model != ModelName.admet_ai:
            continue
        v = _num((rec.endpoint_values or {}).get(ADMET_AI_MICROSOME))
        if v is not None:
            sources.append(Source(model="admet_ai", value=v,
                                  note="ADMET-AI microsomal CLint (uL/min/mg); low-weight/qualitative (F-17)"))
    score, uncertainty = ensemble([s.value for s in sources], [s.weight for s in sources])
    return Feature(feature=MICROSOMAL_CLINT, score=score, uncertainty=uncertainty,
                   unit=MICROSOMAL_CLINT_UNIT, n_sources=len(sources), sources=sources)


def _molecule(mol_id: str, records: Sequence[Any]) -> MoleculeVerdict:
    recs = [_as_output_record(r) for r in records]
    features = [_hepatocyte_feature(recs), _systemic_feature(recs), _microsomal_feature(recs)]
    return MoleculeVerdict(endpoint=Endpoint.clearance, mol_id=mol_id, features=features)


def aggregate(molecules: Mapping[str, Sequence[Any]] | Sequence[Any]) -> EndpointVerdict:
    """Screen clearance for a batch: three DECOMPOSED features per molecule, never merged across units (F-3).

    ``hepatocyte_clint`` is a clean same-unit ensemble (score = mean, uncertainty = std); ``systemic_cl``
    and ``microsomal_clint`` are single-source reads on their own distinct units. No arithmetic ever
    crosses the three features.
    """
    mols = [_molecule(mid, recs) for mid, recs in normalize_molecules(molecules)]
    return EndpointVerdict(endpoint=Endpoint.clearance, molecules=mols, n_molecules=len(mols))
