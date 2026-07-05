#!/usr/bin/env python
"""solubility aggregator - a relative solubility RANK across the compound set (SFI primary, log S cross-check).

Contract (CLAUDE.md §2): the aggregator runs in the core env (no box, no GPU); it consumes already
collected ``OutputRecord``s and harmonizes them onto one common quantity. For solubility that common
quantity is a **relative solubility rank** (IO_SPEC §2 solubility), NOT a single calibrated scalar: the
two contributing models emit incompatible scales, so the honest shared read is an ordinal ranking of the
series, not an averaged number.

    model            field                    direction        role       onto the common rank
    -----            -----                    ---------        ----       ---------------------
    sfi              SFI                       LOWER = better   primary    rank by SFI ascending
    admet_ai         Solubility_AqSolDB (logS) HIGHER = better  cross-check rank by logS descending

LANDMINE (the point of this file): the two lenses point in OPPOSITE directions - SFI **lower = more
soluble**, log S **higher = more soluble** - and they live on unrelated scales (SFI ~= cLogD + #aromatic
rings; log S in log mol/L). A raw average of the two is WRONG (IO_SPEC §2; task t41). We reconcile the
direction BEFORE ranking: ``sfi_soluble_score = -SFI`` flips SFI to point the same way as log S (higher =
more soluble), and the two lenses are co-ranked **ordinally** (never averaged raw), which also sidesteps
their incompatible units.

Uncertainty signal = the **SFI-vs-generalist discrepancy** (IO_SPEC §2). Because the two scales are not
commensurable, the discrepancy is measured as a *rank* disagreement: each molecule gets a position within
the series from SFI (primary) and from log S (cross-check), both normalized to ``[0, 1]`` with 0 = most
soluble. Where the two positions diverge widely the flag is raised - for the low-aromatic oxetane series
that divergence is expected to read as a *series strength* (SFI, which rewards the low aromatic-ring
count, calling the compound more soluble than the generalist does), not a model error.

DEFERRED boundaries honored here (CLAUDE.md §4a; wired to a placeholder, never invented):
- **Rank-gap -> calibrated confidence.** Turning the rank disagreement into a calibrated uncertainty is
  the DEFERRED AD/calibration policy. Here the gap drives a documented heuristic flag only; the threshold
  is a named constant marked a heuristic, not a calibrated cut.
- The cLogD inside SFI already carries the F-13 (shared pKa) / F-16 (di-cation) placeholders from the sfi
  adapter; this aggregator consumes SFI as emitted and does not re-open those decisions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.models import Endpoint, ModelName
from core.schemas import OutputRecord

# --------------------------------------------------------------------------------------------------
# Heuristic flag threshold. Calibration is DEFERRED (CLAUDE.md §4a), so this is a named, documented
# heuristic, not a calibrated cut. It is expressed as a fraction of the series span (0 = same position,
# 1 = opposite ends), which keeps it independent of how many molecules are ranked.
# --------------------------------------------------------------------------------------------------
DISCREPANCY_PCT_FLAG = 0.5  # SFI and log S disagree by > half the series span -> raise the flag


def sfi_soluble_score(sfi: float) -> float:
    """Flip SFI to the common 'higher = more soluble' direction (the inversion the landmine is about).

    SFI is defined LOWER = better (more soluble); log S is HIGHER = better. Negating SFI makes both point
    the same way so they can be co-ranked. This is a direction fix only, NOT a unit conversion: the two
    remain on incompatible scales and are still co-ranked ordinally, never averaged.
    """
    return -float(sfi)


class MoleculeSolubility(BaseModel):
    """One molecule's harmonized solubility read: the two lenses, their series positions, and the flag.

    ``primary_pct`` / ``crosscheck_pct`` are the molecule's normalized position in the series (``0`` = most
    soluble, ``1`` = least) as called by SFI and by log S respectively; ``None`` when that lens is missing.
    ``discrepancy`` is their absolute gap (``None`` unless both lenses are present).
    """

    model_config = ConfigDict(extra="forbid")

    mol_id: str
    sfi: float | None                 # primary lens, LOWER = more soluble
    sfi_soluble_score: float | None   # = -SFI, direction-harmonized (HIGHER = more soluble)
    logs: float | None                # cross-check lens (log S), HIGHER = more soluble
    primary_rank: int | None          # 1 = most soluble by SFI
    crosscheck_rank: int | None       # 1 = most soluble by log S
    primary_pct: float | None         # 0 = most soluble ... 1 = least, by SFI
    crosscheck_pct: float | None      # 0 = most soluble ... 1 = least, by log S
    discrepancy: float | None         # |primary_pct - crosscheck_pct|
    discrepancy_flag: bool            # True iff the SFI-vs-generalist gap is large
    notes: list[str] = Field(default_factory=list)


class EndpointResult(BaseModel):
    """The harmonized solubility result: the series ranked most -> least soluble, plus discrepancy flags.

    Ordered by the PRIMARY lens (SFI); molecules with no SFI are appended, ordered by their log S
    cross-check. The aggregator owns its own result shape (a model/aggregator task may not touch ``core``).
    """

    model_config = ConfigDict(extra="forbid")

    endpoint: Endpoint = Endpoint.solubility
    quantity: str = "relative solubility rank (SFI primary; log S cross-check; higher rank = more soluble)"
    ranking: list[MoleculeSolubility]
    n_molecules: int
    n_ranked: int        # molecules with a usable primary SFI
    n_discrepant: int    # molecules whose SFI-vs-generalist gap raised the flag
    notes: list[str] = Field(default_factory=list)
    deferred: list[str] = Field(default_factory=list)


def _as_output_record(rec: Any) -> OutputRecord:
    """Coerce a dict (or an already-built ``OutputRecord``) into an ``OutputRecord`` for uniform access."""
    if isinstance(rec, OutputRecord):
        return rec
    return OutputRecord.model_validate(rec)


def _extract(records: Sequence[Any]) -> tuple[float | None, float | None]:
    """Pull (SFI, log S) out of one molecule's record bundle. Missing/None lenses come back as ``None``.

    SFI from the ``sfi`` rule (``endpoint_values['SFI']``, LOWER = better); log S from ADMET-AI
    (``endpoint_values['Solubility_AqSolDB']``, HIGHER = better). Any other model in the bundle is ignored.
    """
    sfi: float | None = None
    logs: float | None = None
    for raw in records:
        rec = _as_output_record(raw)
        ev = rec.endpoint_values or {}
        if rec.model == ModelName.sfi and ev.get("SFI") is not None:
            sfi = float(ev["SFI"])  # type: ignore[arg-type]
        elif rec.model == ModelName.admet_ai and ev.get("Solubility_AqSolDB") is not None:
            logs = float(ev["Solubility_AqSolDB"])  # type: ignore[arg-type]
    return sfi, logs


def _normalize_molecules(
    molecules: Mapping[str, Sequence[Any]] | Sequence[Any],
) -> list[tuple[str, list[Any]]]:
    """Normalize the accepted input shapes to ``[(mol_id, records), ...]``.

    Accepts: a Mapping ``{mol_id: records}``; a sequence of ``(mol_id, records)`` pairs; a sequence of
    dicts ``{"mol_id"|"id": ..., "records": [...]}``; or a bare sequence of record-lists (id defaults to a
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
            # a bare record-list for one molecule
            out.append((f"mol_{i}", list(item)))
    return out


def _positions(
    keyed: list[tuple[str, float]],
    *,
    most_soluble_first: bool,
) -> dict[str, tuple[int, float]]:
    """Rank molecules on one lens, returning ``mol_id -> (rank_1based, pct)``.

    ``most_soluble_first`` controls sort direction so both lenses end up with 0 = most soluble: SFI sorts
    ascending (lower = more soluble), log S sorts descending (higher = more soluble). ``pct`` is the
    0..1 position in the series (``idx / (n - 1)``; ``0.0`` for a lone molecule).
    """
    ordered = sorted(keyed, key=lambda kv: kv[1], reverse=not most_soluble_first)
    n = len(ordered)
    out: dict[str, tuple[int, float]] = {}
    for idx, (mid, _val) in enumerate(ordered):
        pct = 0.0 if n == 1 else idx / (n - 1)
        out[mid] = (idx + 1, pct)
    return out


def aggregate(
    molecules: Mapping[str, Sequence[Any]] | Sequence[Any],
) -> EndpointResult:
    """Rank a compound set by relative solubility (SFI primary, log S cross-check), flagging discrepancies.

    ``molecules`` is the set to rank (see ``_normalize_molecules`` for the accepted shapes); each molecule's
    bundle is a list of that molecule's model ``OutputRecord``s. SFI is negated to the common
    'higher = more soluble' direction and used as the primary rank; log S is co-ranked ordinally as the
    cross-check; a wide rank disagreement between them raises the per-molecule discrepancy flag.
    """
    norm = _normalize_molecules(molecules)

    # Per-molecule lens extraction.
    lenses: list[tuple[str, float | None, float | None]] = []
    for mid, recs in norm:
        sfi, logs = _extract(recs)
        lenses.append((mid, sfi, logs))

    # Series positions per lens (only over molecules that actually have that lens).
    sfi_keyed = [(mid, sfi) for mid, sfi, _ in lenses if sfi is not None]
    logs_keyed = [(mid, logs) for mid, _, logs in lenses if logs is not None]
    sfi_pos = _positions(sfi_keyed, most_soluble_first=True)   # ascending: lower SFI = more soluble
    logs_pos = _positions(logs_keyed, most_soluble_first=False)  # descending: higher logS = more soluble

    results: list[MoleculeSolubility] = []
    for mid, sfi, logs in lenses:
        p_rank, p_pct = sfi_pos.get(mid, (None, None))
        c_rank, c_pct = logs_pos.get(mid, (None, None))

        notes: list[str] = []
        if p_pct is not None and c_pct is not None:
            discrepancy: float | None = abs(p_pct - c_pct)
            flag = discrepancy > DISCREPANCY_PCT_FLAG
            if flag:
                notes.append(
                    f"SFI-vs-generalist discrepancy: SFI ranks this molecule at series position "
                    f"{p_pct:.2f} but log S at {c_pct:.2f} (gap {discrepancy:.2f} > {DISCREPANCY_PCT_FLAG})."
                )
        else:
            discrepancy = None
            flag = False
            if sfi is None:
                notes.append("no SFI (primary) lens: molecule not primary-ranked; log S cross-check only.")
            if logs is None:
                notes.append("no log S (generalist) cross-check: discrepancy cannot be computed.")

        results.append(
            MoleculeSolubility(
                mol_id=mid,
                sfi=sfi,
                sfi_soluble_score=None if sfi is None else sfi_soluble_score(sfi),
                logs=logs,
                primary_rank=p_rank,
                crosscheck_rank=c_rank,
                primary_pct=p_pct,
                crosscheck_pct=c_pct,
                discrepancy=discrepancy,
                discrepancy_flag=flag,
                notes=notes,
            )
        )

    # Order the series most -> least soluble by the PRIMARY lens (SFI); molecules with no SFI fall to the
    # end, ordered by their log S cross-check; anything with neither lens goes last.
    def _sort_key(m: MoleculeSolubility) -> tuple[int, float]:
        if m.primary_pct is not None:
            return (0, m.primary_pct)
        if m.crosscheck_pct is not None:
            return (1, m.crosscheck_pct)
        return (2, 0.0)

    results.sort(key=_sort_key)

    notes: list[str] = []
    if not sfi_keyed:
        notes.append("no SFI (primary) lens in the whole set: ranking falls back to the log S cross-check.")
    if not logs_keyed:
        notes.append("no log S (generalist) lens in the whole set: no discrepancy flags can be raised.")

    return EndpointResult(
        ranking=results,
        n_molecules=len(results),
        n_ranked=len(sfi_keyed),
        n_discrepant=sum(1 for r in results if r.discrepancy_flag),
        notes=notes,
        deferred=[
            "rank-gap -> calibrated confidence is DEFERRED (AD/calibration policy); the threshold here is a heuristic.",
            "SFI's internal cLogD carries F-13 (shared pKa) / F-16 (di-cation) placeholders from the sfi adapter.",
        ],
    )
