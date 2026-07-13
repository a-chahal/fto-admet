#!/usr/bin/env python
"""metabolism aggregator - one feature: site-of-metabolism (WHERE the CYP soft spot is).

Metabolism answers exactly one question the other endpoints do not: *which atom* is metabolized. The
"how fast is it metabolized" question is hepatic intrinsic clearance - the SAME quantity the clearance
endpoint already owns (``clearance/hepatocyte_clint`` = OPERA Clint + ADMET-AI, and
``clearance/microsomal_clint``). Reporting those CLint numbers here too would duplicate one value across
two endpoints, so they are NOT read here: metabolism is purely site-of-metabolism, clearance owns CLint.

    feature              sources                                   scale / status
    -------              -------                                   --------------
    site_of_metabolism   fame3r max_som_probability (scored),      max per-atom P(SoM), [0,1] (up = labile).
                         smartcyp top_som_score (concordance)      SMARTCyp Score is a different kJ/mol
                                                                   scale (lower = SoM), carried un-fused.

The load-bearing science is F-2: SMARTCyp ``Score`` (lower = SoM, kJ/mol energy scale) and FAME3R
probability (higher = SoM, 0-1) run in OPPOSITE directions on INCOMPATIBLE scales, so they must NEVER be
averaged. The feature is therefore scored on the FAME3R probability alone (a single numeric source);
SMARTCyp's top-atom Score is carried as a Source with ``value=None`` (visible, never folded into the
score). The per-atom tables each model ships stay in that model's own ``rec.raw`` - they are not copied
here. Everything else is the ``core.aggregate`` contract. See ``docs/ENDPOINTS.md`` for the rationale.
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

# The ONLY native keys this aggregator reads, per model (verified against the adapters).
FAME3R_MAX_PROB = "max_som_probability"           # [0,1], higher = more labile atom
FAME3R_TOP_ATOM = "top_som_atom_index"
SMARTCYP_TOP_SCORE = "top_som_score"              # kJ/mol scale, LOWER = more likely SoM
SMARTCYP_TOP_ATOM = "top_som_atom_index"

SOM = "site_of_metabolism"
SOM_UNIT = "max per-atom P(SoM) [0,1] (up = more labile)"
SMARTCYP_SCORE_UNIT = "kJ/mol SMARTCyp Score"


def _som_feature(records: Sequence[OutputRecord]) -> Feature:
    """Site of metabolism: FAME3R max probability is scored; SMARTCyp top Score is carried, NOT fused (F-2).

    FAME3R's ``max_som_probability`` is the only numeric source (the score); it carries its native AD
    reliability (``ad_index`` + mean FAME3RScore) in ``native``. SMARTCyp's ``top_som_score`` is on a
    different kJ/mol scale running the opposite direction, so it joins as a concordance Source with
    ``value=None`` (its native Score in ``raw``) and is never averaged into the probability. The per-atom
    tables stay in each model's ``rec.raw``.
    """
    sources: list[Source] = []
    for rec in records:
        ev = rec.endpoint_values or {}
        if rec.model == ModelName.fame3r:
            prob = num(ev.get(FAME3R_MAX_PROB))
            if prob is not None:
                u = rec.uncertainty
                native = ({"ad_index": u.ad_index,
                           "fame3r_score_mean": (u.extra or {}).get("fame3r_score_mean")} if u else {})
                sources.append(Source(model="fame3r", value=prob, native=native))
        elif rec.model == ModelName.smartcyp:
            score = num(ev.get(SMARTCYP_TOP_SCORE))
            if score is not None:
                sources.append(Source(model="smartcyp", value=None, raw=score,
                                      raw_unit=SMARTCYP_SCORE_UNIT))
    return build_feature(Endpoint.metabolism, SOM, SOM_UNIT, sources)


def _molecule(mol_id: str, records: Sequence[Any]) -> MoleculeVerdict:
    recs = [as_output_record(r) for r in records]
    return MoleculeVerdict(endpoint=Endpoint.metabolism, mol_id=mol_id, features=[_som_feature(recs)])


def aggregate(molecules: Mapping[str, Sequence[Any]] | Sequence[Any]) -> EndpointVerdict:
    """Screen metabolism for a batch: one site-of-metabolism feature per molecule.

    Scored on the FAME3R probability alone; SMARTCyp's Score is carried as an un-fused concordance read
    (opposite direction, incompatible scale, F-2). Hepatic clearance (metabolic stability) is NOT reported
    here - it is the clearance endpoint's ``hepatocyte_clint`` / ``microsomal_clint``, not duplicated.
    """
    mols = [_molecule(mid, recs) for mid, recs in normalize_molecules(molecules)]
    return EndpointVerdict(endpoint=Endpoint.metabolism, molecules=mols, n_molecules=len(mols))
