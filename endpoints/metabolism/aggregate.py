#!/usr/bin/env python
"""metabolism aggregator - TWO distinct quantities, not three votes (F-2, CLAUDE.md §4).

Contract (task t42, CLAUDE.md §2, IO_SPEC §2 "metabolism"): the aggregator runs in the core env (no
box, no GPU); it consumes already collected ``OutputRecord``s. The metabolism endpoint answers TWO
DIFFERENT questions that are kept completely separate - conflating them is the exact landmine:

    quantity          question                model -> field                       native scale
    --------          --------                --------------                       ------------
    stability         is it metabolically     admet_ai -> Clearance_Hepatocyte_AZ  uL/min/10^6 cells
    (whole-molecule)  stable?                 admet_ai -> Clearance_Microsome_AZ   uL/min/mg
                                              admetlab3 -> metabolic-stability head (column NEEDS_AARAN)
    site of           WHERE is the soft       smartcyp -> per-atom Score/Ranking   kJ/mol scale (LOWER = SoM)
    metabolism (SoM)  spot?                   fame3r   -> per-atom SoM probability  [0,1] (HIGHER = SoM)
    (per-atom)

LANDMINE F-2 (the entire point of this file, CLAUDE.md §4): SMARTCyp ``Score`` and FAME3R probability
run in OPPOSITE directions on INCOMPATIBLE scales (SMARTCyp lower Score = SoM, on a kJ/mol energy scale;
FAME3R higher probability = SoM, on 0-1). They therefore CANNOT share a numeric scale and must NEVER be
averaged. The only honest common quantity is a per-atom ORDINAL soft-spot ranking aligned on RDKit atom
index: rank each model's atoms on its own scale (1 = most likely SoM), then combine the integer ranks
(rank-sum), never the raw values. This module has no code path that averages a Score with a probability;
it only ever sums ordinal ranks.

Two questions, not three votes (IO_SPEC §2): stability answers *is it stable*, SoM answers *where the
soft spot is*. They are surfaced side by side, never merged. Confidence is the AGREEMENT between the SoM
models on the top atom (the primary, testable flag), cross-referenced with the generalist stability read.

FTO-43 note (CLAUDE.md §4, task t42): SMARTCyp applies a +N-oxidation penalty to the pyrrolidine
tertiary amine N, so it DOWN-ranks N-oxidation there. That is the model's designed behaviour - the
aggregator REFLECTS SMARTCyp's ordinal ranking as emitted; it does not "correct" the penalty.

Qualitative-only / DEFERRED boundaries honored here (CLAUDE.md §4a, F-17; never invented):
- ADMET-AI's two clearance heads are weak (R^2 ~0.26/0.28, F-17), so the stability read is QUALITATIVE
  only: each candidate carries a ``low_weight`` flag and the coarse stability bands below are labeled
  TRIAGE defaults. The operational AD rule / conformal calibration that would turn these into a
  calibrated stability call is DEFERRED.
- The ADMETlab metabolic-stability head is one of ADMETlab 3.0's 119 CSV columns whose LITERAL name (and
  direction) are only knowable from one live ``/api/admetCSV`` call (NEEDS_AARAN, F-6, CLAUDE.md §4). We
  read it through a documented PLACEHOLDER key and never assume its direction; it never feeds a derived
  flag. Replacing the placeholder with the real column literal is a one-line change once captured.
- The two ADMET-AI clearance heads have DIFFERENT units (uL/min/10^6 cells vs uL/min/mg) and are kept as
  separate labeled candidates, never combined - the same discipline as the clearance aggregator (F-3).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.models import Endpoint, ModelName
from core.schemas import OutputRecord

# --------------------------------------------------------------------------------------------------
# STABILITY (whole-molecule) source keys. Units are baked into the labels (each candidate keeps its own
# unit; the two ADMET-AI heads are NEVER combined - different units/matrices, F-3/F-17).
# --------------------------------------------------------------------------------------------------
ADMET_AI_HEPATOCYTE = "Clearance_Hepatocyte_AZ"
ADMET_AI_MICROSOME = "Clearance_Microsome_AZ"
ADMET_AI_HEPATOCYTE_UNIT = "uL/min/10^6 cells"
ADMET_AI_MICROSOME_UNIT = "uL/min/mg"

# ADMETlab metabolic-stability head. The literal column name is one of ADMETlab 3.0's 119 CSV columns
# and is NEEDS_AARAN (F-6): this is a PLACEHOLDER, to be replaced with the captured literal. Its
# direction is likewise unconfirmed, so it is surfaced but NEVER folded into the derived stability flag.
ADMETLAB_STABILITY_KEY = "metabolic_stability"  # PLACEHOLDER - real ADMETlab column literal is NEEDS_AARAN

# Stability direction (for the reads whose direction IS known - the ADMET-AI CLint heads).
STABILITY_DIRECTION = "higher CLint-like value = faster intrinsic clearance = LESS metabolically stable"

# Coarse TRIAGE stability bands (DEFERRED calibration, CLAUDE.md §4a). ADMET-AI clearance is low-weight
# (F-17), so these are qualitative buckets only, not a calibrated CLint call. One band set per unit
# because the two heads live on different scales and are never mixed.
HEPATOCYTE_STABLE_BELOW = 10.0   # uL/min/10^6 cells: below ~ low intrinsic clearance (coarse triage)
HEPATOCYTE_LABILE_ABOVE = 30.0   # uL/min/10^6 cells: above ~ high intrinsic clearance (coarse triage)
MICROSOME_STABLE_BELOW = 10.0    # uL/min/mg (coarse triage)
MICROSOME_LABILE_ABOVE = 40.0    # uL/min/mg (coarse triage)

# STABILITY flag vocabulary.
STABLE = "stable"
LABILE = "labile"
BORDERLINE = "borderline"
UNKNOWN = "unknown"

# --------------------------------------------------------------------------------------------------
# SITE-OF-METABOLISM (per-atom) source keys. Each model ships a per-atom table in ``raw.atoms``; the
# aggregator ranks each model's atoms ORDINALLY on its OWN scale, then co-ranks by rank-sum (never by
# averaging the raw values, F-2).
# --------------------------------------------------------------------------------------------------
RAW_ATOMS_KEY = "atoms"
ATOM_INDEX_KEY = "atom_index"
ATOM_ELEMENT_KEY = "element"

# FAME3R per-atom row (adapter t26): higher probability = more likely SoM.
FAME3R_PROB_KEY = "som_probability"
FAME3R_DIRECTION = "higher SoM probability = more likely site of metabolism"

# SMARTCyp per-atom row (adapter t25, intended schema; the SMARTCyp 3.0 header is re-verified at build
# time, see the smartcyp README). Lower Score (and Ranking == 1) = more likely SoM. ``Ranking`` is the
# model's own ordinal (1 = top site); if present it is used directly, else the ordinal is derived from
# ascending ``Score``.
SMARTCYP_SCORE_KEY = "Score"      # general 3A4 model; LOWER = more likely SoM (kJ/mol scale)
SMARTCYP_RANKING_KEY = "Ranking"  # general 3A4 ordinal; 1 = most likely SoM
SMARTCYP_DIRECTION = "lower Score / Ranking==1 = more likely site of metabolism (OPPOSITE of FAME3R)"

# The two per-atom SoM providers this aggregator co-ranks.
SOM_MODELS = (ModelName.smartcyp, ModelName.fame3r)

# Confidence vocabulary (SoM inter-model agreement is the primary, testable signal).
CONF_HIGH = "high"           # >=2 SoM models present and they agree on the top atom
CONF_LOW = "low"             # >=2 SoM models present and they DISAGREE on the top atom
CONF_SINGLE = "single_model"  # exactly one SoM model present (no cross-check)
CONF_NONE = "none"           # no SoM model present


def _as_output_record(rec: Any) -> OutputRecord:
    """Coerce a dict (or an already-built ``OutputRecord``) into an ``OutputRecord`` for uniform access."""
    if isinstance(rec, OutputRecord):
        return rec
    return OutputRecord.model_validate(rec)


def _f(value: Any) -> float | None:
    """Coerce to a finite float, or None if missing/non-finite."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _i(value: Any) -> int | None:
    """Coerce to an int, or None if missing/non-integral."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------------------------------
# Result schema (the aggregator owns its own shape; an aggregator task may not touch ``core``).
# --------------------------------------------------------------------------------------------------
class StabilityCandidate(BaseModel):
    """One whole-molecule metabolic-stability read, kept as its OWN labeled candidate (never combined).

    Each candidate carries its own ``unit`` so the two ADMET-AI heads (different units/matrices) can never
    be averaged. ``low_weight`` marks the ADMET-AI clearance heads as qualitative only (F-17).
    ``direction_known`` is False for the ADMETlab placeholder head, whose direction is NEEDS_AARAN.
    """

    model_config = ConfigDict(extra="forbid")

    model: ModelName
    field: str
    value: float | None
    unit: str
    direction: str
    direction_known: bool
    low_weight: bool
    note: str | None = None


class StabilityRead(BaseModel):
    """The whole-molecule stability read: labeled candidates + a COARSE qualitative flag (DEFERRED calib.).

    ``flag`` is a coarse triage bucket derived ONLY from the known-direction ADMET-AI CLint heads; the
    ADMETlab placeholder head never feeds it (direction NEEDS_AARAN). It is qualitative, not a calibrated
    stability call.
    """

    model_config = ConfigDict(extra="forbid")

    present: bool
    candidates: list[StabilityCandidate] = Field(default_factory=list)
    flag: str = UNKNOWN
    qualitative: bool = True
    direction: str = STABILITY_DIRECTION
    notes: list[str] = Field(default_factory=list)


class AtomSoM(BaseModel):
    """One atom's ORDINAL site-of-metabolism rank within a single model (1 = most likely SoM).

    ``raw_value`` is the model's native per-atom value (SMARTCyp Score or FAME3R probability) kept for
    audit ONLY. It is NEVER averaged across models: only ``rank`` (an integer ordinal) crosses models.
    """

    model_config = ConfigDict(extra="forbid")

    atom_index: int
    element: str | None = None
    rank: int                    # ordinal within this model (1 = most likely SoM)
    raw_value: float | None = None  # native scale (audit only, never averaged across models)
    raw_field: str               # "Score" (SMARTCyp) / "som_probability" (FAME3R)


class ModelSoMRanking(BaseModel):
    """One model's per-atom SoM table ranked ORDINALLY on its own scale."""

    model_config = ConfigDict(extra="forbid")

    model: ModelName
    present: bool
    direction: str
    atoms: list[AtomSoM] = Field(default_factory=list)
    top_atom_index: int | None = None
    notes: list[str] = Field(default_factory=list)


