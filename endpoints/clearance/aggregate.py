#!/usr/bin/env python
"""clearance aggregator - three DECOMPOSED clearance features that are NEVER merged across units.

Clearance is the pipeline's weakest endpoint and the one place where a naive "combine the numbers" is
actively wrong. The clearance predictions live in different units and matrices, so the honest shared read
is NOT one number: it is three separately labeled features, each carrying its own unit string, kept apart
on purpose (F-3, CLAUDE.md §4):

    feature           sources                                    unit                     role
    -------           -------                                    ----                     ----
    hepatocyte_clint  opera Clint + admet_ai Clearance_          uL/min/10^6 cells        CLEAN 2-source
                      Hepatocyte_AZ (SAME units)                                          ensemble/fusion
    systemic_cl       pksmart CL_mL_min_kg (+ fold-error)        mL/min/kg                single-source, IV CL
    microsomal_clint  admet_ai Clearance_Microsome_AZ           uL/min/mg                single-source CLint

LANDMINE (the entire point of this file - F-3, CLAUDE.md §4): **NEVER combine clearance numbers across
units.** No mean, no sum, no ratio across the three features. They are different units AND different
matrices (hepatocyte CLint vs whole-body i.v. CL vs microsomal CLint), so any arithmetic across them is
meaningless. The renal-vs-hepatic fork is resolved by EXPERIMENT, not by the models.

The only within-feature fusion allowed is ``hepatocyte_clint``: OPERA ``Clint`` and ADMET-AI hepatocyte
clearance share the SAME assay units ("uL/min/10^6 cells"), so they form a clean same-scale ensemble.
``systemic_cl`` surfaces the PKSmart whole-body CL with its native fold-error carried in ``native`` (the
CL number is ranking-only, R^2=0.31, and never presented without its fold-error). ``microsomal_clint`` is
the ADMET-AI microsomal head, a different assay/unit, single-source. ``build_feature`` fuses each feature's
sources (trained spec if present, else equal-weight) and projects them into the flat output shape.

Everything else - the shared shape - is ``core.aggregate``. See ``docs/ENDPOINTS.md`` for the fuller
rationale.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from core.aggregate import (
    EndpointVerdict,
    Feature,
    MoleculeVerdict,
    Source,
    as_output_record,
    normalize_molecules,
    num,
)
from core.fusion import build_feature
from core.models import Endpoint, ModelName
from core.schemas import OutputRecord

# The ONLY native keys this aggregator reads, per model (verified against the adapters). Every value is
# routed into its own labeled feature and never combined with another across units.
OPERA_CLINT = "Clint"
ADMET_AI_HEPATOCYTE = "Clearance_Hepatocyte_AZ"
ADMET_AI_MICROSOME = "Clearance_Microsome_AZ"
PKSMART_CL = "CL_mL_min_kg"

HEPATOCYTE_CLINT = "hepatocyte_clint"
SYSTEMIC_CL = "systemic_cl"
MICROSOMAL_CLINT = "microsomal_clint"

HEPATOCYTE_CLINT_UNIT = "uL/min/10^6 cells (up = faster clearance)"
SYSTEMIC_CL_UNIT = "mL/min/kg (whole-body IV clearance, up = faster)"
MICROSOMAL_CLINT_UNIT = "uL/min/mg (up = faster clearance)"


def _hepatocyte_feature(records: Sequence[OutputRecord]) -> Feature:
    """Hepatocyte CLint: OPERA Clint + ADMET-AI hepatocyte clearance on the SAME units (clean ensemble)."""
    sources: list[Source] = []
    for rec in records:
        ev = rec.endpoint_values or {}
        u = rec.uncertainty
        if rec.model == ModelName.opera:
            v = num(ev.get(OPERA_CLINT))
            if v is not None:
                native = ({"conf_index": (u.extra or {}).get("Clint_conf_index"),
                           "ad_in_domain": (u.extra or {}).get("Clint_ad_in_domain")}
                          if u is not None else {})
                sources.append(Source(model="opera", value=v, native=native))
        elif rec.model == ModelName.admet_ai:
            v = num(ev.get(ADMET_AI_HEPATOCYTE))
            if v is not None:
                sources.append(Source(model="admet_ai", value=v))
    return build_feature(Endpoint.clearance, HEPATOCYTE_CLINT, HEPATOCYTE_CLINT_UNIT, sources)


def _systemic_feature(records: Sequence[OutputRecord]) -> Feature:
    """Systemic (whole-body i.v.) CL from PKSmart; single source, native fold-error carried in ``native``."""
    sources: list[Source] = []
    for rec in records:
        if rec.model != ModelName.pksmart:
            continue
        v = num((rec.endpoint_values or {}).get(PKSMART_CL))
        if v is None:
            continue
        u = rec.uncertainty
        native = ({"fold_error_low": u.fold_error_low, "fold_error_high": u.fold_error_high,
                   "ad_in_domain": u.ad_in_domain} if u is not None else {})
        sources.append(Source(model="pksmart", value=v, native=native))
    return build_feature(Endpoint.clearance, SYSTEMIC_CL, SYSTEMIC_CL_UNIT, sources)


def _microsomal_feature(records: Sequence[OutputRecord]) -> Feature:
    """Microsomal CLint from ADMET-AI; a different assay/unit from hepatocyte CLint, single source."""
    sources: list[Source] = []
    for rec in records:
        if rec.model != ModelName.admet_ai:
            continue
        v = num((rec.endpoint_values or {}).get(ADMET_AI_MICROSOME))
        if v is not None:
            sources.append(Source(model="admet_ai", value=v))
    return build_feature(Endpoint.clearance, MICROSOMAL_CLINT, MICROSOMAL_CLINT_UNIT, sources)


def _molecule(mol_id: str, records: Sequence[Any]) -> MoleculeVerdict:
    recs = [as_output_record(r) for r in records]
    features = [_hepatocyte_feature(recs), _systemic_feature(recs), _microsomal_feature(recs)]
    return MoleculeVerdict(endpoint=Endpoint.clearance, mol_id=mol_id, features=features)


def aggregate(molecules: Mapping[str, Sequence[Any]] | Sequence[Any]) -> EndpointVerdict:
    """Screen clearance for a batch: three DECOMPOSED features per molecule, never merged across units (F-3).

    ``hepatocyte_clint`` is a clean same-unit ensemble; ``systemic_cl`` and ``microsomal_clint`` are
    single-source reads on their own distinct units. No arithmetic ever crosses the three features.
    """
    mols = [_molecule(mid, recs) for mid, recs in normalize_molecules(molecules)]
    return EndpointVerdict(endpoint=Endpoint.clearance, molecules=mols, n_molecules=len(mols))
