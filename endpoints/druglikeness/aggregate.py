#!/usr/bin/env python
"""druglikeness aggregator - context flags ONLY (Lipinski violations, Veber pass, QED). NEVER a gate.

Contract (task t50, CLAUDE.md §2, IO_SPEC §2 "druglikeness", §30/§B): this endpoint has no aggregation
math and no consensus vote. It runs in the core env (no box, no GPU) and simply *surfaces*, per molecule,
the three drug-likeness context flags exactly as the ``lipinski_veber_qed`` model (t19) emits them:

    field                 type          direction                     source (model -> field)
    -----                 ----          ---------                     ----------------------
    Lipinski_violations   int 0-4       fewer = more drug-like        lipinski_veber_qed -> Lipinski_violations
    Veber_pass            bool          pass = more drug-like         lipinski_veber_qed -> Veber_pass
    QED                   float 0-1     higher = more drug-like       lipinski_veber_qed -> QED

LANDMINE (task t50, IO_SPEC §30 "Context/POINTER - run by the lab, not a gate"): these are read by the
lab as CONTEXT, they are NEVER an advance/kill decision. So this aggregator deliberately does NO gate
aggregation: no threshold, no pass/fail verdict, no promote/reject scalar, nothing that could be read as
a kill. It passes the three fields through UNCHANGED and attaches a one-line "context, not a gate" note.
Turning drug-likeness into a filter is a well-known error (QED and Ro5 are soft guidance, not rules), and
for a CNS FTO-inhibitor series the classic thresholds are especially inappropriate. The consuming decision
policy, if any, is downstream and out of scope.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.models import Endpoint, ModelName
from core.schemas import OutputRecord

# The three context flags this endpoint surfaces, keyed exactly as the lipinski_veber_qed model (t19)
# writes them into ``endpoint_values``. These are the ONLY keys this aggregator reads. Kept as named
# constants so the tests bind to them, not to raw strings.
LIPINSKI_KEY = "Lipinski_violations"   # int 0-4; fewer violations = more drug-like (Lipinski 2001)
VEBER_KEY = "Veber_pass"               # bool; pass = more drug-like (Veber 2002)
QED_KEY = "QED"                        # float 0-1; higher = more drug-like (Bickerton et al. 2012)

# The model that emits the flags. Read by endpoint membership / field presence, never by folder; a future
# model that emits the same three fields would be surfaced too (the reader keys off the field names).
SOURCE_MODEL = ModelName.lipinski_veber_qed


def _as_output_record(rec: Any) -> OutputRecord:
    """Coerce a dict (or an already-built ``OutputRecord``) into an ``OutputRecord`` for uniform access."""
    if isinstance(rec, OutputRecord):
        return rec
    return OutputRecord.model_validate(rec)


class MoleculeDruglikeness(BaseModel):
    """One molecule's drug-likeness CONTEXT: the three flags surfaced as-is. No verdict, no gate.

    ``present`` is True when at least one contributing record carried these flags. The three flags are
    passed through UNCHANGED (``None`` when absent). ``is_gate`` is always False and stated explicitly:
    drug-likeness is context read by the lab, it is NEVER an advance/kill decision (task t50 landmine).
    """

    model_config = ConfigDict(extra="forbid")

    mol_id: str
    present: bool
    Lipinski_violations: int | None = None
    Veber_pass: bool | None = None
    QED: float | None = None
    is_gate: bool = False   # explicit: drug-likeness flags do NOT gate/kill a molecule.
    notes: list[str] = Field(default_factory=list)


class EndpointResult(BaseModel):
    """The druglikeness result: the three context flags per molecule, surfaced as-is. Deliberately NO gate.

    There is intentionally NO consensus, threshold, or pass/fail field anywhere: the payload is the three
    flags and a "context, not a gate" note. The aggregator owns its own result shape (an aggregator task
    may not touch ``core``).
    """

    model_config = ConfigDict(extra="forbid")

    endpoint: Endpoint = Endpoint.druglikeness
    quantity: str = (
        "three drug-likeness CONTEXT flags surfaced as-is: Lipinski_violations (int 0-4, fewer = more "
        "drug-like), Veber_pass (bool), QED (float 0-1, higher = more drug-like). Context read by the "
        "lab, NEVER a gate/kill; no aggregation, threshold, or pass/fail verdict."
    )
    molecules: list[MoleculeDruglikeness]
    n_molecules: int
    notes: list[str] = Field(default_factory=list)


def _druglikeness_for(mol_id: str, records: Sequence[OutputRecord]) -> MoleculeDruglikeness:
    """Surface the three context flags for one molecule, unchanged; no gate logic anywhere.

    Reads the three keys from the contributing records' ``endpoint_values``. If more than one record carries
    a flag (unusual - only lipinski_veber_qed emits them), the first non-``None`` value wins; the flags are
    never combined, averaged, or thresholded. A missing flag stays ``None`` (surfaced as absent, not zero).
    """
    lipinski: int | None = None
    veber: bool | None = None
    qed: float | None = None

    for rec in records:
        ev = rec.endpoint_values or {}
        if lipinski is None and ev.get(LIPINSKI_KEY) is not None:
            lipinski = int(ev[LIPINSKI_KEY])  # type: ignore[arg-type]
        if veber is None and ev.get(VEBER_KEY) is not None:
            veber = bool(ev[VEBER_KEY])
        if qed is None and ev.get(QED_KEY) is not None:
            qed = float(ev[QED_KEY])  # type: ignore[arg-type]

    present = lipinski is not None or veber is not None or qed is not None
    notes = [
        "CONTEXT, not a gate (task t50 / IO_SPEC §30): Lipinski_violations / Veber_pass / QED are read by "
        "the lab, they are NEVER an advance/kill decision. The three flags are surfaced UNCHANGED; there is "
        "no threshold, consensus, or pass/fail verdict here.",
    ]
    if not present:
        notes.append("no drug-likeness flag (Lipinski_violations / Veber_pass / QED) present in the bundle.")

    return MoleculeDruglikeness(
        mol_id=mol_id,
        present=present,
        Lipinski_violations=lipinski,
        Veber_pass=veber,
        QED=qed,
        notes=notes,
    )


def _normalize_molecules(
    molecules: Mapping[str, Sequence[Any]] | Sequence[Any],
) -> list[tuple[str, list[Any]]]:
    """Normalize the accepted input shapes to ``[(mol_id, records), ...]`` (same contract as the other aggregators).

    Accepts: a Mapping ``{mol_id: records}``; a sequence of ``(mol_id, records)`` pairs; a sequence of dicts
    ``{"mol_id"|"id": ..., "records": [...]}``; or a bare sequence of record-lists (id defaults to a
    positional ``mol_<i>``). A record-list is never mistaken for an ``(id, records)`` pair because a pair's
    first element is a ``str`` while a record-list's first element is a record/dict.
    """
    if isinstance(molecules, Mapping):
        return [(str(mid), list(recs)) for mid, recs in molecules.items()]

    out: list[tuple[str, list[Any]]] = []
    for i, item in enumerate(molecules):
        if isinstance(item, Mapping) and "records" in item:
            mid = item.get("mol_id") or item.get("id") or f"mol_{i}"
            out.append((str(mid), list(item["records"])))
        elif (
            isinstance(item, (tuple, list))
            and len(item) == 2
            and isinstance(item[0], str)
            and isinstance(item[1], (list, tuple))
        ):
            out.append((item[0], list(item[1])))
        else:
            out.append((f"mol_{i}", list(item)))
    return out


def aggregate(
    molecules: Mapping[str, Sequence[Any]] | Sequence[Any],
) -> EndpointResult:
    """Surface, per molecule, the three drug-likeness CONTEXT flags as-is. NEVER a gate (task t50 landmine).

    ``molecules`` is the compound set (see ``_normalize_molecules`` for the accepted shapes); each molecule's
    bundle is a list of its model ``OutputRecord``s. For each molecule the three flags
    (``Lipinski_violations`` / ``Veber_pass`` / ``QED``) are read from ``endpoint_values`` and passed through
    UNCHANGED. There is deliberately no aggregation, threshold, consensus, or pass/fail verdict: drug-likeness
    is context read by the lab, it is NEVER an advance/kill decision.
    """
    norm = _normalize_molecules(molecules)
    mols = [_druglikeness_for(mid, [_as_output_record(r) for r in raw_recs]) for mid, raw_recs in norm]

    return EndpointResult(
        molecules=mols,
        n_molecules=len(mols),
        notes=[
            "druglikeness is CONTEXT flags only: Lipinski_violations, Veber_pass, QED surfaced as-is. It is "
            "read by the lab, NEVER a gate/kill (task t50 / IO_SPEC §30 Context/POINTER).",
            "there is deliberately no aggregation, threshold, consensus, or pass/fail verdict; turning "
            "drug-likeness into a filter is an error, doubly so for a CNS FTO-inhibitor series.",
        ],
    )
