#!/usr/bin/env python
"""distribution aggregator - three separate entities: passive BBB penetration, CNS druglikeness, P-gp efflux.

The endpoint holds THREE distinct entities that must never be averaged together (F-4):

    feature            sources                                     scale / status
    -------            -------                                     --------------
    bbb_penetration    bbb_score BBB_Score (0-6 desirability),     THREE incompatible scales measuring ONE
                       admet_ai BBB_Martins (probability),         entity (does it cross the BBB). The trained
                       boiled_egg BBB_boiled_egg (bool)            rule spec calibrates them onto log Kp,uu.
    cns_druglikeness   cns_mpo CNS_MPO (0-6 desirability)          a DIFFERENT entity (developability, not
                                                                   penetration) -> its own single-source value.
    pgp_efflux         admet_ai Pgp_Broccatelli via pgp.py         efflux liability (F-4, separate entity)
                                                                   -> single-source value.

``bbb_penetration`` is the mixed-scale feature: BBB_Score (0-6 desirability), BBB_Martins (a probability),
and boiled_egg (a boolean) all predict passive BBB penetration on incompatible scales. Rather than an
arbitrary average, the trained spec's per-source calibration maps each onto the shared experimental target
(log Kp,uu,brain), turning what used to be a DEFERRED (None) score into a real calibrated one; admet_ai's
BBB head is contaminated on the public Kp,uu set so it is carried but unweighted. CNS_MPO measures CNS
DRUGLIKENESS (developability), a different entity, so it is a separate feature, never folded into
penetration. P-gp efflux is a third separate entity. Out-of-band DruMAP signals (watanabe_pgp_brain Kp,uu /
NER) are transcribed by hand, not read here.
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
BBB_SCORE_KEY = "BBB_Score"            # bbb_score: 0-6 desirability, higher = more likely passive penetrant
CNS_MPO_KEY = "CNS_MPO"                # cns_mpo: 0-6 desirability, higher = more CNS-druglike (developability)
BBB_MARTINS_KEY = "BBB_Martins"        # admet_ai: P(BBB penetrant), [0,1]
BBB_BOILED_EGG_KEY = "BBB_boiled_egg"  # boiled_egg: bool (in the yolk / BBB region)

PENETRATION = "bbb_penetration"
DRUGLIKENESS = "cns_druglikeness"
EFFLUX = "pgp_efflux"


def _penetration_feature(records: Sequence[OutputRecord]) -> Feature:
    """Passive BBB penetration: three native reads on incompatible scales, fused by the trained rule spec.

    Mixed scales (0-6 rule + prob + 0/1 rule): the trained spec's per-source calibration is what makes them
    commensurable, turning the once-deferred score into a real calibrated log Kp,uu (admet_ai is contaminated
    on this set and not in the spec, so it is carried but unweighted). Falls back to None-yielding equal-weight
    only if the spec is absent (mixed scales have no meaningful equal-weight mean).
    """
    sources: list[Source] = []
    for rec in records:
        ev = rec.endpoint_values or {}
        if rec.model == ModelName.bbb_score:
            v = num(ev.get(BBB_SCORE_KEY))
            if v is not None:
                sources.append(Source(model="bbb_score", value=v))
        elif rec.model == ModelName.admet_ai:
            v = num(ev.get(BBB_MARTINS_KEY))
            if v is not None:
                sources.append(Source(model="admet_ai", value=v))
        elif rec.model == ModelName.boiled_egg:
            b = ev.get(BBB_BOILED_EGG_KEY)
            if isinstance(b, bool):
                sources.append(Source(model="boiled_egg", value=b))
    return build_feature(Endpoint.distribution, PENETRATION,
                         "log10 Kp,uu,brain (up = more brain-penetrant); trained rule fusion", sources)


def _druglikeness_feature(records: Sequence[OutputRecord]) -> Feature:
    """CNS druglikeness (CNS_MPO) - a different entity from penetration; single source."""
    sources = [Source(model="cns_mpo", value=v)
               for rec in records if rec.model == ModelName.cns_mpo
               for v in [num((rec.endpoint_values or {}).get(CNS_MPO_KEY))] if v is not None]
    return build_feature(Endpoint.distribution, DRUGLIKENESS,
                         "0-6 desirability (up = more CNS-druglike)", sources)


def _efflux_feature(records: Sequence[OutputRecord]) -> Feature:
    """P-gp efflux liability, derived from the generalist's Pgp_Broccatelli head (F-4, separate entity)."""
    sources: list[Source] = []
    for rec in records:
        pgp = extract_pgp(rec)
        if pgp.value is not None:
            sources.append(Source(model=pgp.source_model or "admet_ai", value=pgp.value))
    return build_feature(Endpoint.distribution, EFFLUX,
                         "P(P-gp substrate) [0,1] (up = more efflux liability)", sources)


def _molecule(mol_id: str, records: Sequence[Any]) -> MoleculeVerdict:
    recs = [as_output_record(r) for r in records]
    features = [_penetration_feature(recs), _druglikeness_feature(recs), _efflux_feature(recs)]
    return MoleculeVerdict(endpoint=Endpoint.distribution, mol_id=mol_id, features=features)


def aggregate(molecules: Mapping[str, Sequence[Any]] | Sequence[Any]) -> EndpointVerdict:
    """Screen distribution for a batch: penetration (score deferred) + CNS druglikeness + P-gp efflux."""
    mols = [_molecule(mid, recs) for mid, recs in normalize_molecules(molecules)]
    return EndpointVerdict(endpoint=Endpoint.distribution, molecules=mols, n_molecules=len(mols))
