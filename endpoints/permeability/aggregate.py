#!/usr/bin/env python
"""permeability aggregator - TWO independent flags: a permeability flag and an absorption flag.

Contract (task t46, CLAUDE.md §2, IO_SPEC §2 "permeability (aggregate-only)", §1 #23): this endpoint
has NO model of its own (no ``ModelName`` maps to it). It runs in the core env (no box, no GPU) and
consumes fields already emitted by the cross-cutting generalists plus the BOILED-Egg HIA boolean. It
answers two DIFFERENT questions and emits them as two SEPARATE flags, never merged into one scalar:

    read          signal (model -> field)               native scale          question
    ----          -----------------------               ------------          --------
    permeability  admet_ai -> Caco2_Wang                 log Papp (cm/s, log)  does it cross a membrane?
                  admet_ai -> PAMPA_NCATS                probability [0,1]
                  admet_ai -> Pgp_Broccatelli (efflux)   probability [0,1]     (surfaced apart, see below)
    absorption    admet_ai -> HIA_Hou                    probability [0,1]     does it get absorbed orally?
                  boiled_egg -> HIA_boiled_egg           bool
                  admet_ai -> Bioavailability_Ma / %F    probability [0,1]     (SUSPECT, does not vote)

Design mirrors the distribution aggregator (t44) deliberately, because the same landmine applies: the
contributing signals sit on INCOMPATIBLE scales (log Papp vs probability vs boolean). Averaging them is
meaningless (what is the mean of -5.4, 0.82, and True?). So each signal is FIRST mapped, on its own
scale, to a categorical flag, and THEN a plain categorical VOTE resolves the consensus. No number ever
crosses scales; nothing is averaged; there is no single fabricated permeability scalar.

Two landmines specific to this endpoint (task t46, IO_SPEC §1 #23):
- ``Bioavailability_Ma`` / %F is a WEAK predictor - "treat with suspicion, don't let it dominate". It is
  therefore DOWN-WEIGHTED to zero in the absorption vote: its flag is computed and surfaced (with a
  ``suspect=True`` marker and a note), but it is kept out of the vote counts entirely so it can never
  swing the absorption consensus. It is context, not a vote.
- Efflux (``Pgp_Broccatelli``) is a DIFFERENT axis from intrinsic membrane permeability: a molecule can
  be intrinsically permeable AND heavily effluxed. So it is surfaced as its own labeled signal inside
  the permeability read (an efflux-liability flag), NOT averaged into the passive-permeability vote.
  Turning "intrinsic permeability minus efflux = net permeability" into a number is an operational,
  calibrated decision that is DEFERRED (CLAUDE.md §4a); we surface both, we do not compute net flux.

The categorical cutoffs below (Caco2 log Papp bands, probability bands around 0.5) are coarse,
literature-grounded TRIAGE defaults; the operational, calibrated AD / decision policy is DEFERRED
(CLAUDE.md §4a). And this whole endpoint may be partly moot for FTO-43 if delivery is intratumoral /
osmotic-pump rather than oral (IO_SPEC §1 #23) - it is a triage read, not a gate.
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
# categorical flag on its OWN scale before any vote; no value is ever combined across scales.
# --------------------------------------------------------------------------------------------------
CACO2_KEY = "Caco2_Wang"            # admet_ai (t21): Caco-2 permeability, log Papp (cm/s), higher = more permeable
PAMPA_KEY = "PAMPA_NCATS"           # admet_ai (t21): P(PAMPA-permeable), [0,1]
HIA_HOU_KEY = "HIA_Hou"             # admet_ai (t21): P(human intestinal absorption), [0,1]
BIOAVAIL_KEY = "Bioavailability_Ma"  # admet_ai (t21): P(orally bioavailable) / %F - WEAK, suspect (does not vote)
HIA_BOILED_EGG_KEY = "HIA_boiled_egg"  # boiled_egg model (t16): bool (in the white/GI-absorption region)
# Pgp_Broccatelli (efflux) is read through the shared t28 derived-pgp helper, not by a literal key here.

# Permeability flag literals (kept as constants so tests bind to them, not to raw strings).
PERMEABLE = "permeable"
ABSORBED = "absorbed"
NON = "non"
BORDERLINE = "borderline"
UNKNOWN = "unknown"

# Efflux-liability flag literals (a separate vocabulary: efflux answers a different question).
HIGH = "high"          # strong efflux liability -> lowers NET permeability / absorption
LOW = "low"            # little efflux liability

# Triage cutoffs (coarse, literature-grounded; the calibrated policy is DEFERRED, CLAUDE.md §4a).
# Caco2_Wang is log10 Papp in cm/s. A common high/low split is Papp ~7e-6 cm/s (log ~ -5.15) = permeable,
# Papp ~1e-6 cm/s (log = -6.0) = poorly permeable; between them is borderline. Direction: higher = more permeable.
CACO2_PERMEABLE = -5.15
CACO2_NON = -6.0
PROB_HIGH = 0.6        # probability band around 0.5 with a borderline margin (HIA_Hou / PAMPA / %F)
PROB_LOW = 0.4
PGP_HIGH = 0.6         # Pgp_Broccatelli band around 0.5 with a borderline margin
PGP_LOW = 0.4


def _as_output_record(rec: Any) -> OutputRecord:
    """Coerce a dict (or an already-built ``OutputRecord``) into an ``OutputRecord`` for uniform access."""
    if isinstance(rec, OutputRecord):
        return rec
    return OutputRecord.model_validate(rec)


class PermVote(BaseModel):
    """One passive-permeability signal mapped, on its OWN native scale, to a categorical flag.

    ``scale`` names the native scale ("log Papp" / "probability") precisely so the reader can see that the
    flag - not the raw number - is what enters the vote. The raw value is preserved for audit; it is NEVER
    averaged with another signal's raw value (incompatible scales).
    """

    model_config = ConfigDict(extra="forbid")

    model: ModelName
    field: str
    scale: str
    raw_value: float | bool | None
    flag: str            # PERMEABLE / BORDERLINE / NON


class EffluxSignal(BaseModel):
    """The efflux-liability signal (Pgp_Broccatelli), surfaced apart from the passive-permeability vote.

    Direction is "efflux liability": HIGH = more pumped out = LESS net permeability / absorption. It is a
    DIFFERENT axis than intrinsic permeability, so it is recorded alongside the permeability vote, never
    folded into it (computing net flux is a DEFERRED calibrated decision).
    """

    model_config = ConfigDict(extra="forbid")

    model: ModelName
    field: str
    scale: str
    raw_value: float | None
    flag: str            # HIGH / BORDERLINE / LOW


class SuspectSignal(BaseModel):
    """A weak, down-weighted signal (``Bioavailability_Ma`` / %F): flagged and surfaced, but it does NOT vote.

    The landmine (task t46, IO_SPEC §1 #23): %F / Bioavailability_Ma is a poor predictor - "treat with
    suspicion, don't let it dominate". So its flag is computed for context but ``suspect`` is True and it
    is kept entirely out of the absorption vote counts, so it can never swing the consensus.
    """

    model_config = ConfigDict(extra="forbid")

    model: ModelName
    field: str
    scale: str
    raw_value: float | None
    flag: str
    suspect: bool = True


class PermeabilityRead(BaseModel):
    """The permeability read: passive-permeability signals -> flags -> a categorical VOTE (never averaged).

    ``consensus`` is the majority category across the passive-permeability votes (Caco2 + PAMPA):
    PERMEABLE if permeable votes strictly outnumber non votes, NON if the reverse, otherwise BORDERLINE.
    Efflux (Pgp_Broccatelli) is surfaced in ``efflux`` / ``efflux_consensus`` as its OWN read, never
    folded into the permeability consensus (different axis). ``UNKNOWN`` when no passive signal is present.
    """

    model_config = ConfigDict(extra="forbid")

    present: bool
    votes: list[PermVote] = Field(default_factory=list)
    n_permeable: int = 0
    n_borderline: int = 0
    n_non: int = 0
    consensus: str = UNKNOWN
    efflux: list[EffluxSignal] = Field(default_factory=list)
    efflux_consensus: str = UNKNOWN
    notes: list[str] = Field(default_factory=list)


class AbsorptionRead(BaseModel):
    """The absorption read: HIA_Hou + BOILED-Egg HIA -> flags -> a categorical VOTE; %F is suspect, no vote.

    ``consensus`` votes only the trusted absorption signals (HIA_Hou probability + BOILED-Egg HIA bool).
    ``suspect_signals`` carries ``Bioavailability_Ma`` / %F, flagged but DOWN-WEIGHTED out of the vote so
    it cannot dominate (task t46 landmine). ``UNKNOWN`` when no trusted signal votes.
    """

    model_config = ConfigDict(extra="forbid")

    present: bool
    votes: list[PermVote] = Field(default_factory=list)
    n_absorbed: int = 0
    n_borderline: int = 0
    n_non: int = 0
    consensus: str = UNKNOWN
    suspect_signals: list[SuspectSignal] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class MoleculePermeability(BaseModel):
    """One molecule's permeability triage: a permeability flag and an absorption flag as SEPARATE reads."""

    model_config = ConfigDict(extra="forbid")

    mol_id: str
    permeability: PermeabilityRead
    absorption: AbsorptionRead
    notes: list[str] = Field(default_factory=list)


class EndpointResult(BaseModel):
    """The harmonized permeability result: a permeability flag and an absorption flag, kept separate.

    There is deliberately NO single combined permeability scalar: permeability and absorption answer
    different questions and stay in their own fields. Triage only - and possibly partly moot for FTO-43
    given intratumoral / osmotic-pump delivery (IO_SPEC §1 #23). The aggregator owns its own result shape
    (an aggregator task may not touch ``core``).
    """

    model_config = ConfigDict(extra="forbid")

    endpoint: Endpoint = Endpoint.permeability
    quantity: str = (
        "TWO separate triage flags: a permeability-consensus flag (vote across incompatible-scale signals, "
        "never averaged) and an absorption-consensus flag (%F down-weighted out of the vote); kept apart. "
        "No single permeability scalar. Not a gate; possibly partly moot given intratumoral delivery."
    )
    molecules: list[MoleculePermeability]
    n_molecules: int
    notes: list[str] = Field(default_factory=list)
    deferred: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------------------------------
# Per-scale flag mappers. Each takes ONE signal on its own scale and returns a categorical flag. This is
# the only place a raw value is interpreted; after this point everything is a category and votes count
# categories, so no value ever crosses scales.
# --------------------------------------------------------------------------------------------------
def _flag_logpapp(value: float) -> str:
    """Map a Caco2_Wang log Papp (cm/s, higher = more permeable) to a permeability flag."""
    if value >= CACO2_PERMEABLE:
        return PERMEABLE
    if value <= CACO2_NON:
        return NON
    return BORDERLINE


def _flag_probability(value: float, positive: str) -> str:
    """Map a probability (higher = more of ``positive``) to a flag with a borderline margin around 0.5."""
    if value >= PROB_HIGH:
        return positive
    if value <= PROB_LOW:
        return NON
    return BORDERLINE


def _flag_bool(value: bool, positive: str) -> str:
    """Map a boolean (BOILED-Egg HIA) to a flag. A bool has no borderline state."""
    return positive if value else NON


def _flag_pgp(value: float) -> str:
    """Map a P(P-gp substrate/inhibitor) probability to an efflux-liability flag (borderline margin)."""
    if value >= PGP_HIGH:
        return HIGH
    if value <= PGP_LOW:
        return LOW
    return BORDERLINE


def _vote(flags: Sequence[str], up: str, down: str) -> str:
    """Resolve a categorical consensus from a set of flags without ever touching the raw scales.

    ``up`` outnumbering ``down`` -> ``up``; the reverse -> ``down``; a tie or a BORDERLINE-dominated set
    -> ``BORDERLINE``. ``UNKNOWN`` flags do not vote. Empty -> ``UNKNOWN``.
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


def _permeability_read(records: Sequence[OutputRecord]) -> PermeabilityRead:
    """Map each passive-permeability signal to a flag on its own scale, then vote; surface efflux apart."""
    votes: list[PermVote] = []
    efflux: list[EffluxSignal] = []

    for rec in records:
        ev = rec.endpoint_values or {}
        if rec.model == ModelName.admet_ai and ev.get(CACO2_KEY) is not None:
            v = float(ev[CACO2_KEY])  # type: ignore[arg-type]
            votes.append(PermVote(
                model=ModelName.admet_ai, field=CACO2_KEY, scale="log Papp", raw_value=v,
                flag=_flag_logpapp(v),
            ))
        if rec.model == ModelName.admet_ai and ev.get(PAMPA_KEY) is not None:
            v = float(ev[PAMPA_KEY])  # type: ignore[arg-type]
            votes.append(PermVote(
                model=ModelName.admet_ai, field=PAMPA_KEY, scale="probability", raw_value=v,
                flag=_flag_probability(v, PERMEABLE),
            ))
        # Efflux (Pgp_Broccatelli) via the shared t28 derived-pgp helper. It returns None unless the record
        # carries a valid [0,1] P-gp probability, so it self-filters which records contribute.
        pgp = extract_pgp(rec)
        if pgp.value is not None:
            efflux.append(EffluxSignal(
                model=rec.model, field=pgp.source_key or "Pgp_Broccatelli", scale="probability",
                raw_value=pgp.value, flag=_flag_pgp(pgp.value),
            ))

    if not votes and not efflux:
        return PermeabilityRead(
            present=False,
            consensus=UNKNOWN,
            efflux_consensus=UNKNOWN,
            notes=["no permeability signal (Caco2_Wang / PAMPA_NCATS / Pgp_Broccatelli) present."],
        )

    flags = [v.flag for v in votes]
    consensus = _vote(flags, PERMEABLE, NON) if votes else UNKNOWN
    efflux_consensus = _vote([s.flag for s in efflux], HIGH, LOW)
    notes = [
        "each passive-permeability signal is mapped to a flag on its OWN scale (log Papp / probability), "
        "then a categorical vote resolves the consensus; raw values are NEVER averaged across scales.",
        "triage only, and possibly partly moot for FTO-43 given intratumoral / osmotic-pump delivery.",
    ]
    if efflux:
        notes.append(
            "efflux (Pgp_Broccatelli) is a DIFFERENT axis than intrinsic permeability - a molecule can be "
            "permeable AND effluxed - so it is surfaced separately, never folded into the permeability vote "
            "(net flux = intrinsic minus efflux is a DEFERRED calibrated decision)."
        )
    return PermeabilityRead(
        present=True,
        votes=votes,
        n_permeable=flags.count(PERMEABLE),
        n_borderline=flags.count(BORDERLINE),
        n_non=flags.count(NON),
        consensus=consensus,
        efflux=efflux,
        efflux_consensus=efflux_consensus,
        notes=notes,
    )


def _absorption_read(records: Sequence[OutputRecord]) -> AbsorptionRead:
    """Vote HIA_Hou + BOILED-Egg HIA; keep %F (Bioavailability_Ma) as a SUSPECT, down-weighted, non-voting read."""
    votes: list[PermVote] = []
    suspect: list[SuspectSignal] = []

    for rec in records:
        ev = rec.endpoint_values or {}
        if rec.model == ModelName.admet_ai and ev.get(HIA_HOU_KEY) is not None:
            v = float(ev[HIA_HOU_KEY])  # type: ignore[arg-type]
            votes.append(PermVote(
                model=ModelName.admet_ai, field=HIA_HOU_KEY, scale="probability", raw_value=v,
                flag=_flag_probability(v, ABSORBED),
            ))
        if rec.model == ModelName.boiled_egg and ev.get(HIA_BOILED_EGG_KEY) is not None:
            raw = ev[HIA_BOILED_EGG_KEY]
            b = bool(raw)
            votes.append(PermVote(
                model=ModelName.boiled_egg, field=HIA_BOILED_EGG_KEY, scale="bool", raw_value=b,
                flag=_flag_bool(b, ABSORBED),
            ))
        # Bioavailability_Ma / %F: WEAK - flag with suspicion, DO NOT let it vote (task t46 landmine).
        if rec.model == ModelName.admet_ai and ev.get(BIOAVAIL_KEY) is not None:
            v = float(ev[BIOAVAIL_KEY])  # type: ignore[arg-type]
            suspect.append(SuspectSignal(
                model=ModelName.admet_ai, field=BIOAVAIL_KEY, scale="probability", raw_value=v,
                flag=_flag_probability(v, ABSORBED),
            ))

    if not votes and not suspect:
        return AbsorptionRead(
            present=False,
            consensus=UNKNOWN,
            notes=["no absorption signal (HIA_Hou / BOILED-Egg HIA / Bioavailability_Ma) present."],
        )

    flags = [v.flag for v in votes]
    consensus = _vote(flags, ABSORBED, NON) if votes else UNKNOWN
    notes = [
        "HIA_Hou (probability) and BOILED-Egg HIA (bool) are each mapped to a flag on their own scale, "
        "then voted; raw values are NEVER averaged across scales.",
    ]
    if suspect:
        notes.append(
            "Bioavailability_Ma / %F is a WEAK predictor (task t46 landmine): its flag is surfaced for "
            "context but it is DOWN-WEIGHTED out of the vote so it cannot dominate the absorption consensus."
        )
    if votes == [] and suspect:
        notes.append("only the weak %F signal was present; it does not vote, so the consensus is UNKNOWN.")
    return AbsorptionRead(
        present=True,
        votes=votes,
        n_absorbed=flags.count(ABSORBED),
        n_borderline=flags.count(BORDERLINE),
        n_non=flags.count(NON),
        consensus=consensus,
        suspect_signals=suspect,
        notes=notes,
    )


def _normalize_molecules(
    molecules: Mapping[str, Sequence[Any]] | Sequence[Any],
) -> list[tuple[str, list[Any]]]:
    """Normalize the accepted input shapes to ``[(mol_id, records), ...]`` (same contract as distribution).

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
    """Emit two SEPARATE permeability triage flags per molecule: a permeability flag and an absorption flag.

    ``molecules`` is the compound set (see ``_normalize_molecules`` for the accepted shapes); each
    molecule's bundle is a list of its model ``OutputRecord``s. For each molecule the passive-permeability
    signals (Caco2 + PAMPA) are each mapped to a categorical flag on their own scale and voted (never
    averaged across the log-Papp / probability scales), with efflux (Pgp_Broccatelli) surfaced separately;
    and the absorption signals (HIA_Hou + BOILED-Egg HIA) are voted, with %F down-weighted out of the vote.
    The two consensus flags come out in their own fields and are never combined into a single scalar.
    Triage only, and possibly partly moot for FTO-43 given intratumoral / osmotic-pump delivery.
    """
    norm = _normalize_molecules(molecules)

    mols: list[MoleculePermeability] = []
    for mid, raw_recs in norm:
        recs = [_as_output_record(r) for r in raw_recs]
        mols.append(
            MoleculePermeability(
                mol_id=mid,
                permeability=_permeability_read(recs),
                absorption=_absorption_read(recs),
                notes=[
                    "permeability and absorption are kept as SEPARATE flags: they answer different "
                    "questions and are never merged into one permeability number.",
                ],
            )
        )

    return EndpointResult(
        molecules=mols,
        n_molecules=len(mols),
        notes=[
            "permeability is two separate triage flags (a permeability vote + an absorption vote); the "
            "incompatible-scale signals are mapped-then-voted, never averaged; no single scalar.",
            "efflux (Pgp_Broccatelli) is surfaced apart from the passive-permeability vote (different axis).",
            "triage only, and possibly partly moot for FTO-43 given intratumoral / osmotic-pump delivery.",
        ],
        deferred=[
            "the operational, calibrated AD / decision policy that would turn these votes into a "
            "promote/reject call is DEFERRED (CLAUDE.md §4a); the categorical cutoffs here are coarse "
            "literature-grounded triage defaults, not a calibrated gate.",
            "combining intrinsic permeability and efflux into a single NET-flux number is a DEFERRED "
            "calibrated decision; the two axes are surfaced separately, never merged.",
        ],
    )