class SoMConsensus(BaseModel):
    """The per-atom ORDINAL co-rank across the SoM models (rank-sum; never averages raw values, F-2).

    ``consensus_ranking`` is ``[(atom_index, consensus_rank), ...]`` sorted best-first (rank 1 = softest
    spot). ``models_agree`` is True only when every present SoM model shares the same top atom.
    """

    model_config = ConfigDict(extra="forbid")

    present: bool
    per_model: list[ModelSoMRanking] = Field(default_factory=list)
    models_present: list[ModelName] = Field(default_factory=list)
    consensus_ranking: list[tuple[int, int]] = Field(default_factory=list)
    consensus_top_atom_index: int | None = None
    top_atom_by_model: dict[str, int | None] = Field(default_factory=dict)
    models_agree: bool = False
    notes: list[str] = Field(default_factory=list)


class MoleculeMetabolism(BaseModel):
    """One molecule's metabolism read: the TWO quantities (stability + SoM) kept separate + a confidence."""

    model_config = ConfigDict(extra="forbid")

    mol_id: str
    stability: StabilityRead
    som: SoMConsensus
    confidence: str
    confidence_basis: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class EndpointResult(BaseModel):
    """The harmonized metabolism result: two separate quantities per molecule, never merged (F-2)."""

    model_config = ConfigDict(extra="forbid")

    endpoint: Endpoint = Endpoint.metabolism
    quantity: str = (
        "TWO distinct quantities kept separate: (1) whole-molecule metabolic STABILITY (qualitative, "
        "CLint-like, higher = less stable); (2) per-atom ORDINAL site-of-metabolism co-rank aligned on "
        "atom index. SoM never averages SMARTCyp Score with FAME3R probability - only ordinal ranks (F-2)."
    )
    molecules: list[MoleculeMetabolism]
    n_molecules: int
    notes: list[str] = Field(default_factory=list)
    deferred: list[str] = Field(default_factory=list)


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


