#!/usr/bin/env python
"""distribution aggregator - TWO independent flags: passive penetration SEPARATE from efflux.

Contract (CLAUDE.md §2, IO_SPEC §2 "distribution / BBB", F-4): the aggregator runs in the core env
(no box, no GPU); it consumes already collected ``OutputRecord``s. Distribution / BBB / CNS is a triage
endpoint, NOT a gate: BBB penetration is desirable, not required, and the real CNS answer is the
experimental Kp,uu. So this module emits two SEPARATE reads that answer two different questions and are
never merged into one score:

    read     signal (model -> field)                       native scale            question
    ----     -----------------------                       ------------            --------
    passive  bbb_score  -> BBB_Score                        0-6 desirability        can it cross passively?
             cns_mpo    -> CNS_MPO                           0-6 desirability
             admet_ai   -> BBB_Martins                       probability [0,1]
             boiled_egg -> BBB_boiled_egg                    bool
    efflux   admet_ai   -> Pgp_Broccatelli (via t28 helper)  probability [0,1]       is it pumped back out?
             watanabe_pgp_brain -> pgp_brain_efflux          NER class (str)
             watanabe_pgp_brain -> Kp_uu_brain               float (brain-to-plasma)

LANDMINE (the entire point of this file - F-4, CLAUDE.md §4): the four passive signals sit on
**incompatible scales** (0-6 desirability vs probability vs boolean). Averaging them is meaningless
(what is the mean of 4.2, 0.83, and True?). So each signal is FIRST mapped, on its own scale, to a
categorical flag (``penetrant`` / ``borderline`` / ``non``), and THEN a plain categorical VOTE resolves
the consensus. No number ever crosses scales; nothing is averaged. The efflux signals are kept in their
own read entirely, because efflux answers a different question than passive penetration: a molecule can
be passively permeant AND heavily effluxed. Merging the two would hide exactly the case that matters.

The categorical cutoffs below (BBB Score >= 4, CNS MPO >= 4, prob bands around 0.5) are literature-
grounded TRIAGE defaults (Gupta 2019 recommends BBB Score > 4; Wager 2010 recommends CNS MPO >= 4);
they are deliberately coarse. The operational, calibrated applicability-domain / decision policy that
would turn these votes into a promote/reject call is DEFERRED (CLAUDE.md §4a): we surface the votes and
the consensus, we do not decide the gate. The real CNS answer is experimental Kp,uu.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.models import Endpoint, ModelName
from core.schemas import OutputRecord
from endpoints.distribution.pgp.pgp import extract_pgp

# --------------------------------------------------------------------------------------------------
# Source field names. These are the ONLY keys this aggregator reads. Each signal is mapped to a
# categorical flag on its OWN scale before any vote; no value is ever combined across scales (F-4).
# --------------------------------------------------------------------------------------------------
BBB_SCORE_KEY = "BBB_Score"          # bbb_score model (t14): 0-6, higher = more likely passive penetrant
CNS_MPO_KEY = "CNS_MPO"              # cns_mpo model (t15): 0-6, higher = more CNS-desirable
BBB_MARTINS_KEY = "BBB_Martins"     # admet_ai (t21): P(BBB penetrant), [0,1]
BBB_BOILED_EGG_KEY = "BBB_boiled_egg"  # boiled_egg model (t16): bool (in the yolk region)

WATANABE_NER_KEY = "pgp_brain_efflux"  # watanabe_pgp_brain SOP (t38): NER class string, e.g. "Low"
WATANABE_KP_UU_KEY = "Kp_uu_brain"     # watanabe_pgp_brain SOP (t38): unbound brain-to-plasma ratio (rat)

# Categorical flag literals (documented values; kept as constants so tests bind to them, not to strings).
PENETRANT = "penetrant"
BORDERLINE = "borderline"
NON = "non"
UNKNOWN = "unknown"

# Efflux-liability flag literals (a separate vocabulary: efflux answers a different question).
HIGH = "high"          # strong efflux liability -> lowers brain penetration
LOW = "low"            # little efflux liability

# Triage cutoffs (coarse, literature-grounded; the calibrated policy is DEFERRED, CLAUDE.md §4a).
BBB_SCORE_PENETRANT = 4.0   # Gupta 2019 recommends BBB Score > 4 for CNS drugs
BBB_SCORE_NON = 2.0         # below this the passive-entry read is unfavorable
CNS_MPO_PENETRANT = 4.0     # Wager 2010/2016 recommends CNS MPO >= 4 as desirable
CNS_MPO_NON = 2.0
PROB_PENETRANT = 0.6        # BBB_Martins band around 0.5 with a borderline margin
PROB_NON = 0.4
PGP_HIGH = 0.6              # Pgp_Broccatelli band around 0.5 with a borderline margin
PGP_LOW = 0.4
KP_UU_PENETRANT = 0.5       # Kp,uu,brain >= 0.5 ~ brain-penetrant heuristic (rat; IO_SPEC §1 #17)

# Watanabe NER class -> efflux-liability flag. The live class labels are confirmed at transcription time
# (t38 SOP README leaves the exact strings a live-page confirmation); we match the documented family of
# labels case-insensitively and record the raw class verbatim so an unmapped label degrades to UNKNOWN.
_NER_HIGH = {"high", "very high"}
_NER_BORDERLINE = {"medium", "moderate", "mid", "intermediate"}
_NER_LOW = {"low", "very low", "none", "no efflux"}


def _as_output_record(rec: Any) -> OutputRecord:
    """Coerce a dict (or an already-built ``OutputRecord``) into an ``OutputRecord`` for uniform access."""
    if isinstance(rec, OutputRecord):
        return rec
    return OutputRecord.model_validate(rec)


class PassiveVote(BaseModel):
    """One passive-penetration signal mapped, on its OWN native scale, to a categorical flag.

    ``scale`` names the native scale ("0-6", "probability", "bool") precisely so the reader can see that
    the flag - not the raw number - is what enters the vote. The raw value is preserved for audit; it is
    NEVER averaged with another signal's raw value (F-4).
    """

    model_config = ConfigDict(extra="forbid")

    model: ModelName
    field: str
    scale: str
    raw_value: float | bool | None
    flag: str            # PENETRANT / BORDERLINE / NON


class PassiveRead(BaseModel):
    """The passive-penetration read: each signal -> a flag, then a categorical VOTE (never an average).

    ``consensus`` is the majority category across the available votes: PENETRANT if penetrant votes
    strictly outnumber non votes, NON if the reverse, otherwise BORDERLINE (a tie, or a borderline-
    dominated set). ``UNKNOWN`` only when no passive signal was present at all. The counts are surfaced
    so the vote is auditable; no number crosses scales anywhere in here.
    """

    model_config = ConfigDict(extra="forbid")

    present: bool
    votes: list[PassiveVote] = Field(default_factory=list)
    n_penetrant: int = 0
    n_borderline: int = 0
    n_non: int = 0
    consensus: str = UNKNOWN
    notes: list[str] = Field(default_factory=list)


class EffluxSignal(BaseModel):
    """One efflux-liability signal mapped to a categorical flag on its own scale (HIGH/BORDERLINE/LOW).

    Direction is unified to "efflux liability": HIGH = more pumped out = LESS brain penetration. The raw
    value / class is preserved; the Watanabe NER read carries the verbatim class string in ``raw_class``.
    """

    model_config = ConfigDict(extra="forbid")

    model: ModelName
    field: str
    scale: str
    raw_value: float | None = None
    raw_class: str | None = None
    flag: str            # HIGH / BORDERLINE / LOW


class EffluxRead(BaseModel):
    """The efflux read, kept ENTIRELY SEPARATE from passive penetration (they answer different questions).

    ``consensus`` votes the efflux-liability signals (Pgp_Broccatelli + Watanabe NER class) the same
    categorical way. ``kp_uu_brain`` is surfaced on its own because it is the closest predicted proxy to
    the real CNS answer (experimental Kp,uu): ``kp_uu_penetrant`` is True when Kp,uu,brain >= 0.5. It is
    NOT folded into the efflux vote - it is a direct penetration read, recorded alongside, not merged.
    """

    model_config = ConfigDict(extra="forbid")

    present: bool
    signals: list[EffluxSignal] = Field(default_factory=list)
    n_high: int = 0
    n_borderline: int = 0
    n_low: int = 0
    consensus: str = UNKNOWN
    kp_uu_brain: float | None = None
    kp_uu_penetrant: bool | None = None
    notes: list[str] = Field(default_factory=list)


class MoleculeDistribution(BaseModel):
    """One molecule's distribution triage: passive penetration and efflux as two SEPARATE labeled reads."""

    model_config = ConfigDict(extra="forbid")

    mol_id: str
    passive: PassiveRead
    efflux: EffluxRead
    notes: list[str] = Field(default_factory=list)


