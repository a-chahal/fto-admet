#!/usr/bin/env python
"""synthesizability aggregator - an escalating-rigor TIER, never one scalar (the ladder IS the signal).

Contract (task t48, CLAUDE.md §2, IO_SPEC §2 "synthesizability" / §25-27): this endpoint reports a
*tier position on a ladder of escalating rigor*, not a single fused number. The three rungs live on
three different scales and MUST NOT be collapsed into one value (task landmine, IO_SPEC §2):

    rung  model          field (endpoint_values)   scale / direction
    ----  -----          -----------------------   -----------------
    1     sascore        SAscore                    1-10, LOWER = easier to synthesize (INVERTED)
    2     rascore        RAscore                    0-1,  HIGHER = route more likely findable
    3     aizynthfinder  is_solved (+ top_score)    bool, True = a real route search found a route

The ladder is escalating evidence: SAscore is a fast triage screen, RAscore is a machine-learned
"second opinion" on route-findability, AiZynthFinder is a real retrosynthetic route search (the gold
standard). So the tier answers *how far up the rigor ladder synthesizability is confirmed*:

    tier        meaning
    ----        -------
    confirmed   the route search (rung 3) found a route: is_solved == True. Top tier.
    likely      no route search verdict, but RAscore (rung 2) says a route is findable (>= threshold).
    easy        only SAscore (rung 1) available, and it says easy (<= threshold). Fast triage only.
    hard        the highest rung reached says NOT synthesizable (route search found no route, or
                RAscore below threshold, or - if that is all there is - SAscore above threshold).

The raw ladder (SAscore, RAscore, is_solved, top_score) is ALWAYS surfaced alongside the tier so the
reader sees every rung and any disagreement between them: the tier is a summary of the ladder, never a
replacement for it. There is deliberately NO averaging across rungs and NO single fused scalar.

LANDMINES (task t48 / IO_SPEC §2, §25, F-11):
- Different scales - do NOT collapse into one number. Each rung is read on its own scale; the tier is a
  category, not an arithmetic combination.
- SAscore direction is INVERTED: LOWER SAscore = easier. "easy" is SAscore <= SASCORE_EASY_MAX, never
  the reverse. Getting this backwards silently inverts the whole first rung.
- The AiZynthFinder go/no-go key is ``is_solved`` (t32 / F-11), NOT ``solved`` (an internal per-node
  key). This aggregator reads ``is_solved`` only.

The tier thresholds below are documented, named, SOFT screening cutoffs (a 1-10 SAscore and a binary
0-1 RAscore both have natural, sourced decision boundaries). They are triage guidance, not a hard gate;
the consuming decision policy is downstream and out of scope.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.models import Endpoint, ModelName
from core.schemas import OutputRecord

# --------------------------------------------------------------------------------------------------
# The four ladder fields, keyed exactly as the three source adapters write them into endpoint_values.
# These are the ONLY keys this aggregator reads. Kept as named constants so the tests bind to them.
# --------------------------------------------------------------------------------------------------
SASCORE_KEY = "SAscore"      # rung 1, sascore (t20):        float 1-10, LOWER = easier (Ertl 2009)
RASCORE_KEY = "RAscore"      # rung 2, rascore (t31):        float 0-1,  HIGHER = route more findable
IS_SOLVED_KEY = "is_solved"  # rung 3, aizynthfinder (t32):  bool,       True = route search found a route
TOP_SCORE_KEY = "top_score"  # rung 3, aizynthfinder (t32):  float 0-1,  score of the top route (context)

# The models that feed the three rungs. Read by field presence / endpoint membership, never by folder;
# a future model emitting the same fields would feed the same rung (the reader keys off the field names).
SOURCE_MODELS = (ModelName.sascore, ModelName.rascore, ModelName.aizynthfinder)

# Soft, documented screening thresholds (NOT a hard gate; see module docstring).
# SAscore <= 6 is the widely used "readily synthesizable" boundary on the 1-10 Ertl & Schuffenhauer
# scale (scores climb above ~6 for complex/unusual scaffolds). RAscore is a binary route-findability
# classifier, so its natural decision boundary is 0.5 (P(route findable) >= 0.5 -> route is predicted).
SASCORE_EASY_MAX = 6.0
RASCORE_LIKELY_MIN = 0.5


class Tier(StrEnum):
    """The four ladder positions. Ordered by ascending confidence in synthesizability.

    ``hard`` is the one negative verdict (the highest rung reached says NOT synthesizable); ``easy`` /
    ``likely`` / ``confirmed`` are the positive verdicts from rung 1 / 2 / 3 respectively.
    """

    hard = "hard"
    easy = "easy"
    likely = "likely"
    confirmed = "confirmed"


def _as_output_record(rec: Any) -> OutputRecord:
    """Coerce a dict (or an already-built ``OutputRecord``) into an ``OutputRecord`` for uniform access."""
    if isinstance(rec, OutputRecord):
        return rec
    return OutputRecord.model_validate(rec)


class MoleculeSynthesizability(BaseModel):
    """One molecule's synthesizability LADDER: the assigned tier plus every raw rung, surfaced as-is.

    The four rung fields are passed through UNCHANGED (``None`` when a rung did not run). ``tier`` is the
    ladder-position summary; it is ``None`` only when no rung produced a value (nothing to place). The
    rungs are NEVER averaged or fused into one number - the tier is a category derived from the highest
    rung reached, and the raw rungs are kept so any inter-rung disagreement stays visible.
    """

    model_config = ConfigDict(extra="forbid")

    mol_id: str
    present: bool
    tier: Tier | None = None
    SAscore: float | None = None       # rung 1; 1-10, LOWER = easier (inverted)
    RAscore: float | None = None       # rung 2; 0-1, HIGHER = route more likely findable
    is_solved: bool | None = None      # rung 3; True = route search found a route
    top_score: float | None = None     # rung 3; 0-1, top-route score (context, not part of the tier rule)
    notes: list[str] = Field(default_factory=list)


class EndpointResult(BaseModel):
    """The synthesizability result: a per-molecule tier + raw ladder. Deliberately NO single fused scalar.

    There is intentionally no averaged/consensus number anywhere: the payload is the tier (a category)
    and the four raw rung values. The aggregator owns its own result shape (an aggregator task may not
    touch ``core``).
    """

    model_config = ConfigDict(extra="forbid")

    endpoint: Endpoint = Endpoint.synthesizability
    quantity: str = (
        "an escalating-rigor TIER (easy < likely < confirmed; hard = negative), NOT one scalar. Rungs: "
        "SAscore (1-10, LOWER = easier) -> RAscore (0-1, route findable) -> AiZynthFinder is_solved "
        "(route search). The raw ladder is surfaced with the tier; the three scales are never averaged."
    )
    molecules: list[MoleculeSynthesizability]
    n_molecules: int
    notes: list[str] = Field(default_factory=list)


def _assign_tier(
    sascore: float | None,
    rascore: float | None,
    is_solved: bool | None,
) -> tuple[Tier | None, list[str]]:
    """Place a molecule on the ladder from its highest available rung. Returns (tier, notes).

    Escalating rigor: the most rigorous rung that produced a value decides the tier. Rung 3 (a real
    route search) is authoritative when present; else rung 2 (the RAscore classifier); else rung 1
    (the SAscore triage). No rung is averaged into another - each is read on its own scale, and the
    SAscore inversion (LOWER = easier) is honored explicitly.
    """
    notes: list[str] = []

    # Rung 3: AiZynthFinder route search is the gold standard - authoritative when it produced a verdict.
    if is_solved is True:
        notes.append("rung 3 (AiZynthFinder route search) found a route (is_solved=True) -> confirmed.")
        return Tier.confirmed, notes
    if is_solved is False:
        notes.append(
            "rung 3 (AiZynthFinder route search) found NO route within the search budget "
            "(is_solved=False) -> hard. (A search-budget miss, not a proof of impossibility.)"
        )
        return Tier.hard, notes

    # Rung 2: RAscore classifier - P(a synthetic route is findable), HIGHER = more likely synthesizable.
    if rascore is not None:
        if rascore >= RASCORE_LIKELY_MIN:
            notes.append(
                "no route-search verdict; rung 2 (RAscore) >= {0} -> likely (a route is predicted "
                "findable).".format(RASCORE_LIKELY_MIN)
            )
            return Tier.likely, notes
        notes.append(
            "no route-search verdict; rung 2 (RAscore) < {0} -> hard (a route is predicted NOT "
            "findable).".format(RASCORE_LIKELY_MIN)
        )
        return Tier.hard, notes

    # Rung 1: SAscore fast triage - INVERTED, LOWER = easier to synthesize.
    if sascore is not None:
        if sascore <= SASCORE_EASY_MAX:
            notes.append(
                "only rung 1 (SAscore) available; SAscore <= {0} -> easy (LOWER SAscore = easier; "
                "fast triage only, not route-confirmed).".format(SASCORE_EASY_MAX)
            )
            return Tier.easy, notes
        notes.append(
            "only rung 1 (SAscore) available; SAscore > {0} -> hard (LOWER SAscore = easier, so a HIGH "
            "score = harder).".format(SASCORE_EASY_MAX)
        )
        return Tier.hard, notes

    notes.append("no synthesizability rung (SAscore / RAscore / is_solved) present in the bundle.")
    return None, notes


def _read_rung(records: Sequence[OutputRecord], key: str) -> Any:
    """Return the first non-``None`` value for ``key`` across the bundle's ``endpoint_values`` (or None).

    Only one model feeds each rung, so at most one record carries a given key; the first-non-None rule is
    just defensive. Values are read raw and never combined - the ladder is reported, never fused.
    """
    for rec in records:
        ev = rec.endpoint_values or {}
        if ev.get(key) is not None:
            return ev[key]
    return None


def _synth_for(mol_id: str, records: Sequence[OutputRecord]) -> MoleculeSynthesizability:
    """Build one molecule's ladder + tier from its bundle of model records."""
    sa_raw = _read_rung(records, SASCORE_KEY)
    ra_raw = _read_rung(records, RASCORE_KEY)
    solved_raw = _read_rung(records, IS_SOLVED_KEY)
    top_raw = _read_rung(records, TOP_SCORE_KEY)

    sascore = float(sa_raw) if sa_raw is not None else None
    rascore = float(ra_raw) if ra_raw is not None else None
    is_solved = bool(solved_raw) if solved_raw is not None else None
    top_score = float(top_raw) if top_raw is not None else None

    present = any(v is not None for v in (sascore, rascore, is_solved))
    tier, notes = _assign_tier(sascore, rascore, is_solved)
    notes.insert(
        0,
        "TIER, not a scalar (task t48 / IO_SPEC §2): the three rungs live on different scales and are "
        "NEVER averaged. SAscore is INVERTED (LOWER = easier). The raw ladder is surfaced alongside the "
        "tier so every rung and any disagreement stays visible.",
    )

    return MoleculeSynthesizability(
        mol_id=mol_id,
        present=present,
        tier=tier,
        SAscore=sascore,
        RAscore=rascore,
        is_solved=is_solved,
        top_score=top_score,
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
    """Place each molecule on the synthesizability rigor ladder and report its TIER + raw rungs.

    ``molecules`` is the compound set (see ``_normalize_molecules`` for the accepted shapes); each
    molecule's bundle is a list of its model ``OutputRecord``s. For each molecule the four rung fields
    (``SAscore`` / ``RAscore`` / ``is_solved`` / ``top_score``) are read from ``endpoint_values`` and the
    tier is derived from the highest rung reached. The three scales are NEVER averaged into one number:
    the tier is a category and the raw ladder is surfaced with it.
    """
    norm = _normalize_molecules(molecules)
    mols = [_synth_for(mid, [_as_output_record(r) for r in raw_recs]) for mid, raw_recs in norm]

    return EndpointResult(
        molecules=mols,
        n_molecules=len(mols),
        notes=[
            "synthesizability is an escalating-rigor TIER, NOT one scalar: SAscore (1-10, LOWER = easier) "
            "-> RAscore (0-1, route findable) -> AiZynthFinder is_solved (real route search). The ladder "
            "position IS the signal (task t48 / IO_SPEC §2).",
            "the three rungs are on different scales and are never averaged; the raw ladder is surfaced "
            "with the tier. SAscore is INVERTED (LOWER = easier); the AiZynthFinder key is is_solved.",
            "tiers: confirmed (route search found a route) > likely (RAscore predicts a route) > easy "
            "(SAscore triage says easy); hard = the highest rung reached says NOT synthesizable. "
            "Thresholds are soft screening guidance, not a hard gate.",
        ],
    )