def _stability_flag(candidates: Sequence[StabilityCandidate]) -> tuple[str, list[str]]:
    """Coarse qualitative stability bucket from the KNOWN-direction ADMET-AI CLint heads only (F-17).

    The ADMETlab placeholder head (direction NEEDS_AARAN) is excluded. Prefers hepatocyte, falls back to
    microsome (own band set - different unit). Returns (flag, notes). Bands are TRIAGE defaults; the
    calibrated rule is DEFERRED (CLAUDE.md §4a).
    """
    notes: list[str] = []

    def band(value: float, stable_below: float, labile_above: float) -> str:
        if value < stable_below:
            return STABLE
        if value > labile_above:
            return LABILE
        return BORDERLINE

    hepatocyte = next(
        (c for c in candidates if c.model == ModelName.admet_ai and c.field == ADMET_AI_HEPATOCYTE and c.value is not None),
        None,
    )
    microsome = next(
        (c for c in candidates if c.model == ModelName.admet_ai and c.field == ADMET_AI_MICROSOME and c.value is not None),
        None,
    )
    if hepatocyte is not None:
        flag = band(hepatocyte.value, HEPATOCYTE_STABLE_BELOW, HEPATOCYTE_LABILE_ABOVE)  # type: ignore[arg-type]
        notes.append(
            f"stability flag '{flag}' from ADMET-AI hepatocyte CLint (coarse triage band, low-weight/"
            "qualitative F-17; calibration DEFERRED)."
        )
        return flag, notes
    if microsome is not None:
        flag = band(microsome.value, MICROSOME_STABLE_BELOW, MICROSOME_LABILE_ABOVE)  # type: ignore[arg-type]
        notes.append(
            f"stability flag '{flag}' from ADMET-AI microsome CLint (coarse triage band, low-weight/"
            "qualitative F-17; calibration DEFERRED)."
        )
        return flag, notes
    notes.append(
        "no known-direction stability read (ADMET-AI CLint) present; stability flag is 'unknown' "
        "(the ADMETlab head direction is NEEDS_AARAN and never drives the flag)."
    )
    return UNKNOWN, notes


