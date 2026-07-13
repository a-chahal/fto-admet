#!/usr/bin/env python
"""lipophilicity aggregator - one feature: ``logD`` at pH 7.4 (a clean same-scale ensemble).

Four models report lipophilicity; all harmonize onto the common feature ``logD`` (log units, pH 7.4)
before the shared fusion:

    model          native key                    native scale   -> logD@7.4
    ------         ----------                    ------------   ----------
    opera          LogD                          logD           identity (native; carries conf_index)
    admet_ai       Lipophilicity_AstraZeneca     logD           identity (native logD7.4 head)
    rdkit_crippen  logP_crippen (WLOGP)          logP           logP -> logD via Henderson-Hasselbalch
    swissadme      Consensus_logP                logP           logP -> logD via Henderson-Hasselbalch

The load-bearing science is the **logP -> logD conversion** (F-12): for the di-basic FTO series
``logP != logD`` at pH 7.4, so a raw logP must be corrected for ionization before it can join a logD
ensemble. The conversion needs one shared pKa (F-13, DEFERRED): the placeholder is OPERA's ``pKa_b``
(basic; FTO is basic), read from the OPERA record, or an injected ``pka=``. A logP lens with no available
pKa cannot be harmonized and is carried with ``value=None`` (kept OUT of the score, never averaged raw),
its native logP still visible in ``raw``. Each source also carries its model's native AD / confidence
signals in ``native`` (OPERA conf_index/AD, SwissADME lens spread); ``build_feature`` fuses the sources
(trained spec if present, else equal-weight) and projects them into the flat output shape from
``core.aggregate``. See ``docs/ENDPOINTS.md`` for the fuller rationale.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from core.aggregate import (
    EndpointVerdict,
    MoleculeVerdict,
    Source,
    as_output_record,
    normalize_molecules,
    num,
)
from core.fusion import build_feature
from core.models import Endpoint, ModelName
from core.schemas import OutputRecord

FEATURE = "logD"
UNIT = "logD (log units, pH 7.4, up = more lipophilic)"
DEFAULT_PH = 7.4
LOGP_UNIT = "logP"


def logp_to_logd(logp: float, pka: float, ph: float = DEFAULT_PH, kind: str = "base") -> float:
    """Henderson-Hasselbalch logP -> logD at ``ph`` for a monoprotic center (the DEFERRED F-16 placeholder).

    ``logD = logP - log10(1 + 10**exp)`` with ``exp = pKa - pH`` (base) or ``pH - pKa`` (acid). The FTO
    series is di-basic (F-16), so the true conversion is multi-site; that is DEFERRED and this monoprotic
    form is the documented placeholder. Any residual gap it leaves for a di-protic center surfaces as
    ensemble disagreement (uncertainty), not a fabricated di-cation formula.
    """
    if kind == "base":
        exponent = pka - ph
    elif kind == "acid":
        exponent = ph - pka
    else:  # pragma: no cover - guarded input
        raise ValueError(f"kind must be 'base' or 'acid', got {kind!r}")
    return float(logp - math.log10(1.0 + 10.0 ** exponent))


def _resolve_pka(
    records: Sequence[OutputRecord],
    override: float | None,
    override_kind: str | None,
) -> tuple[float | None, str | None]:
    """Pick the single shared pKa ``(value, kind)``. F-13 DEFERRED: OPERA is the placeholder source.

    An explicit ``override`` (kind defaults to base, since FTO is basic) wins; otherwise OPERA's ``pKa_b``
    (basic) is preferred, falling back to ``pKa_a`` (acidic). Returns ``(None, None)`` when no pKa is
    available - then logP lenses cannot be converted and are kept out of the score (F-12).
    """
    if override is not None:
        return float(override), (override_kind or "base")
    pka_b: float | None = None
    pka_a: float | None = None
    for rec in records:
        if rec.model != ModelName.opera:
            continue
        ev = rec.endpoint_values or {}
        if pka_b is None and ev.get("pKa_b") is not None:
            pka_b = num(ev["pKa_b"])
        if pka_a is None and ev.get("pKa_a") is not None:
            pka_a = num(ev["pKa_a"])
    if pka_b is not None:
        return pka_b, "base"
    if pka_a is not None:
        return pka_a, "acid"
    return None, None


def _logp_source(model: str, logp: float, pka: float | None, kind: str | None, ph: float,
                 native: dict[str, Any]) -> Source:
    """A logP lens harmonized to logD via the shared pKa; ``value=None`` (excluded) when no pKa exists (F-12).

    The native logP is retained in ``raw`` (it differs from the harmonized logD); ``native`` carries the
    model's own uncertainty signals.
    """
    logd = None if pka is None else logp_to_logd(logp, pka, ph=ph, kind=kind or "base")
    return Source(model=model, value=logd, raw=logp, raw_unit=LOGP_UNIT, native=native)


def _sources(records: Sequence[OutputRecord], pka: float | None, kind: str | None, ph: float) -> list[Source]:
    """Harmonize each contributing model's lipophilicity read onto logD, keeping native logP in ``raw``."""
    sources: list[Source] = []
    for rec in records:
        ev = rec.endpoint_values or {}
        u = rec.uncertainty
        if rec.model == ModelName.opera:
            v = num(ev.get("LogD"))
            if v is not None:
                native = ({"conf_index": u.conf_index, "ad_in_domain": u.ad_in_domain,
                           "ad_index": u.ad_index} if u is not None else {})
                sources.append(Source(model="opera", value=v, native=native))
        elif rec.model == ModelName.admet_ai:
            v = num(ev.get("Lipophilicity_AstraZeneca"))
            if v is not None:
                sources.append(Source(model="admet_ai", value=v))
        elif rec.model == ModelName.rdkit_crippen:
            lp = num(ev.get("logP_crippen"))
            if lp is not None:
                sources.append(_logp_source("rdkit_crippen", lp, pka, kind, ph, {}))
        elif rec.model == ModelName.swissadme:
            lp = num(ev.get("Consensus_logP"))
            if lp is not None:
                native = {"spread_std": (u.extra or {}).get("spread_std")} if u is not None else {}
                sources.append(_logp_source("swissadme", lp, pka, kind, ph, native))
    return sources


def _molecule(mol_id: str, records: Sequence[Any], pka: float | None, pka_kind: str | None,
              ph: float) -> MoleculeVerdict:
    recs = [as_output_record(r) for r in records]
    pka_used, kind = _resolve_pka(recs, pka, pka_kind)
    sources = _sources(recs, pka_used, kind, ph)
    feature = build_feature(Endpoint.lipophilicity, FEATURE, UNIT, sources)
    return MoleculeVerdict(endpoint=Endpoint.lipophilicity, mol_id=mol_id, features=[feature])


def aggregate(
    molecules: Mapping[str, Sequence[Any]] | Sequence[Any],
    *,
    pka: float | None = None,
    pka_kind: str | None = None,
    ph: float = DEFAULT_PH,
) -> EndpointVerdict:
    """Screen lipophilicity for a batch: one ``logD`` feature per molecule (fused across the harmonized lenses).

    ``pka`` (with optional ``pka_kind`` in ``{"base","acid"}``) injects the single shared pKa for the
    logP -> logD conversion; when it is ``None`` the placeholder (OPERA ``pKa_b``, F-13) is read per molecule.
    """
    mols = [_molecule(mid, recs, pka, pka_kind, ph) for mid, recs in normalize_molecules(molecules)]
    return EndpointVerdict(endpoint=Endpoint.lipophilicity, molecules=mols, n_molecules=len(mols))
