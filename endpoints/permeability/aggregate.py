#!/usr/bin/env python
"""permeability aggregator - three separate entities: passive permeability, intestinal absorption, P-gp efflux.

This endpoint has NO model of its own (no ``ModelName`` maps to it, IO_SPEC §2 "permeability
(aggregate-only)"). It runs in the core env (no box, no GPU) and consumes fields already emitted by the
cross-cutting generalists plus the BOILED-Egg HIA boolean. It holds THREE distinct entities that must
never be averaged together:

    feature                 sources                                     scale / status
    -------                 -------                                     --------------
    passive_permeability    admet_ai Caco2_Wang (log Papp),             TWO incompatible scales measuring ONE
                            admet_ai PAMPA_NCATS (probability)          entity (does it cross a membrane). No
                                                                        clean common axis -> score DEFERRED
                                                                        (None); the reads live upstream in the
                                                                        admet_ai record, pending calibration.
    intestinal_absorption   admet_ai HIA_Hou (probability),             ONE entity (does it get absorbed
                            boiled_egg HIA_boiled_egg (bool)            orally) on a probability + a boolean.
                                                                        No clean common axis -> score DEFERRED
                                                                        (None).
    pgp_efflux              admet_ai Pgp_Broccatelli via pgp.py         efflux liability, a DIFFERENT axis
                                                                        (F-4) -> single-source scored value.

Why the first two features carry no score yet: Caco2 log Papp (a log-scale flux) and PAMPA (a trained
probability) both predict passive membrane permeability, but on scales with no scientifically clean
common axis; the same holds for HIA_Hou (a probability) and BOILED-Egg (a boolean) on absorption.
Averaging either pair would need an arbitrary rescale, so - per the "score only clean fusions" policy -
the fused score is DEFERRED until each source is calibrated to a shared experimental target. Each source
is gathered with ``value=None`` so ``build_feature`` yields ``score=None`` (no fabricated mean of
incompatible scales). P-gp efflux is a third separate entity (F-4). This whole endpoint may be partly moot
for FTO-43 if delivery is intratumoral / osmotic-pump rather than oral (IO_SPEC §1 #23); it is a triage
read, not a gate.
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
from endpoints.distribution.pgp.pgp import extract_pgp

# The ONLY native keys this aggregator reads (verified against the adapters).
CACO2_KEY = "Caco2_Wang"                # admet_ai: Caco-2 permeability, log Papp (cm/s), up = more permeable
PAMPA_KEY = "PAMPA_NCATS"               # admet_ai: P(PAMPA-permeable), [0,1]
HIA_HOU_KEY = "HIA_Hou"                 # admet_ai: P(human intestinal absorption), [0,1]
HIA_BOILED_EGG_KEY = "HIA_boiled_egg"   # boiled_egg: bool (in the white / GI-absorption region)
# Pgp_Broccatelli (efflux) is read through the shared pgp helper, not by a literal key here.

PASSIVE = "passive_permeability"
ABSORPTION = "intestinal_absorption"
EFFLUX = "pgp_efflux"


def _passive_feature(records: Sequence[OutputRecord]) -> Feature:
    """Passive permeability: Caco2 log Papp + PAMPA probability, one entity, score DEFERRED (mixed axis).

    Both reads are gathered as ``value=None`` sources so no arbitrary mean of the two incompatible scales
    is fabricated; ``build_feature`` yields ``score=None`` until the sources are calibrated.
    """
    sources: list[Source] = []
    for rec in records:
        if rec.model != ModelName.admet_ai:
            continue
        ev = rec.endpoint_values or {}
        if num(ev.get(CACO2_KEY)) is not None:
            sources.append(Source(model="admet_ai", value=None))
        if num(ev.get(PAMPA_KEY)) is not None:
            sources.append(Source(model="admet_ai", value=None))
    return build_feature(Endpoint.permeability, PASSIVE, None, sources)


def _absorption_feature(records: Sequence[OutputRecord]) -> Feature:
    """Intestinal absorption: HIA_Hou probability + BOILED-Egg boolean, one entity, score DEFERRED (mixed axis).

    Both reads are gathered as ``value=None`` sources (probability + boolean have no clean common axis), so
    ``build_feature`` yields ``score=None`` until calibration.
    """
    sources: list[Source] = []
    for rec in records:
        ev = rec.endpoint_values or {}
        if rec.model == ModelName.admet_ai:
            if num(ev.get(HIA_HOU_KEY)) is not None:
                sources.append(Source(model="admet_ai", value=None))
        elif rec.model == ModelName.boiled_egg:
            if isinstance(ev.get(HIA_BOILED_EGG_KEY), bool):
                sources.append(Source(model="boiled_egg", value=None))
    return build_feature(Endpoint.permeability, ABSORPTION, None, sources)


def _efflux_feature(records: Sequence[OutputRecord]) -> Feature:
    """P-gp efflux liability, derived from the generalist's Pgp_Broccatelli head (F-4, separate entity)."""
    sources: list[Source] = []
    for rec in records:
        pgp = extract_pgp(rec)
        if pgp.value is not None:
            sources.append(Source(model=pgp.source_model or "admet_ai", value=pgp.value))
    return build_feature(Endpoint.permeability, EFFLUX,
                         "P(P-gp substrate) [0,1] (up = more efflux liability)", sources)


def _molecule(mol_id: str, records: Sequence[Any]) -> MoleculeVerdict:
    recs = [as_output_record(r) for r in records]
    features = [_passive_feature(recs), _absorption_feature(recs), _efflux_feature(recs)]
    return MoleculeVerdict(endpoint=Endpoint.permeability, mol_id=mol_id, features=features)


def aggregate(molecules: Mapping[str, Sequence[Any]] | Sequence[Any]) -> EndpointVerdict:
    """Screen permeability for a batch: passive permeability + intestinal absorption (both score deferred) + P-gp efflux."""
    mols = [_molecule(mid, recs) for mid, recs in normalize_molecules(molecules)]
    return EndpointVerdict(endpoint=Endpoint.permeability, molecules=mols, n_molecules=len(mols))