def _stability_read(records: Sequence[OutputRecord]) -> StabilityRead:
    """Route the whole-molecule stability signals into labeled candidates (never combined across units)."""
    candidates: list[StabilityCandidate] = []

    for rec in records:
        ev = rec.endpoint_values or {}
        if rec.model == ModelName.admet_ai:
            if ev.get(ADMET_AI_HEPATOCYTE) is not None:
                candidates.append(
                    StabilityCandidate(
                        model=ModelName.admet_ai,
                        field=ADMET_AI_HEPATOCYTE,
                        value=_f(ev[ADMET_AI_HEPATOCYTE]),
                        unit=ADMET_AI_HEPATOCYTE_UNIT,
                        direction=STABILITY_DIRECTION,
                        direction_known=True,
                        low_weight=True,  # F-17: weak head, qualitative only
                    )
                )
            if ev.get(ADMET_AI_MICROSOME) is not None:
                candidates.append(
                    StabilityCandidate(
                        model=ModelName.admet_ai,
                        field=ADMET_AI_MICROSOME,
                        value=_f(ev[ADMET_AI_MICROSOME]),
                        unit=ADMET_AI_MICROSOME_UNIT,
                        direction=STABILITY_DIRECTION,
                        direction_known=True,
                        low_weight=True,  # F-17
                    )
                )
        elif rec.model == ModelName.admetlab3 and ev.get(ADMETLAB_STABILITY_KEY) is not None:
            candidates.append(
                StabilityCandidate(
                    model=ModelName.admetlab3,
                    field=ADMETLAB_STABILITY_KEY,
                    value=_f(ev[ADMETLAB_STABILITY_KEY]),
                    unit="unknown",
                    direction="UNKNOWN - ADMETlab metabolic-stability column literal + direction are NEEDS_AARAN (F-6)",
                    direction_known=False,
                    low_weight=True,
                    note=(
                        "read through a PLACEHOLDER key; the real ADMETlab column literal and its "
                        "direction require one live /api/admetCSV call (NEEDS_AARAN). Surfaced, but "
                        "excluded from the derived stability flag."
                    ),
                )
            )

    if not candidates:
        return StabilityRead(
            present=False,
            candidates=[],
            flag=UNKNOWN,
            notes=["no whole-molecule stability read (admet_ai / admetlab3) present for this molecule."],
        )

    flag, flag_notes = _stability_flag(candidates)
    notes = [
        "stability candidates are kept as SEPARATE labeled reads (different units/matrices); they are "
        "NEVER combined (F-3/F-17). ADMET-AI clearance heads are low-weight/qualitative only.",
        *flag_notes,
    ]
    return StabilityRead(present=True, candidates=candidates, flag=flag, notes=notes)


