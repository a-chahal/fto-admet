#!/usr/bin/env python
"""distribution aggregator - three separate entities: passive BBB penetration, CNS druglikeness, P-gp efflux.

The endpoint holds THREE distinct entities that must never be averaged together (F-4):

    feature            sources                                     scale / status
    -------            -------                                     --------------
    bbb_penetration    bbb_score BBB_Score (0-6 desirability),     THREE incompatible scales measuring ONE
                       admet_ai BBB_Martins (probability),         entity (does it cross the BBB). No clean
                       boiled_egg BBB_boiled_egg (bool)            common axis -> score DEFERRED (None); the
                                                                   three native reads are carried as sources.
    cns_druglikeness   cns_mpo CNS_MPO (0-6 desirability)          a DIFFERENT entity (developability, not
                                                                   penetration) -> its own single-source value.
    pgp_efflux         admet_ai Pgp_Broccatelli via pgp.py         efflux liability (F-4, separate entity)
                                                                   -> single-source value.

Why ``bbb_penetration`` carries no score yet: BBB_Score (a 0-6 desirability), BBB_Martins (a trained
probability), and boiled_egg (a boolean) all predict passive BBB penetration, but on scales with no
scientifically clean common axis. Averaging them would need an arbitrary rescale, so - per the
"score only clean fusions" policy - the fused score is DEFERRED until each source is calibrated to a shared
experimental target (logBB / Kp,uu); the three native reads are all carried (real values shown), ready for
that calibration. CNS_MPO measures CNS DRUGLIKENESS (developability), a different entity, so it is a
separate feature, never folded into penetration. P-gp efflux is a third separate entity. Out-of-band DruMAP
signals (watanabe_pgp_brain Kp,uu / NER) are transcribed by hand, not read here.
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
from endpoints.distribution.pgp.pgp import extract_pgp

# The ONLY native keys this aggregator reads (verified against the adapters).
BBB_SCORE_KEY = "BBB_Score"            # bbb_score: 0-6 desirability, higher = more likely passive penetrant
CNS_MPO_KEY = "CNS_MPO"                # cns_mpo: 0-6 desirability, higher = more CNS-druglike (developability)
BBB_MARTINS_KEY = "BBB_Martins"        # admet_ai: P(BBB penetrant), [0,1]
BBB_BOILED_EGG_KEY = "BBB_boiled_egg"  # boiled_egg: bool (in the yolk / BBB region)

PENETRATION = "bbb_penetration"
DRUGLIKENESS = "cns_druglikeness"
EFFLUX = "pgp_efflux"


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


def _penetration_feature(records: Sequence[OutputRecord]) -> Feature:
    """Passive BBB penetration: three native reads on incompatible scales, score DEFERRED (mixed axis)."""
    sources: list[Source] = []
    for rec in records:
        ev = rec.endpoint_values or {}
        if rec.model == ModelName.bbb_score:
            v = _num(ev.get(BBB_SCORE_KEY))
            if v is not None:
                sources.append(Source(model="bbb_score", value=v,
                                      note="BBB Score, 0-6 desirability (up = penetrant)"))
        elif rec.model == ModelName.admet_ai:
            v = _num(ev.get(BBB_MARTINS_KEY))
            if v is not None:
                sources.append(Source(model="admet_ai", value=v,
                                      note="P(BBB penetrant), probability [0,1]"))
        elif rec.model == ModelName.boiled_egg:
            b = ev.get(BBB_BOILED_EGG_KEY)
            if isinstance(b, bool):
                sources.append(Source(model="boiled_egg", value=b,
                                      note="in-yolk point-in-polygon, boolean (True = penetrant)"))
    # Mixed scales, one entity: no clean common axis -> score DEFERRED until calibration (F-4 / logBB target).
    return Feature(feature=PENETRATION, score=None, uncertainty=None, unit=None,
                   n_sources=len(sources), sources=sources)


def _druglikeness_feature(records: Sequence[OutputRecord]) -> Feature:
    """CNS druglikeness (CNS_MPO) - a different entity from penetration; single source."""
    sources: list[Source] = []
    for rec in records:
        if rec.model == ModelName.cns_mpo:
            v = _num((rec.endpoint_values or {}).get(CNS_MPO_KEY))
            if v is not None:
                sources.append(Source(model="cns_mpo", value=v, note="CNS MPO, developability desirability"))
    score, uncertainty = ensemble([s.value for s in sources], [s.weight for s in sources])
    return Feature(feature=DRUGLIKENESS, score=score, uncertainty=uncertainty,
                   unit="0-6 desirability (up = more CNS-druglike)", n_sources=len(sources), sources=sources)


def _efflux_feature(records: Sequence[OutputRecord]) -> Feature:
    """P-gp efflux liability, derived from the generalist's Pgp_Broccatelli head (F-4, separate entity)."""
    sources: list[Source] = []
    for rec in records:
        pgp = extract_pgp(rec)
        if pgp.value is not None:
            sources.append(Source(model=pgp.source_model or "admet_ai", value=pgp.value,
                                  note=f"P-gp efflux via {pgp.source_key}"))
    score, uncertainty = ensemble([s.value for s in sources], [s.weight for s in sources])
    return Feature(feature=EFFLUX, score=score, uncertainty=uncertainty,
                   unit="P(P-gp substrate) [0,1] (up = more efflux liability)",
                   n_sources=len(sources), sources=sources)


def _molecule(mol_id: str, records: Sequence[Any]) -> MoleculeVerdict:
    recs = [_as_output_record(r) for r in records]
    features = [_penetration_feature(recs), _druglikeness_feature(recs), _efflux_feature(recs)]
    return MoleculeVerdict(endpoint=Endpoint.distribution, mol_id=mol_id, features=features)


def aggregate(molecules: Mapping[str, Sequence[Any]] | Sequence[Any]) -> EndpointVerdict:
    """Screen distribution for a batch: penetration (score deferred) + CNS druglikeness + P-gp efflux."""
    mols = [_molecule(mid, recs) for mid, recs in normalize_molecules(molecules)]
    return EndpointVerdict(endpoint=Endpoint.distribution, molecules=mols, n_molecules=len(mols))