class EndpointResult(BaseModel):
    """The harmonized distribution result: passive-penetration flag and efflux flag kept separate (F-4).

    There is deliberately NO single combined distribution score: passive and efflux answer different
    questions and stay in their own fields. Triage only - BBB is desirable, not a gate; the real answer
    is experimental Kp,uu. The aggregator owns its own result shape (an aggregator task may not touch
    ``core``).
    """

    model_config = ConfigDict(extra="forbid")

    endpoint: Endpoint = Endpoint.distribution
    quantity: str = (
        "TWO separate triage flags: passive-penetration consensus (vote across incompatible-scale "
        "signals, never averaged) and efflux-liability consensus; kept apart (F-4). Not a gate."
    )
    molecules: list[MoleculeDistribution]
    n_molecules: int
    notes: list[str] = Field(default_factory=list)
    deferred: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------------------------------
# Per-scale flag mappers. Each takes ONE signal on its own scale and returns a categorical flag. This is
# the only place a raw value is interpreted; after this point everything is a category and votes count
# categories, so no value ever crosses scales (F-4).
# --------------------------------------------------------------------------------------------------
def _flag_desirability(value: float, penetrant_at: float, non_below: float) -> str:
    """Map a 0-6 desirability score (BBB Score / CNS MPO; higher = more favorable) to a flag."""
    if value >= penetrant_at:
        return PENETRANT
    if value <= non_below:
        return NON
    return BORDERLINE


