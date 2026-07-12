#!/usr/bin/env python
"""ppb aggregator - plasma protein binding as one feature: ``fraction_bound``.

Three models report PPB on THREE different native representations; all are harmonized onto the common
feature ``fraction_bound`` (0-1, UP = more bound) before the shared ensemble mean/std:

    model       native key            native scale       -> fraction_bound
    ------      ----------            ------------       -----------------
    ochem_ppb   ppb_percent_bound     % bound            pct / 100
    admet_ai    PPBR_AZ               % bound            pct / 100
    opera       FuB (or FuB_pred)     fraction UNBOUND   1 - FuB      (the inversion; the landmine)

The load-bearing science here is the **inversion**: OPERA's ``FuB`` is fraction UNBOUND, so a source only
joins the ensemble as ``1 - FuB``; a missed inversion (or a %/fraction mixup) silently corrupts the score.
Everything else - ``score`` = mean of the harmonized values, ``uncertainty`` = std over them, the native
``raw`` value + unit carried on each source - is the shared shape from ``core.aggregate``. PPB is a
modulator, not a gate. See ``docs/ENDPOINTS.md`` for the fuller rationale.
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

FEATURE = "fraction_bound"
UNIT = "fraction bound (0-1, up = more bound)"

# The ONLY native keys this aggregator reads, per model (verified against the adapters).
ADMET_AI_KEY = "PPBR_AZ"                        # % bound
OPERA_FUB_KEYS: tuple[str, ...] = ("FuB", "FuB_pred")   # fraction UNBOUND (both accepted; a rename on
#                                                         either side must not silently drop the source)
# OCHEM emits % bound; its key is VERIFIED live (modelId 1121) as ``ppb_percent_bound`` (read first).
# ``fraction_bound`` is deliberately NOT in this %-scale set - it is already a fraction (dividing by 100
# would be a 100x error). The trailing entries are tolerant pre-live fallbacks.
OCHEM_PCT_BOUND_KEYS: tuple[str, ...] = (
    "ppb_percent_bound", "PPB", "ppb", "percent_bound", "PPB_percent", "pct_bound", "plasma_protein_binding",
)

PCT_UNIT = "% bound"
FUB_UNIT = "fraction unbound"


def _as_output_record(rec: Any) -> OutputRecord:
    return rec if isinstance(rec, OutputRecord) else OutputRecord.model_validate(rec)


def _num(value: Any) -> float | None:
    """Coerce to a finite float, or ``None`` (a source with no numeric value never enters the mean)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _first_present(ev: Mapping[str, Any], keys: Sequence[str]) -> Any | None:
    """The value of the first present, non-null key in ``keys`` (case-sensitive), else ``None``."""
    for k in keys:
        if ev.get(k) is not None:
            return ev[k]
    return None


def _sources(records: Sequence[Any]) -> list[Source]:
    """Harmonize each contributing model's PPB read onto fraction_bound, keeping the native raw value."""
    sources: list[Source] = []
    for raw_rec in records:
        rec = _as_output_record(raw_rec)
        ev = rec.endpoint_values or {}

        if rec.model == ModelName.ochem_ppb:
            pct = _num(_first_present(ev, OCHEM_PCT_BOUND_KEYS))
            if pct is not None:
                sources.append(Source(model="ochem_ppb", value=pct / 100.0, raw=pct, raw_unit=PCT_UNIT))

        elif rec.model == ModelName.admet_ai:
            pct = _num(ev.get(ADMET_AI_KEY))
            if pct is not None:
                sources.append(Source(model="admet_ai", value=pct / 100.0, raw=pct, raw_unit=PCT_UNIT))

        elif rec.model == ModelName.opera:
            fub = _num(_first_present(ev, OPERA_FUB_KEYS))
            if fub is not None:
                sources.append(Source(model="opera", value=1.0 - fub, raw=fub, raw_unit=FUB_UNIT))

    return sources


def _molecule(mol_id: str, records: Sequence[Any]) -> MoleculeVerdict:
    sources = _sources(records)
    score, uncertainty = fuse(Endpoint.ppb, FEATURE, sources)   # trained spec if present, else equal-weight
    feature = Feature(
        feature=FEATURE, score=score, uncertainty=uncertainty, unit=UNIT,
        n_sources=len(sources), sources=sources,
    )
    return MoleculeVerdict(endpoint=Endpoint.ppb, mol_id=mol_id, features=[feature])


def aggregate(molecules: Mapping[str, Sequence[Any]] | Sequence[Any]) -> EndpointVerdict:
    """Screen PPB for a batch: one ``fraction_bound`` feature per molecule (score = mean, uncertainty = std)."""
    mols = [_molecule(mid, recs) for mid, recs in normalize_molecules(molecules)]
    return EndpointVerdict(endpoint=Endpoint.ppb, molecules=mols, n_molecules=len(mols))
