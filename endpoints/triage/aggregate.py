#!/usr/bin/env python
"""triage aggregator - the funnel-entry generalist read-out. CONTEXT ONLY.

Triage is not a scientific endpoint in its own right: it is the funnel entry that surfaces the
cross-cutting generalist(s) so the real endpoints can consume their heads. It is modeled as an endpoint
purely for code consistency (the same ``aggregate(molecules) -> EndpointResult`` contract as every other
endpoint), but it does NO scoring, NO consensus, NO uncertainty, and NO gate.

With admetlab3 removed there is exactly ONE generalist (``admet_ai``), so there is nothing to cross-check.
This aggregator therefore just EXPOSES admet_ai's usable heads verbatim, per molecule. The one guard is
F-17: the two worse-than-the-mean ADMET-AI heads (``VDss_Lombardo`` / ``Half_Life_Obach``) are never
surfaced (the adapter already quarantines them in ``raw``; this is belt-and-braces).

If a second independent generalist is ever added, cross-model spread would belong here again; until then,
keep it a thin pass-through. Every real endpoint's aggregator reads admet_ai's heads it needs directly
(``ev.get("hERG")`` etc.) via registry membership - it does not go through this triage view.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.aggregate import normalize_molecules
from core.models import Endpoint, ModelName
from core.schemas import OutputRecord

# The cross-cutting generalist(s) this triage view surfaces. A record from any other model is ignored
# (triage is generalist-only); the real endpoints read admet_ai's heads directly by registry membership.
GENERALISTS: frozenset[ModelName] = frozenset({ModelName.admet_ai})

# ADMET-AI heads the model itself reports as worse-than-the-mean (F-17). Already quarantined in the
# adapter's ``raw``; guarded here too so they can NEVER be surfaced.
EXCLUDED_R2_NEGATIVE: frozenset[str] = frozenset({"VDss_Lombardo", "Half_Life_Obach"})

# The scalar types an ``endpoint_values`` head can carry (mirrors core.schemas.OutputRecord).
Scalar = float | int | str | bool | None


def _as_output_record(rec: Any) -> OutputRecord:
    """Coerce a dict (or an already-built ``OutputRecord``) into an ``OutputRecord`` for uniform access."""
    if isinstance(rec, OutputRecord):
        return rec
    return OutputRecord.model_validate(rec)


class MoleculeTriage(BaseModel):
    """One molecule's funnel-entry read: the generalist's usable heads, surfaced verbatim. No verdict.

    ``present`` is True when a generalist record was in the bundle. ``values`` is admet_ai's
    ``endpoint_values`` passed through unchanged, minus the F-17 heads. There is deliberately no
    consensus / spread / confidence / gate field: triage is context that feeds the real endpoints.
    """

    model_config = ConfigDict(extra="forbid")

    mol_id: str
    present: bool
    values: dict[str, Scalar] = Field(default_factory=dict)


class EndpointResult(BaseModel):
    """The triage result: per-molecule raw generalist reads. Context only - no consensus, no gate."""

    model_config = ConfigDict(extra="forbid")

    endpoint: Endpoint = Endpoint.triage
    quantity: str = (
        "funnel-entry generalist reads (ADMET-AI heads) surfaced verbatim; context that feeds the real "
        "endpoints. No consensus, no uncertainty, no gate."
    )
    molecules: list[MoleculeTriage]
    n_molecules: int


def _triage_for(mol_id: str, records: Sequence[Any]) -> MoleculeTriage:
    """Surface one molecule's generalist heads verbatim (minus F-17). Non-generalist records are ignored."""
    values: dict[str, Scalar] = {}
    present = False
    for raw in records:
        rec = _as_output_record(raw)
        if rec.model not in GENERALISTS:
            continue
        present = True
        for key, val in (rec.endpoint_values or {}).items():
            if key in EXCLUDED_R2_NEGATIVE:  # F-17: never surface VDss_Lombardo / Half_Life_Obach
                continue
            values[key] = val
    return MoleculeTriage(mol_id=mol_id, present=present, values=values)


def aggregate(molecules: Mapping[str, Sequence[Any]] | Sequence[Any]) -> EndpointResult:
    """Surface each molecule's generalist (ADMET-AI) heads verbatim. Context only - no scoring, no gate.

    ``molecules`` accepts the shared aggregator input shapes (see ``core.aggregate.normalize_molecules``);
    each molecule's bundle is a list of its model ``OutputRecord``s (or their plain-dict form).
    """
    mols = [_triage_for(mid, recs) for mid, recs in normalize_molecules(molecules)]
    return EndpointResult(molecules=mols, n_molecules=len(mols))
