#!/usr/bin/env python
"""ppb aggregator - plasma protein binding as one feature: ``fraction_bound``.

Three models report PPB on THREE different native representations; all are harmonized onto the common
feature ``fraction_bound`` (0-1, UP = more bound) before the shared fusion:

    model       native key            native scale       -> fraction_bound
    ------      ----------            ------------       -----------------
    ochem_ppb   ppb_percent_bound     % bound            pct / 100
    admet_ai    PPBR_AZ               % bound            pct / 100
    opera       FuB (or FuB_pred)     fraction UNBOUND   1 - FuB      (the inversion; the landmine)

The load-bearing science here is the **inversion**: OPERA's ``FuB`` is fraction UNBOUND, so a source only
joins the ensemble as ``1 - FuB``; a missed inversion (or a %/fraction mixup) silently corrupts the score.
Each source keeps its native ``raw`` value + ``raw_unit`` (for the %/inversion transparency) and its
model's native AD signals in ``native`` (OCHEM distance-to-model, OPERA conf_index/AD). ``build_feature``
fuses the sources (trained spec if present, else equal-weight) and projects them into the flat output
shape from ``core.aggregate``. PPB is a modulator, not a gate. See ``docs/ENDPOINTS.md`` for the fuller
rationale.
"""

from __future__ import annotations

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
        rec = as_output_record(raw_rec)
        ev = rec.endpoint_values or {}
        u = rec.uncertainty

        if rec.model == ModelName.ochem_ppb:
            pct = num(_first_present(ev, OCHEM_PCT_BOUND_KEYS))
            if pct is not None:
                native = ({"ad_in_domain": u.ad_in_domain,
                           "distance_to_model": (u.extra or {}).get("distance_to_model")}
                          if u is not None else {})
                sources.append(Source(model="ochem_ppb", value=pct / 100.0, raw=pct, raw_unit=PCT_UNIT,
                                      native=native))

        elif rec.model == ModelName.admet_ai:
            pct = num(ev.get(ADMET_AI_KEY))
            if pct is not None:
                sources.append(Source(model="admet_ai", value=pct / 100.0, raw=pct, raw_unit=PCT_UNIT))

        elif rec.model == ModelName.opera:
            fub = num(_first_present(ev, OPERA_FUB_KEYS))
            if fub is not None:
                native = ({"conf_index": (u.extra or {}).get("FuB_conf_index"),
                           "ad_in_domain": (u.extra or {}).get("FuB_ad_in_domain")}
                          if u is not None else {})
                sources.append(Source(model="opera", value=1.0 - fub, raw=fub, raw_unit=FUB_UNIT,
                                      native=native))

    return sources


def _molecule(mol_id: str, records: Sequence[Any]) -> MoleculeVerdict:
    sources = _sources(records)
    feature = build_feature(Endpoint.ppb, FEATURE, UNIT, sources)
    return MoleculeVerdict(endpoint=Endpoint.ppb, mol_id=mol_id, features=[feature])


def aggregate(molecules: Mapping[str, Sequence[Any]] | Sequence[Any]) -> EndpointVerdict:
    """Screen PPB for a batch: one ``fraction_bound`` feature per molecule (fused across the harmonized reads)."""
    mols = [_molecule(mid, recs) for mid, recs in normalize_molecules(molecules)]
    return EndpointVerdict(endpoint=Endpoint.ppb, molecules=mols, n_molecules=len(mols))