def _flag_probability(value: float) -> str:
    """Map a P(BBB-penetrant) probability to a flag with a borderline margin around 0.5."""
    if value >= PROB_PENETRANT:
        return PENETRANT
    if value <= PROB_NON:
        return NON
    return BORDERLINE


def _flag_bool(value: bool) -> str:
    """Map the BOILED-Egg BBB boolean (in the yolk region) to a flag. A bool has no borderline state."""
    return PENETRANT if value else NON


def _flag_pgp(value: float) -> str:
    """Map a P(P-gp substrate/inhibitor) probability to an efflux-liability flag (borderline margin)."""
    if value >= PGP_HIGH:
        return HIGH
    if value <= PGP_LOW:
        return LOW
    return BORDERLINE


def _flag_ner(raw_class: str) -> str:
    """Map a Watanabe NER (net efflux ratio) class string to an efflux-liability flag; UNKNOWN if unmapped."""
    key = raw_class.strip().lower()
    if key in _NER_HIGH:
        return HIGH
    if key in _NER_LOW:
        return LOW
    if key in _NER_BORDERLINE:
        return BORDERLINE
    return UNKNOWN


def _vote(flags: Sequence[str], up: str, down: str) -> str:
    """Resolve a categorical consensus from a set of flags without ever touching the raw scales.

    ``up`` outnumbering ``down`` -> ``up``; the reverse -> ``down``; a tie or a BORDERLINE-dominated set
    -> ``BORDERLINE``. ``UNKNOWN`` flags (unmapped labels) do not vote. Empty -> ``UNKNOWN``.
    """
    counted = [f for f in flags if f != UNKNOWN]
    if not counted:
        return UNKNOWN
    n_up = counted.count(up)
    n_down = counted.count(down)
    if n_up > n_down:
        return up
    if n_down > n_up:
        return down
    return BORDERLINE