def _atom_rows(rec: OutputRecord) -> list[dict[str, Any]]:
    """Pull the per-atom table from ``raw.atoms`` (the load-bearing SoM output). Empty if absent/errored."""
    raw = rec.raw or {}
    atoms = raw.get(RAW_ATOMS_KEY)
    if not isinstance(atoms, (list, tuple)):
        return []
    return [a for a in atoms if isinstance(a, Mapping)]


def _order_to_ranking(
    model: ModelName,
    scored: list[tuple[int, str | None, float, str]],
    ascending: bool,
    direction: str,
    notes: list[str],
) -> ModelSoMRanking:
    """Turn ``[(atom_index, element, raw_value, raw_field), ...]`` into an ORDINAL ranking (1 = SoM).

    ``ascending`` True means a LOWER raw value ranks first (SMARTCyp Score); False means a HIGHER raw
    value ranks first (FAME3R probability). Ties share nothing special - broken by atom index for a stable
    order. This is the per-model ordinal; the raw values never leave this function's model.
    """
    if not scored:
        return ModelSoMRanking(model=model, present=False, direction=direction, notes=notes)

    ordered = sorted(scored, key=lambda t: (t[2] if ascending else -t[2], t[0]))
    atoms = [
        AtomSoM(atom_index=idx, element=el, rank=r + 1, raw_value=val, raw_field=field)
        for r, (idx, el, val, field) in enumerate(ordered)
    ]
    return ModelSoMRanking(
        model=model,
        present=True,
        direction=direction,
        atoms=atoms,
        top_atom_index=atoms[0].atom_index,
        notes=notes,
    )


def _fame3r_ranking(rec: OutputRecord) -> ModelSoMRanking:
    """Rank FAME3R atoms by DESCENDING SoM probability (higher = more likely SoM)."""
    scored: list[tuple[int, str | None, float, str]] = []
    for row in _atom_rows(rec):
        idx = _i(row.get(ATOM_INDEX_KEY))
        prob = _f(row.get(FAME3R_PROB_KEY))
        if idx is None or prob is None:
            continue
        el = row.get(ATOM_ELEMENT_KEY)
        scored.append((idx, str(el) if el is not None else None, prob, FAME3R_PROB_KEY))
    notes = [] if scored else ["no usable FAME3R per-atom probabilities in raw.atoms."]
    return _order_to_ranking(ModelName.fame3r, scored, ascending=False, direction=FAME3R_DIRECTION, notes=notes)


def _smartcyp_ranking(rec: OutputRecord) -> ModelSoMRanking:
    """Rank SMARTCyp atoms by ASCENDING Score (lower = more likely SoM); use native Ranking if provided.

    If a row ships SMARTCyp's own ``Ranking`` ordinal (1 = top site), that is authoritative and used
    directly; otherwise the ordinal is derived from ascending ``Score``. The +N-oxidation penalty on
    FTO-43's pyrrolidine N is already folded into ``Score`` upstream - this reflects it, never corrects it.
    """
    rows = _atom_rows(rec)

    # Prefer the model's native Ranking ordinal when every usable row carries one.
    native: list[tuple[int, str | None, int]] = []
    score_scored: list[tuple[int, str | None, float, str]] = []
    for row in rows:
        idx = _i(row.get(ATOM_INDEX_KEY))
        if idx is None:
            continue
        el = row.get(ATOM_ELEMENT_KEY)
        el_s = str(el) if el is not None else None
        ranking = _i(row.get(SMARTCYP_RANKING_KEY))
        score = _f(row.get(SMARTCYP_SCORE_KEY))
        if ranking is not None:
            native.append((idx, el_s, ranking))
        if score is not None:
            score_scored.append((idx, el_s, score, SMARTCYP_SCORE_KEY))

    if native and len(native) == len([r for r in rows if _i(r.get(ATOM_INDEX_KEY)) is not None]):
        ordered = sorted(native, key=lambda t: (t[2], t[0]))
        # Re-index to a dense 1..n ordinal (SMARTCyp Ranking may skip atoms it does not rank).
        atoms = [
            AtomSoM(atom_index=idx, element=el, rank=r + 1, raw_value=float(native_rank), raw_field=SMARTCYP_RANKING_KEY)
            for r, (idx, el, native_rank) in enumerate(ordered)
        ]
        return ModelSoMRanking(
            model=ModelName.smartcyp,
            present=True,
            direction=SMARTCYP_DIRECTION,
            atoms=atoms,
            top_atom_index=atoms[0].atom_index,
            notes=["ordinal taken from SMARTCyp's native Ranking column (1 = top SoM)."],
        )

    notes = [] if score_scored else ["no usable SMARTCyp per-atom Score/Ranking in raw.atoms."]
    return _order_to_ranking(
        ModelName.smartcyp, score_scored, ascending=True, direction=SMARTCYP_DIRECTION, notes=notes
    )


