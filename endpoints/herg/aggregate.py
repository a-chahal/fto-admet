#!/usr/bin/env python
"""herg aggregator - the cardiotoxicity channel: hERG block plus the NaV1.5 / CaV1.2 context reads.

hERG is the pipeline's primary cardiotox liability. Three models report P(hERG block) on the SAME
probability scale, so they harmonize into one clean ensemble feature ``hERG_block``:

    model          native key    native scale        -> hERG_block
    ------         ----------    ------------        ------------
    admet_ai       hERG          P(block) [0,1]      identity
    bayesherg      P_block       P(block) [0,1]      identity (carries alea/epis in the note)
    cardiotox_net  P_block       P(block) [0,1]      identity (Morgan-onbits applicability limit)
    cardiogenai    hERG pIC50    pIC50 (not a prob)  carried, NOT scored (value=None)

The load-bearing science is that CardioGenAI's discriminative head emits a pIC50, NOT a probability:
the pIC50 -> P(block) mapping is DEFERRED (F-1), so CardioGenAI joins ``hERG_block`` as a carried source
with ``value=None`` (its raw pIC50 stays visible in ``raw``) and never enters the mean. The score is
therefore the mean of the three real probabilities; ``uncertainty`` is their std. CardioGenAI's two
other discriminative reads - the NaV1.5 and CaV1.2 pIC50s (literal spaces in the keys) - are DIFFERENT
entities (different ion channels), so each is its own single-source feature, never fused with hERG.
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

# The ONLY native keys this aggregator reads, per model (verified against the adapters). The CardioGenAI
# keys carry a LITERAL SPACE and must be quoted exactly (CLAUDE.md §4 landmine).
ADMET_AI_HERG_KEY = "hERG"                  # admet_ai: pre-screen P(hERG block) [0,1]
BAYESHERG_PBLOCK_KEY = "P_block"            # bayesherg: identity P(block) [0,1]
CARDIOTOX_PBLOCK_KEY = "P_block"            # cardiotox_net: identity P(block) [0,1]
CARDIOGENAI_HERG_PIC50_KEY = "hERG pIC50"   # cardiogenai: raw pIC50 (not a probability); F-1 DEFERRED
CARDIOGENAI_NAV_KEY = "NaV1.5 pIC50"        # cardiogenai: NaV1.5 pIC50 (a different ion channel)
CARDIOGENAI_CAV_KEY = "CaV1.2 pIC50"        # cardiogenai: CaV1.2 pIC50 (a different ion channel)

HERG_BLOCK = "hERG_block"
NAV_BLOCK = "nav1.5_block"
CAV_BLOCK = "cav1.2_block"

HERG_UNIT = "P(hERG block) [0,1] (up = more block, worse)"
NAV_UNIT = "pIC50 (up = more block)"
CAV_UNIT = "pIC50 (up = more block)"
PIC50_UNIT = "pIC50"


def _as_output_record(rec: Any) -> OutputRecord:
    return rec if isinstance(rec, OutputRecord) else OutputRecord.model_validate(rec)


def _num(value: Any) -> float | None:
    """Coerce to a finite float, or ``None`` (a source with no numeric value never enters the mean)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _herg_block_feature(records: Sequence[OutputRecord]) -> Feature:
    """P(hERG block): three identity-probability sources ensembled; CardioGenAI's pIC50 carried, not scored."""
    sources: list[Source] = []
    for rec in records:
        ev = rec.endpoint_values or {}
        if rec.model == ModelName.admet_ai:
            v = _num(ev.get(ADMET_AI_HERG_KEY))
            if v is not None:
                sources.append(Source(model="admet_ai", value=v, note="P(hERG block)"))
        elif rec.model == ModelName.bayesherg:
            v = _num(ev.get(BAYESHERG_PBLOCK_KEY))
            if v is not None:
                unc = rec.uncertainty
                alea = unc.aleatoric if unc is not None else None
                epis = unc.epistemic if unc is not None else None
                sources.append(Source(model="bayesherg", value=v,
                                      note=f"P(block); alea={alea} epis={epis}"))
        elif rec.model == ModelName.cardiotox_net:
            v = _num(ev.get(CARDIOTOX_PBLOCK_KEY))
            if v is not None:
                sources.append(Source(model="cardiotox_net", value=v, note="P(block); Morgan onbits AD"))
        elif rec.model == ModelName.cardiogenai:
            pic50 = _num(ev.get(CARDIOGENAI_HERG_PIC50_KEY))
            if pic50 is not None:
                sources.append(Source(
                    model="cardiogenai", value=None, raw=pic50, raw_unit=PIC50_UNIT,
                    note="pIC50; placeholder pIC50->P(block) DEFERRED (F-1), excluded from score",
                ))
    score, uncertainty = ensemble([s.value for s in sources], [s.weight for s in sources])
    return Feature(feature=HERG_BLOCK, score=score, uncertainty=uncertainty, unit=HERG_UNIT,
                   n_sources=len(sources), sources=sources)


def _channel_feature(records: Sequence[OutputRecord], key: str, feature: str, unit: str) -> Feature:
    """A single-source CardioGenAI ion-channel pIC50 read (NaV1.5 or CaV1.2) - its own separate entity."""
    sources: list[Source] = []
    for rec in records:
        if rec.model == ModelName.cardiogenai:
            v = _num((rec.endpoint_values or {}).get(key))
            if v is not None:
                sources.append(Source(model="cardiogenai", value=v, note="pIC50 (up = more block)"))
    score, uncertainty = ensemble([s.value for s in sources], [s.weight for s in sources])
    return Feature(feature=feature, score=score, uncertainty=uncertainty, unit=unit,
                   n_sources=len(sources), sources=sources)


def _molecule(mol_id: str, records: Sequence[Any]) -> MoleculeVerdict:
    recs = [_as_output_record(r) for r in records]
    features = [
        _herg_block_feature(recs),
        _channel_feature(recs, CARDIOGENAI_NAV_KEY, NAV_BLOCK, NAV_UNIT),
        _channel_feature(recs, CARDIOGENAI_CAV_KEY, CAV_BLOCK, CAV_UNIT),
    ]
    return MoleculeVerdict(endpoint=Endpoint.herg, mol_id=mol_id, features=features)


def aggregate(molecules: Mapping[str, Sequence[Any]] | Sequence[Any]) -> EndpointVerdict:
    """Screen hERG for a batch: hERG_block (3-prob ensemble) + NaV1.5 + CaV1.2 context reads per molecule."""
    mols = [_molecule(mid, recs) for mid, recs in normalize_molecules(molecules)]
    return EndpointVerdict(endpoint=Endpoint.herg, molecules=mols, n_molecules=len(mols))