def _passive_read(records: Sequence[OutputRecord]) -> PassiveRead:
    """Map each passive signal to a flag on its own scale, then vote (never average across scales, F-4)."""
    votes: list[PassiveVote] = []

    for rec in records:
        ev = rec.endpoint_values or {}
        if rec.model == ModelName.bbb_score and ev.get(BBB_SCORE_KEY) is not None:
            v = float(ev[BBB_SCORE_KEY])  # type: ignore[arg-type]
            votes.append(PassiveVote(
                model=ModelName.bbb_score, field=BBB_SCORE_KEY, scale="0-6", raw_value=v,
                flag=_flag_desirability(v, BBB_SCORE_PENETRANT, BBB_SCORE_NON),
            ))
        elif rec.model == ModelName.cns_mpo and ev.get(CNS_MPO_KEY) is not None:
            v = float(ev[CNS_MPO_KEY])  # type: ignore[arg-type]
            votes.append(PassiveVote(
                model=ModelName.cns_mpo, field=CNS_MPO_KEY, scale="0-6", raw_value=v,
                flag=_flag_desirability(v, CNS_MPO_PENETRANT, CNS_MPO_NON),
            ))
        elif rec.model == ModelName.admet_ai and ev.get(BBB_MARTINS_KEY) is not None:
            v = float(ev[BBB_MARTINS_KEY])  # type: ignore[arg-type]
            votes.append(PassiveVote(
                model=ModelName.admet_ai, field=BBB_MARTINS_KEY, scale="probability", raw_value=v,
                flag=_flag_probability(v),
            ))
        elif rec.model == ModelName.boiled_egg and ev.get(BBB_BOILED_EGG_KEY) is not None:
            raw = ev[BBB_BOILED_EGG_KEY]
            b = bool(raw)
            votes.append(PassiveVote(
                model=ModelName.boiled_egg, field=BBB_BOILED_EGG_KEY, scale="bool", raw_value=b,
                flag=_flag_bool(b),
            ))

    if not votes:
        return PassiveRead(
            present=False,
            consensus=UNKNOWN,
            notes=["no passive-penetration signal (bbb_score / cns_mpo / admet_ai / boiled_egg) present."],
        )

    flags = [v.flag for v in votes]
    consensus = _vote(flags, PENETRANT, NON)
    notes = [
        "each signal is mapped to a flag on its OWN scale (0-6 / probability / bool), then a categorical "
        "vote resolves the consensus; raw values are NEVER averaged across scales (F-4).",
        "triage only: BBB penetration is desirable, not a gate; the real CNS answer is experimental Kp,uu.",
    ]
    return PassiveRead(
        present=True,
        votes=votes,
        n_penetrant=flags.count(PENETRANT),
        n_borderline=flags.count(BORDERLINE),
        n_non=flags.count(NON),
        consensus=consensus,
        notes=notes,
    )


