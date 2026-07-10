#!/usr/bin/env python
"""hERG / cardiotoxicity gate aggregator - harmonization layer + PROVISIONAL (uncalibrated) flag.

hERG is the pipeline's PRIMARY go/no-go gate (IO_SPEC §2 "hERG (GATE)"). The settled philosophy is
"harmonize every contributing read onto a common P(block) in [0,1], then weight TOWARD SENSITIVITY
(not a plain mean)". This module implements the harmonization layer in full and, per an explicit,
owner-approved narrowing of CLAUDE.md §4a, ALSO emits a clearly-labeled PROVISIONAL flag so the
endpoint RUNS and yields a usable provisional read.

============================== DEFERRED (CLAUDE.md §4a - do NOT treat as final) ==============================
The CALIBRATED gate is DEFERRED. Everything the real decision needs to be trustworthy is NOT decided here:
  * the weighting function ("weight toward sensitivity" is a philosophy, not numbers),
  * the decision thresholds (what P(block) / spread / vote-confidence separates go from no-go),
  * what counts as a "split" ensemble and how the BayeshERG alea/epis adjudicator resolves it,
  * the pIC50 -> P(block) mapping for CardioGenAI's discriminative head (flag F-1).
Every number that stands in for those decisions is a ``PLACEHOLDER_*`` constant collected in ONE block
below and is an UNCALIBRATED heuristic. The provisional flag is labeled provisional/uncalibrated
everywhere it is produced. When the gate is calibrated, replace the ``PLACEHOLDER_*`` block and the
``_provisional_flag`` logic; the harmonization layer above them should not need to change.
Status for the orchestrator: needs_aaran (the calibration is the genuine residue).
=============================================================================================================

Harmonization contract (IO_SPEC §2 / §3 F-1) - each contributing read mapped onto the common P(block)
shape WITHOUT deciding weights:
  BayeshERG      endpoint_values["P_block"]         identity P(block); carry uncertainty.aleatoric/epistemic
  CardioTox net  endpoint_values["P_block"]         identity P(block) (positional array upstream)
  ADMET-AI       endpoint_values["hERG"]            identity P(block) pre-screen head
  CardioGenAI    endpoint_values["hERG pIC50"]      PLACEHOLDER logistic pIC50 -> P(block), centered on
                 (literal space)                        the pIC50 = 5.0 non-blocker cutoff (F-1 placeholder)

The aggregator also carries generic support for a 0/1 confidence-weighted blocker VOTE read: such a
vote is NEVER averaged into the probability mean (IO_SPEC §2, CLAUDE.md §4), only consulted in the flag
logic. No model currently emits one.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.models import Endpoint, ModelName
from core.schemas import OutputRecord

# ---------------------------------------------------------------------------------------------------
# Exact endpoint_values keys each contributing adapter writes (verified against the model run.py's).
# Kept as named constants so the tests and the harmonizer bind to these, not to raw strings scattered
# around. These are field-name facts, not policy.
# ---------------------------------------------------------------------------------------------------
BAYESHERG_PBLOCK_KEY = "P_block"          # bayesherg: identity P(block)
CARDIOTOX_PBLOCK_KEY = "P_block"          # cardiotox_net: identity P(block)
ADMET_AI_HERG_KEY = "hERG"                # admet_ai: pre-screen P(block) classification head
CARDIOGENAI_PIC50_KEY = "hERG pIC50"      # cardiogenai: literal label WITH a space; raw pIC50 (not P)

# Which models contribute a real P(block) probability (go into the ensemble mean). Read by field
# presence per record, so a future model emitting the same field is picked up too; this list only
# documents the current, settled membership.
PROBABILITY_MODEL_KEYS: dict[ModelName, str] = {
    ModelName.bayesherg: BAYESHERG_PBLOCK_KEY,
    ModelName.cardiotox_net: CARDIOTOX_PBLOCK_KEY,
    ModelName.admet_ai: ADMET_AI_HERG_KEY,
    # cardiogenai contributes a probability too, but only AFTER the placeholder pIC50->P mapping (F-1),
    # so it is harmonized separately below rather than read as a raw identity field.
}

# The dedicated hERG specialists (as opposed to the ADMET-AI generalist pre-screen head). Only a
# specialist read trips the "single specialist alarm" branch of the provisional flag. This split is a
# modeling judgment about which heads are trusted to raise a solo alarm, and stays provisional.
SPECIALIST_MODELS: frozenset[ModelName] = frozenset(
    {ModelName.bayesherg, ModelName.cardiotox_net, ModelName.cardiogenai}
)


# ===================================================================================================
# PLACEHOLDER_* BLOCK - UNCALIBRATED heuristics standing in for the DEFERRED calibrated gate.
# Every constant here is provisional. Do NOT read these as the settled gate. See the DEFERRED banner
# in the module docstring. Replace this whole block when the gate is calibrated.
# ===================================================================================================
PLACEHOLDER_HIGH_MEAN = 0.5          # ensemble-mean P(block) at/above this -> provisional HIGH liability
PLACEHOLDER_MEDIUM_MEAN = 0.3        # ensemble-mean P(block) in [0.3, 0.5) -> provisional MEDIUM
PLACEHOLDER_SPECIALIST_ALARM = 0.7   # any single specialist P(block) at/above this -> provisional HIGH
PLACEHOLDER_VOTE_CONF = 0.5          # a blocker VOTE at confidence at/above this -> provisional HIGH
PLACEHOLDER_SPREAD_CAUTION = 0.4     # ensemble spread (max-min) at/above this biases one level up (caution)

# F-1 placeholder: CardioGenAI pIC50 -> P(block) via a logistic centered on the pIC50 = 5.0 non-blocker
# cutoff. Slope is a placeholder. At pIC50 = 5.0 this returns exactly 0.5; higher pIC50 (stronger block)
# -> higher P(block). The real mapping (threshold vs. calibrated logistic) is DEFERRED (F-1).
PLACEHOLDER_PIC50_CENTER = 5.0       # the VERIFIED non-blocker cutoff (IO_SPEC §2); reused as logistic midpoint
PLACEHOLDER_PIC50_SLOPE = 1.0        # provisional logistic steepness for pIC50 -> P(block)
# ===================================================================================================


def _placeholder_pic50_to_pblock(pic50: float) -> float:
    """PLACEHOLDER F-1 map: CardioGenAI pIC50 -> P(block) logistic, midpoint at the pIC50=5.0 cutoff.

    DEFERRED: this is an uncalibrated stand-in (CLAUDE.md §4a, IO_SPEC F-1). It only guarantees the
    documented anchor (pIC50 = 5.0 -> 0.5) and the correct direction (higher pIC50 -> higher P(block)).
    """
    return 1.0 / (1.0 + math.exp(-PLACEHOLDER_PIC50_SLOPE * (pic50 - PLACEHOLDER_PIC50_CENTER)))


class HergFlag(StrEnum):
    """Provisional, UNCALIBRATED hERG liability level. Not a final go/no-go verdict (see DEFERRED)."""

    HIGH = "HIGH"        # provisional cardiotox liability - lean no-go, but uncalibrated
    MEDIUM = "MEDIUM"    # provisional / ambiguous - "measure it"
    LOW = "LOW"          # provisional low liability - lean go, but uncalibrated
    UNKNOWN = "UNKNOWN"  # no contributing read at all -> cannot even provisionally call


class ReadKind(StrEnum):
    """Whether a harmonized read is a P(block) probability or a 0/1 blocker vote."""

    probability = "probability"
    vote = "vote"


class HergModelRead(BaseModel):
    """One model's contribution harmonized onto the common shape. A probability read OR a vote read.

    ``kind == probability``: ``p_block`` is set (identity, or the F-1 placeholder map for CardioGenAI),
    and the read joins the ensemble mean. ``kind == vote``: ``vote`` (0/1) + ``confidence`` are set and
    the read is a 0/1 blocker VOTE that NEVER enters the probability pool. ``aleatoric`` /
    ``epistemic`` carry BayeshERG's native split for the (deferred) adjudicator.
    """

    model_config = ConfigDict(extra="forbid")

    model: ModelName
    kind: ReadKind
    source_field: str
    is_specialist: bool = False
    p_block: float | None = Field(default=None, ge=0.0, le=1.0)
    vote: int | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    aleatoric: float | None = None
    epistemic: float | None = None
    notes: list[str] = Field(default_factory=list)


class MoleculeHerg(BaseModel):
    """One molecule's harmonized hERG reads + the PROVISIONAL (uncalibrated) flag.

    ``ensemble_mean`` / ``ensemble_spread`` are over the PROBABILITY reads only (a vote read is
    excluded by contract). ``provisional_flag`` is a placeholder, sensitivity-leaning read; ``calibrated``
    is always False and ``is_gate`` always True: hERG IS the gate, but this specific call is not yet the
    calibrated one.
    """

    model_config = ConfigDict(extra="forbid")

    mol_id: str
    reads: list[HergModelRead]
    n_probability_reads: int
    ensemble_mean: float | None = None
    ensemble_spread: float | None = None
    provisional_flag: HergFlag
    flag_reasons: list[str] = Field(default_factory=list)
    is_gate: bool = True
    calibrated: bool = False


class EndpointResult(BaseModel):
    """The hERG endpoint result: per-molecule harmonized reads + spread + a PROVISIONAL flag.

    The endpoint RUNS (the owner wants a running deliverable), but ``deferred`` is True and every flag
    is labeled provisional/uncalibrated: the CALIBRATED weighting/thresholds and the F-1 pIC50->P(block)
    mapping are DEFERRED (CLAUDE.md §4a). The aggregator owns its own result shape (it may not touch core).
    """

    model_config = ConfigDict(extra="forbid")

    endpoint: Endpoint = Endpoint.herg
    quantity: str = (
        "P(hERG block) in [0,1], harmonized across contributing models, plus a PROVISIONAL sensitivity-"
        "leaning liability flag (HIGH/MEDIUM/LOW). PRIMARY go/no-go gate, but the calibrated "
        "weighting/thresholds and the F-1 pIC50->P(block) mapping are DEFERRED - this flag is a labeled "
        "uncalibrated placeholder."
    )
    deferred: bool = True
    molecules: list[MoleculeHerg]
    n_molecules: int
    notes: list[str] = Field(default_factory=list)


def _as_output_record(rec: Any) -> OutputRecord:
    """Coerce a dict (or an already-built ``OutputRecord``) into an ``OutputRecord`` for uniform access."""
    if isinstance(rec, OutputRecord):
        return rec
    return OutputRecord.model_validate(rec)


def _harmonize(records: Sequence[OutputRecord]) -> list[HergModelRead]:
    """Map each contributing record onto the common hERG read shape. NO weighting decided here.

    Probability models (BayeshERG, CardioTox net, ADMET-AI) map by identity from their P(block) field;
    CardioGenAI maps through the PLACEHOLDER F-1 pIC50->P(block) logistic. Missing/None fields are
    skipped (a model that did not run simply does not contribute a read).
    """
    reads: list[HergModelRead] = []

    for rec in records:
        ev = rec.endpoint_values or {}
        unc = rec.uncertainty
        model = rec.model

        # Identity P(block) probability reads.
        if model in PROBABILITY_MODEL_KEYS:
            key = PROBABILITY_MODEL_KEYS[model]
            val = ev.get(key)
            if val is not None:
                reads.append(
                    HergModelRead(
                        model=model,
                        kind=ReadKind.probability,
                        source_field=key,
                        is_specialist=model in SPECIALIST_MODELS,
                        p_block=float(val),
                        aleatoric=(unc.aleatoric if unc else None),
                        epistemic=(unc.epistemic if unc else None),
                        notes=["identity P(block) (IO_SPEC §2)"],
                    )
                )
            continue

        # CardioGenAI: raw pIC50 -> P(block) via the PLACEHOLDER F-1 logistic (DEFERRED mapping).
        if model == ModelName.cardiogenai:
            pic50 = ev.get(CARDIOGENAI_PIC50_KEY)
            if pic50 is not None:
                reads.append(
                    HergModelRead(
                        model=model,
                        kind=ReadKind.probability,
                        source_field=CARDIOGENAI_PIC50_KEY,
                        is_specialist=model in SPECIALIST_MODELS,
                        p_block=_placeholder_pic50_to_pblock(float(pic50)),
                        notes=[
                            "PLACEHOLDER F-1 pIC50->P(block) logistic (midpoint pIC50=5.0); "
                            "the real mapping is DEFERRED (CLAUDE.md §4a)."
                        ],
                    )
                )
            continue

        # Any other model carrying a plain hERG P(block) field is picked up by presence, not folder.
        for key in (ADMET_AI_HERG_KEY,):
            if key in ev and ev.get(key) is not None:
                reads.append(
                    HergModelRead(
                        model=model,
                        kind=ReadKind.probability,
                        source_field=key,
                        is_specialist=model in SPECIALIST_MODELS,
                        p_block=float(ev[key]),  # type: ignore[arg-type]
                        notes=["identity P(block) by field presence (IO_SPEC §2)"],
                    )
                )
                break

    return reads


def _provisional_flag(reads: Sequence[HergModelRead]) -> tuple[HergFlag, float | None, float | None, list[str]]:
    """Compute the PROVISIONAL, UNCALIBRATED, sensitivity-leaning hERG flag from the harmonized reads.

    DEFERRED (CLAUDE.md §4a): every threshold used here is a ``PLACEHOLDER_*`` constant, not the
    calibrated gate. Rules (sensitivity-leaning, so HIGH is checked first):
      HIGH   if ensemble-mean P(block) >= PLACEHOLDER_HIGH_MEAN, OR any single SPECIALIST P(block) >=
             PLACEHOLDER_SPECIALIST_ALARM, OR a blocker VOTE lands at confidence >= PLACEHOLDER_VOTE_CONF.
      MEDIUM if ensemble-mean in [PLACEHOLDER_MEDIUM_MEAN, PLACEHOLDER_HIGH_MEAN).
      LOW    if ensemble-mean < PLACEHOLDER_MEDIUM_MEAN with no specialist alarm and no block vote.
    Ensemble disagreement (spread) is the INDIRECT uncertainty: a wide spread (>= PLACEHOLDER_SPREAD_CAUTION)
    biases one level UP (toward caution), never down.
    Returns (flag, ensemble_mean, ensemble_spread, reasons).
    """
    probs = [r.p_block for r in reads if r.kind is ReadKind.probability and r.p_block is not None]
    votes = [r for r in reads if r.kind is ReadKind.vote]

    reasons: list[str] = ["PROVISIONAL / UNCALIBRATED (CLAUDE.md §4a) - not the final go/no-go verdict."]

    if not probs and not votes:
        reasons.append("no contributing hERG read present in the bundle -> UNKNOWN.")
        return HergFlag.UNKNOWN, None, None, reasons

    mean = sum(probs) / len(probs) if probs else None
    spread = (max(probs) - min(probs)) if len(probs) >= 2 else (0.0 if probs else None)

    # Sensitivity-leaning alarms (any one trips HIGH).
    specialist_alarm = any(
        r.is_specialist and r.p_block is not None and r.p_block >= PLACEHOLDER_SPECIALIST_ALARM
        for r in reads
        if r.kind is ReadKind.probability
    )
    block_vote_alarm = any(
        v.vote == 1 and v.confidence is not None and v.confidence >= PLACEHOLDER_VOTE_CONF for v in votes
    )
    mean_high = mean is not None and mean >= PLACEHOLDER_HIGH_MEAN

    if mean_high or specialist_alarm or block_vote_alarm:
        if mean_high:
            reasons.append(f"ensemble-mean P(block) {mean:.3f} >= {PLACEHOLDER_HIGH_MEAN} (placeholder).")
        if specialist_alarm:
            reasons.append(f"a specialist P(block) >= {PLACEHOLDER_SPECIALIST_ALARM} (placeholder).")
        if block_vote_alarm:
            reasons.append(
                f"a blocker VOTE lands at confidence >= {PLACEHOLDER_VOTE_CONF} (placeholder vote, not a prob)."
            )
        return HergFlag.HIGH, mean, spread, reasons

    # No HIGH alarm: level off the mean, then apply the spread caution bias.
    if mean is not None and mean >= PLACEHOLDER_MEDIUM_MEAN:
        flag = HergFlag.MEDIUM
        reasons.append(
            f"ensemble-mean P(block) {mean:.3f} in [{PLACEHOLDER_MEDIUM_MEAN}, {PLACEHOLDER_HIGH_MEAN}) (placeholder)."
        )
    elif mean is not None:
        flag = HergFlag.LOW
        reasons.append(f"ensemble-mean P(block) {mean:.3f} < {PLACEHOLDER_MEDIUM_MEAN} (placeholder).")
    else:
        # Only vote(s) present, none tripping the block alarm -> provisional LOW with a caveat.
        flag = HergFlag.LOW
        reasons.append("only a non-blocking VOTE present (no probability reads); provisional LOW.")

    if spread is not None and spread >= PLACEHOLDER_SPREAD_CAUTION and flag is HergFlag.LOW:
        flag = HergFlag.MEDIUM
        reasons.append(
            f"ensemble spread {spread:.3f} >= {PLACEHOLDER_SPREAD_CAUTION} (placeholder) biases one level up "
            "toward caution."
        )

    return flag, mean, spread, reasons


def _herg_for(mol_id: str, records: Sequence[OutputRecord]) -> MoleculeHerg:
    """Harmonize one molecule's records and attach the PROVISIONAL flag."""
    reads = _harmonize(records)
    flag, mean, spread, reasons = _provisional_flag(reads)
    n_prob = sum(1 for r in reads if r.kind is ReadKind.probability)
    return MoleculeHerg(
        mol_id=mol_id,
        reads=reads,
        n_probability_reads=n_prob,
        ensemble_mean=mean,
        ensemble_spread=spread,
        provisional_flag=flag,
        flag_reasons=reasons,
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
    """Harmonize the hERG reads onto the common P(block) shape and emit a PROVISIONAL (uncalibrated) flag.

    The endpoint RUNS and returns a full ``EndpointResult`` (per-model harmonized reads + ensemble
    spread + the provisional flag). This is the PRIMARY go/no-go gate, but per CLAUDE.md §4a the
    CALIBRATED weighting/thresholds and the F-1 pIC50->P(block) mapping are DEFERRED: the flag is a
    labeled, uncalibrated placeholder built from the ``PLACEHOLDER_*`` block, to be replaced when the
    gate is calibrated. Do not read the flag as the final verdict.
    """
    norm = _normalize_molecules(molecules)
    mols = [_herg_for(mid, [_as_output_record(r) for r in raw_recs]) for mid, raw_recs in norm]

    return EndpointResult(
        molecules=mols,
        n_molecules=len(mols),
        notes=[
            "hERG is the PRIMARY go/no-go gate; this aggregator harmonizes every contributing read onto a "
            "common P(block) in [0,1] (IO_SPEC §2).",
            "A 0/1 blocker VOTE (if any model emits one) is confidence-weighted and NEVER averaged into "
            "the probability pool (CLAUDE.md §4 landmine, IO_SPEC §2).",
            "DEFERRED (CLAUDE.md §4a): the flag is PROVISIONAL and UNCALIBRATED - the calibrated weighting/"
            "thresholds and the F-1 pIC50->P(block) mapping are placeholders (PLACEHOLDER_* block). Replace "
            "them when the gate is calibrated. Status: needs_aaran.",
        ],
    )