def _consensus(rankings: Sequence[ModelSoMRanking]) -> SoMConsensus:
    """Co-rank the SoM models ORDINALLY by rank-sum over the union of atoms (never averages raw values).

    Each present model contributes an integer ordinal per atom (1 = most likely SoM). An atom a model did
    not rank is assigned that model's worst rank + 1 (so a soft spot only one model saw is penalized, not
    dropped). Atoms are then sorted by ascending rank-sum; ties (equal rank-sum) SHARE a consensus rank
    (competition ranking). This is the only cross-model operation, and it is purely on integer ranks.
    """
    present = [r for r in rankings if r.present and r.atoms]
    top_by_model = {r.model.value: r.top_atom_index for r in rankings if r.present}

    if not present:
        return SoMConsensus(
            present=False,
            per_model=list(rankings),
            models_present=[],
            top_atom_by_model=top_by_model,
            notes=["no SoM model (smartcyp / fame3r) produced a per-atom ranking for this molecule."],
        )

    rank_maps = [{a.atom_index: a.rank for a in r.atoms} for r in present]
    worsts = [max(rm.values()) + 1 for rm in rank_maps]
    all_atoms = sorted({idx for rm in rank_maps for idx in rm})

    rank_sums = [(idx, sum(rm.get(idx, worsts[i]) for i, rm in enumerate(rank_maps))) for idx in all_atoms]
    rank_sums.sort(key=lambda t: (t[1], t[0]))

    # Competition ranking: equal rank-sum -> equal consensus rank.
    consensus: list[tuple[int, int]] = []
    prev_sum: int | None = None
    prev_rank = 0
    for position, (idx, s) in enumerate(rank_sums):
        rank = prev_rank if s == prev_sum else position + 1
        consensus.append((idx, rank))
        prev_sum, prev_rank = s, rank

    tops = [r.top_atom_index for r in present]
    models_agree = len(present) >= 2 and len(set(tops)) == 1

    notes = [
        "SoM consensus is an ORDINAL rank-sum aligned on atom index; SMARTCyp Score and FAME3R "
        "probability are NEVER averaged - only their integer per-model ranks are summed (F-2).",
    ]
    if len(present) >= 2:
        notes.append(
            f"SoM models {'AGREE' if models_agree else 'DISAGREE'} on the top atom "
            f"(top by model: {top_by_model})."
        )

    return SoMConsensus(
        present=True,
        per_model=list(rankings),
        models_present=[r.model for r in present],
        consensus_ranking=consensus,
        consensus_top_atom_index=consensus[0][0] if consensus else None,
        top_atom_by_model=top_by_model,
        models_agree=models_agree,
        notes=notes,
    )