def _efflux_read(records: Sequence[OutputRecord]) -> EffluxRead:
    """Build the efflux read, kept ENTIRELY separate from passive penetration (different question, F-4)."""
    signals: list[EffluxSignal] = []
    kp_uu: float | None = None

    for rec in records:
        ev = rec.endpoint_values or {}
        # Pgp_Broccatelli, sourced via the generalists through the t28 derived-pgp helper. The helper
        # returns None unless the record carries a valid [0,1] P-gp probability, so it self-filters which
        # records contribute (only ADMET-AI does).
        pgp = extract_pgp(rec)
        if pgp.value is not None:
            signals.append(EffluxSignal(
                model=rec.model, field=pgp.source_key or "Pgp_Broccatelli", scale="probability",
                raw_value=pgp.value, flag=_flag_pgp(pgp.value),
            ))
        if rec.model == ModelName.watanabe_pgp_brain:
            ner = ev.get(WATANABE_NER_KEY)
            if isinstance(ner, str) and ner.strip():
                signals.append(EffluxSignal(
                    model=ModelName.watanabe_pgp_brain, field=WATANABE_NER_KEY, scale="NER class",
                    raw_class=ner, flag=_flag_ner(ner),
                ))
            kp = ev.get(WATANABE_KP_UU_KEY)
            if kp is not None and not isinstance(kp, bool):
                kp_uu = float(kp)  # type: ignore[arg-type]

    if not signals and kp_uu is None:
        return EffluxRead(
            present=False,
            consensus=UNKNOWN,
            notes=["no efflux signal (Pgp_Broccatelli / Watanabe NER class / Kp,uu,brain) present."],
        )

    flags = [s.flag for s in signals]
    consensus = _vote(flags, HIGH, LOW)
    notes = [
        "efflux is a SEPARATE read from passive penetration (a molecule can be permeant AND effluxed); "
        "the two are never merged into one distribution score (F-4).",
    ]
    if kp_uu is not None:
        notes.append(
            "Kp,uu,brain is the closest predicted proxy to the real CNS answer (experimental Kp,uu); "
            "it is recorded alongside the efflux vote, NOT folded into it."
        )
    return EffluxRead(
        present=True,
        signals=signals,
        n_high=flags.count(HIGH),
        n_borderline=flags.count(BORDERLINE),
        n_low=flags.count(LOW),
        consensus=consensus,
        kp_uu_brain=kp_uu,
        kp_uu_penetrant=None if kp_uu is None else kp_uu >= KP_UU_PENETRANT,
        notes=notes,
    )


def _normalize_molecules(
    molecules: Mapping[str, Sequence[Any]] | Sequence[Any],
) -> list[tuple[str, list[Any]]]:
    """Normalize the accepted input shapes to ``[(mol_id, records), ...]`` (same contract as clearance).

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
            out.append((f"mol_{i}", list(item)))
    return out


def aggregate(
    molecules: Mapping[str, Sequence[Any]] | Sequence[Any],
) -> EndpointResult:
    """Emit two SEPARATE distribution triage flags per molecule: passive penetration and efflux (F-4).

    ``molecules`` is the compound set (see ``_normalize_molecules`` for the accepted shapes); each
    molecule's bundle is a list of its model ``OutputRecord``s. For each molecule the passive signals are
    each mapped to a categorical flag on their own scale and voted (never averaged across the 0-6 /
    probability / bool scales), and the efflux signals are voted separately. The two consensus flags come
    out in their own fields and are never combined into a single distribution score. Triage only: BBB is
    desirable, not a gate; the real CNS answer is experimental Kp,uu.
    """
    norm = _normalize_molecules(molecules)

    mols: list[MoleculeDistribution] = []
    for mid, raw_recs in norm:
        recs = [_as_output_record(r) for r in raw_recs]
        mols.append(
            MoleculeDistribution(
                mol_id=mid,
                passive=_passive_read(recs),
                efflux=_efflux_read(recs),
                notes=[
                    "passive penetration and efflux are kept as SEPARATE flags: they answer different "
                    "questions and are never merged into one distribution number (F-4).",
                ],
            )
        )

    return EndpointResult(
        molecules=mols,
        n_molecules=len(mols),
        notes=[
            "distribution is two separate triage flags (passive penetration vote + efflux vote); the "
            "incompatible-scale passive signals are mapped-then-voted, never averaged (F-4).",
            "triage only: BBB penetration is desirable, not a gate; the real CNS answer is experimental Kp,uu.",
        ],
        deferred=[
            "the operational, calibrated AD / decision policy that would turn these votes into a "
            "promote/reject call is DEFERRED (CLAUDE.md §4a); the categorical cutoffs here are coarse "
            "literature-grounded triage defaults, not a calibrated gate.",
            "the exact live Watanabe NER class labels are confirmed at t38 transcription time; unmapped "
            "labels degrade to 'unknown' and do not vote, rather than being guessed (no-fabricate rule).",
        ],
    )