def _confidence(stability: StabilityRead, som: SoMConsensus) -> tuple[str, list[str]]:
    """Confidence = SoM inter-model AGREEMENT (primary), cross-referenced with the stability read.

    Primary, testable signal: do the two SoM models agree on the top atom? >=2 agree -> high; >=2
    disagree -> low; exactly one -> single_model; none -> none. The generalist stability read is then
    cross-referenced qualitatively (does 'labile' line up with a found soft spot?) as a secondary note,
    without a fabricated numeric threshold (CLAUDE.md §4a).
    """
    n = len(som.models_present)
    if n == 0:
        return CONF_NONE, ["no SoM model present; confidence is 'none'."]
    if n == 1:
        conf = CONF_SINGLE
        basis = [f"only one SoM model ({som.models_present[0].value}) present; no cross-check (single_model)."]
    elif som.models_agree:
        conf = CONF_HIGH
        basis = ["the SoM models AGREE on the top atom -> high confidence in the soft-spot call."]
    else:
        conf = CONF_LOW
        basis = ["the SoM models DISAGREE on the top atom -> low confidence (raises the confidence flag)."]

    # Secondary, qualitative cross-reference with the whole-molecule stability read.
    if stability.present and stability.flag != UNKNOWN:
        if stability.flag == LABILE:
            basis.append(
                f"generalist stability read is '{LABILE}' and a SoM soft spot is identified -> the two "
                "quantities are consistent (a metabolic liability with a located site)."
            )
        elif stability.flag == STABLE:
            basis.append(
                f"generalist stability read is '{STABLE}' while a SoM soft spot is still ranked -> "
                "qualitatively divergent reads (stable whole-molecule vs a nominal soft spot); treat with care."
            )
        else:
            basis.append(f"generalist stability read is '{stability.flag}' (coarse triage; qualitative).")
    else:
        basis.append("no known-direction stability read to cross-reference the SoM finding against.")

    return conf, basis


def aggregate(
    molecules: Mapping[str, Sequence[Any]] | Sequence[Any],
) -> EndpointResult:
    """Harmonize a compound set's metabolism into TWO separate quantities per molecule (never merged, F-2).

    ``molecules`` is the set (see ``_normalize_molecules`` for the accepted shapes); each molecule's bundle
    is a list of its model ``OutputRecord``s. For each molecule: (1) the whole-molecule stability signals
    are routed into labeled, never-combined candidates plus a coarse qualitative flag; (2) the SMARTCyp and
    FAME3R per-atom tables are each ranked ORDINALLY on their own scale and co-ranked by rank-sum aligned on
    atom index - the raw Score and probability are never averaged (F-2). Confidence is the SoM inter-model
    agreement, cross-referenced with the stability read.
    """
    norm = _normalize_molecules(molecules)

    mols: list[MoleculeMetabolism] = []
    for mid, raw_recs in norm:
        recs = [_as_output_record(r) for r in raw_recs]
        stability = _stability_read(recs)

        rankings: list[ModelSoMRanking] = []
        for rec in recs:
            if rec.model == ModelName.fame3r:
                rankings.append(_fame3r_ranking(rec))
            elif rec.model == ModelName.smartcyp:
                rankings.append(_smartcyp_ranking(rec))
        som = _consensus(rankings)

        confidence, basis = _confidence(stability, som)
        mols.append(
            MoleculeMetabolism(
                mol_id=mid,
                stability=stability,
                som=som,
                confidence=confidence,
                confidence_basis=basis,
                notes=[
                    "metabolism is TWO quantities kept separate: whole-molecule stability (is it stable) "
                    "and per-atom SoM (where the soft spot is); they are never merged (F-2, IO_SPEC §2).",
                ],
            )
        )

    return EndpointResult(
        molecules=mols,
        n_molecules=len(mols),
        notes=[
            "metabolism endpoint answers TWO questions, not three votes: stability vs site-of-metabolism.",
            "SoM co-rank is ORDINAL (rank-sum on atom index); SMARTCyp Score and FAME3R probability are "
            "never averaged - opposite directions on incompatible scales (F-2, CLAUDE.md §4).",
        ],
        deferred=[
            "the operational AD rule / conformal calibration that would turn the low-weight ADMET-AI "
            "clearance heads and the coarse stability bands into a calibrated stability call is DEFERRED "
            "(CLAUDE.md §4a); the bands here are qualitative triage defaults only.",
            "the ADMETlab metabolic-stability head is read through a PLACEHOLDER key; its real 119-CSV "
            "column literal and direction are NEEDS_AARAN (one live /api/admetCSV call, F-6). It is "
            "surfaced but never feeds the derived stability flag until the literal is captured.",
            "the SMARTCyp 3.0 (Python/RDKit) per-atom output header is re-verified at build time (smartcyp "
            "adapter t25 is BLOCKED); this aggregator consumes the documented intended raw.atoms schema "
            "(atom_index + Score/Ranking) and maps from that.",
        ],
    )
