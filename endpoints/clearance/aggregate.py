#!/usr/bin/env python
"""clearance aggregator - DECOMPOSED renal / hepatic / aggregate reads that are NEVER merged.

Contract (CLAUDE.md §2, IO_SPEC §2 "clearance"): the aggregator runs in the core env (no box, no GPU);
it consumes already collected ``OutputRecord``s. Clearance is the pipeline's weakest endpoint and the
one place where a naive "combine the numbers" is actively wrong. The four clearance predictions live in
FOUR different units and matrices, so the honest shared read is NOT one number - it is three separately
labeled decomposed reads, each carrying its own unit string, kept apart on purpose.

    read        model -> field                              unit                     role
    ----        --------------                              ----                     ----
    renal       watanabe_renal -> fe / CLr (+ fu_p)         CLr: mL/min/kg           web/manual triage read
    hepatic     admet_ai -> Clearance_Hepatocyte_AZ         uL/min/10^6 cells        CLint candidate (low-weight, F-17)
                admet_ai -> Clearance_Microsome_AZ          uL/min/mg                CLint candidate (low-weight, F-17)
                opera    -> Clint                           uL/min/10^6 cells        CLint candidate
                (+ metabolism SoM from smartcyp / fame3r    per-atom table           qualitative hepatic-lability input)
    aggregate   pksmart -> CL_mL_min_kg (+ fold-error)      mL/min/kg                ranking-only (R^2=0.31); FTO liability

LANDMINE (the entire point of this file - F-3, CLAUDE.md §4): **NEVER combine the four clearance
numbers numerically.** No mean, no sum, no ratio across them. They are different units AND different
matrices (renal plasma clearance vs hepatocyte CLint vs microsomal CLint vs whole-body i.v. CL), so any
arithmetic across them is meaningless. Even the two hepatic candidates that happen to share the string
"uL/min/10^6 cells" (ADMET-AI hepatocyte and OPERA Clint) are different assays and are kept as separate
labeled candidates, never averaged. The renal-vs-hepatic fork is resolved by EXPERIMENT, not by the
models. This module therefore has no code path that averages or sums across the reads; it only routes
each source into its own labeled slot with its own unit string.

PKSmart CL is **ranking-only** (R^2=0.31, GMFE ~2.43): we surface it with its native fold-error and a
relative within-series rank, and we NEVER present the bare CL number without that fold-error attached
(anchor ~89.6 mL/min/kg, the FTO liability). ADMET-AI's two clearance heads are weak (R^2 ~0.26/0.28,
F-17) so each hepatic CLint candidate carries a ``low_weight`` flag: qualitative, not a calibrated CLint.

DEFERRED boundaries honored here (CLAUDE.md §4a; never invented):
- The operational AD rule / conformal calibration that would turn the fold-error and low-weight flags
  into a calibrated confidence is DEFERRED: we surface the native signals, we do not decide the policy.
- Watanabe's ``CLr`` unit ("mL/min/kg") is confirmed only against the SOP template; the live-page unit
  confirmation (F-14) lives in the watanabe_renal README, not here. We record whatever unit the ledger
  transcription carried; we do not convert.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.models import Endpoint, ModelName
from core.schemas import OutputRecord

# --------------------------------------------------------------------------------------------------
# Source field names (units baked into the labels; see each adapter). These are the ONLY keys this
# aggregator reads; every value is routed into its own labeled slot and never combined with another.
# --------------------------------------------------------------------------------------------------
WATANABE_FE = "fe"
WATANABE_CLR = "CLr"
WATANABE_FUP = "fu_p"
WATANABE_CLR_UNIT = "mL/min/kg"  # per the watanabe_renal SOP; live-page confirmation is F-14, not here

ADMET_AI_HEPATOCYTE = "Clearance_Hepatocyte_AZ"
ADMET_AI_MICROSOME = "Clearance_Microsome_AZ"
ADMET_AI_HEPATOCYTE_UNIT = "uL/min/10^6 cells"
ADMET_AI_MICROSOME_UNIT = "uL/min/mg"

OPERA_CLINT = "Clint"
OPERA_CLINT_UNIT = "uL/min/10^6 cells"

PKSMART_CL = "CL_mL_min_kg"
PKSMART_CL_UNIT = "mL/min/kg"
PKSMART_FOLD_ERROR_KEY = "cl_fold_error"  # in pksmart uncertainty.extra (the CL fold factor)

# The FTO liability anchor: PKSmart human total body clearance ~89.6 mL/min/kg (IO_SPEC §1 #11, task t43).
ANCHOR_CL_ML_MIN_KG = 89.6

# Site-of-metabolism providers whose presence marks a qualitative hepatic-lability input (t42). Their
# output is a per-atom ordinal SoM table, NOT a clearance scalar, so it is noted, never numerically merged.
SOM_MODELS = (ModelName.smartcyp, ModelName.fame3r)


def _as_output_record(rec: Any) -> OutputRecord:
    """Coerce a dict (or an already-built ``OutputRecord``) into an ``OutputRecord`` for uniform access."""
    if isinstance(rec, OutputRecord):
        return rec
    return OutputRecord.model_validate(rec)


class ClintCandidate(BaseModel):
    """One hepatic intrinsic-clearance candidate, kept as its OWN labeled read (never averaged).

    Each candidate carries its own ``unit`` and ``matrix`` precisely so the landmine cannot be tripped:
    the three hepatic candidates are different assays and are surfaced side by side, not combined into a
    single CLint. ``low_weight`` marks the ADMET-AI heads (F-17: R^2 ~0.26/0.28) as qualitative only.
    """

    model_config = ConfigDict(extra="forbid")

    model: ModelName
    field: str
    value: float | None
    unit: str
    matrix: str          # "hepatocyte" / "microsome" / "intrinsic"
    low_weight: bool      # F-17: qualitative only (weak ADMET-AI clearance heads)


class RenalRead(BaseModel):
    """The renal decomposed read (Watanabe via DruMAP): fe / CLr / fu_p. Triage only, never combined."""

    model_config = ConfigDict(extra="forbid")

    source: ModelName = ModelName.watanabe_renal
    present: bool
    fe: float | str | None                     # fraction excreted unchanged (binary classifier: class or prob)
    clr: float | None                           # renal clearance
    clr_unit: str = WATANABE_CLR_UNIT
    fu_p: float | None                          # fraction unbound in plasma (0-1)
    notes: list[str] = Field(default_factory=list)


class HepaticRead(BaseModel):
    """The hepatic decomposed read: the CLint candidates, kept separate + a qualitative SoM presence flag.

    ``clint_candidates`` holds each hepatic-clearance candidate as its own labeled ``ClintCandidate``
    (own unit, own matrix). They are NEVER averaged - the two that share "uL/min/10^6 cells" are still
    different assays. ``som_available`` records that a per-atom SoM table (SMARTCyp / FAME3R, t42) exists
    for this molecule as a qualitative hepatic-lability signal; it is not turned into a number here.
    """

    model_config = ConfigDict(extra="forbid")

    present: bool
    clint_candidates: list[ClintCandidate] = Field(default_factory=list)
    som_available: bool = False
    som_models: list[ModelName] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class AggregateRead(BaseModel):
    """The aggregate/total read (PKSmart whole-body i.v. CL): RANKING-ONLY, always with its fold-error.

    PKSmart CL is weak (R^2=0.31), so it is used for relative within-series ranking, never as a calibrated
    number. The fold-error travels WITH the CL value at all times (surface the fold-error, never the bare
    CL); ``fold_error_available`` is False only when the upstream record carried no fold-error, in which
    case a note flags that CL must not be surfaced on its own. ``cl_rank`` is the molecule's relative rank
    across the set (1 = fastest clearance = highest CL = worst liability); ``None`` if it has no CL.
    """

    model_config = ConfigDict(extra="forbid")

    source: ModelName = ModelName.pksmart
    present: bool
    cl: float | None                            # total body clearance (ranking-only; never present bare)
    cl_unit: str = PKSMART_CL_UNIT
    ranking_only: bool = True
    fold_error: float | None                    # the CL fold factor (native DIRECT uncertainty)
    fold_error_low: float | None                # CL lower prediction bound
    fold_error_high: float | None               # CL upper prediction bound
    fold_error_available: bool = False
    anchor_cl: float = ANCHOR_CL_ML_MIN_KG      # FTO liability anchor (mL/min/kg)
    cl_rank: int | None = None                  # relative rank across the set (1 = fastest clearance)
    notes: list[str] = Field(default_factory=list)


class MoleculeClearance(BaseModel):
    """One molecule's DECOMPOSED clearance: renal / hepatic / aggregate as three separate labeled reads."""

    model_config = ConfigDict(extra="forbid")

    mol_id: str
    renal: RenalRead
    hepatic: HepaticRead
    aggregate: AggregateRead
    notes: list[str] = Field(default_factory=list)


class EndpointResult(BaseModel):
    """The harmonized clearance result: per-molecule decomposed reads that stay renal / hepatic / aggregate.

    There is deliberately NO single combined clearance scalar anywhere in this result (F-3): the reads are
    kept apart, each with its own unit, and the renal-vs-hepatic fork is left for experiment. The
    aggregator owns its own result shape (an aggregator task may not touch ``core``).
    """

    model_config = ConfigDict(extra="forbid")

    endpoint: Endpoint = Endpoint.clearance
    quantity: str = (
        "DECOMPOSED clearance: renal / hepatic / aggregate kept as separate labeled reads, "
        "each with its own unit; never merged across units (F-3)"
    )
    molecules: list[MoleculeClearance]
    n_molecules: int
    n_cl_ranked: int                            # molecules with a PKSmart CL used in the relative ranking
    notes: list[str] = Field(default_factory=list)
    deferred: list[str] = Field(default_factory=list)


def _normalize_molecules(
    molecules: Mapping[str, Sequence[Any]] | Sequence[Any],
) -> list[tuple[str, list[Any]]]:
    """Normalize the accepted input shapes to ``[(mol_id, records), ...]`` (same contract as solubility).

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


def _renal_read(records: Sequence[OutputRecord]) -> RenalRead:
    """Route the Watanabe renal record into the renal slot (fe / CLr / fu_p). Triage read only."""
    for rec in records:
        if rec.model != ModelName.watanabe_renal:
            continue
        ev = rec.endpoint_values or {}
        fe = ev.get(WATANABE_FE)
        clr = ev.get(WATANABE_CLR)
        fu_p = ev.get(WATANABE_FUP)
        notes = [
            "renal read is triage only; the renal-vs-hepatic fork is resolved by experiment, not the models.",
        ]
        if clr is None:
            notes.append("no CLr value transcribed (manual DruMAP SOP); fe/fu_p only.")
        return RenalRead(
            present=True,
            fe=None if fe is None else (fe if isinstance(fe, str) else float(fe)),
            clr=None if clr is None else float(clr),
            fu_p=None if fu_p is None else float(fu_p),
            notes=notes,
        )
    return RenalRead(
        present=False,
        fe=None,
        clr=None,
        fu_p=None,
        notes=["no watanabe_renal (DruMAP) transcription present for this molecule."],
    )


def _hepatic_read(records: Sequence[OutputRecord]) -> HepaticRead:
    """Route the hepatic CLint candidates into separate labeled slots; flag SoM presence (never combine)."""
    candidates: list[ClintCandidate] = []
    som_models: list[ModelName] = []

    for rec in records:
        ev = rec.endpoint_values or {}
        if rec.model == ModelName.admet_ai:
            if ADMET_AI_HEPATOCYTE in ev and ev[ADMET_AI_HEPATOCYTE] is not None:
                candidates.append(
                    ClintCandidate(
                        model=ModelName.admet_ai,
                        field=ADMET_AI_HEPATOCYTE,
                        value=float(ev[ADMET_AI_HEPATOCYTE]),  # type: ignore[arg-type]
                        unit=ADMET_AI_HEPATOCYTE_UNIT,
                        matrix="hepatocyte",
                        low_weight=True,  # F-17: weak head, qualitative only
                    )
                )
            if ADMET_AI_MICROSOME in ev and ev[ADMET_AI_MICROSOME] is not None:
                candidates.append(
                    ClintCandidate(
                        model=ModelName.admet_ai,
                        field=ADMET_AI_MICROSOME,
                        value=float(ev[ADMET_AI_MICROSOME]),  # type: ignore[arg-type]
                        unit=ADMET_AI_MICROSOME_UNIT,
                        matrix="microsome",
                        low_weight=True,  # F-17
                    )
                )
        elif rec.model == ModelName.opera and OPERA_CLINT in ev and ev[OPERA_CLINT] is not None:
            candidates.append(
                ClintCandidate(
                    model=ModelName.opera,
                    field=OPERA_CLINT,
                    value=float(ev[OPERA_CLINT]),  # type: ignore[arg-type]
                    unit=OPERA_CLINT_UNIT,
                    matrix="intrinsic",
                    low_weight=False,
                )
            )
        elif rec.model in SOM_MODELS and rec.model not in som_models:
            som_models.append(rec.model)

    notes: list[str] = []
    if candidates:
        notes.append(
            "hepatic CLint candidates are kept as separate labeled reads (different assays/units); "
            "they are NEVER averaged, even the two sharing 'uL/min/10^6 cells' (F-3)."
        )
    else:
        notes.append("no hepatic CLint candidate (admet_ai / opera) present for this molecule.")
    if som_models:
        notes.append(
            "metabolism SoM table present (qualitative hepatic-lability input, t42); "
            "it is a per-atom ranking, not merged into a clearance number."
        )

    return HepaticRead(
        present=bool(candidates),
        clint_candidates=candidates,
        som_available=bool(som_models),
        som_models=som_models,
        notes=notes,
    )


def _aggregate_read(records: Sequence[OutputRecord]) -> AggregateRead:
    """Route the PKSmart whole-body CL into the aggregate slot, always paired with its fold-error."""
    for rec in records:
        if rec.model != ModelName.pksmart:
            continue
        ev = rec.endpoint_values or {}
        cl = ev.get(PKSMART_CL)
        unc = rec.uncertainty
        fold_error = None
        fold_low = None
        fold_high = None
        if unc is not None:
            fold_low = unc.fold_error_low
            fold_high = unc.fold_error_high
            fold_error = (unc.extra or {}).get(PKSMART_FOLD_ERROR_KEY)
            if fold_error is not None:
                fold_error = float(fold_error)
        fold_available = fold_error is not None or fold_low is not None or fold_high is not None

        notes = [
            "PKSmart CL is RANKING-ONLY (R^2=0.31); the fold-error is surfaced with it and the bare CL "
            f"is never presented alone. FTO liability anchor ~{ANCHOR_CL_ML_MIN_KG} mL/min/kg.",
        ]
        if not fold_available:
            notes.append(
                "no PKSmart fold-error on this record: CL must NOT be surfaced on its own without it."
            )
        return AggregateRead(
            present=True,
            cl=None if cl is None else float(cl),
            fold_error=fold_error,
            fold_error_low=None if fold_low is None else float(fold_low),
            fold_error_high=None if fold_high is None else float(fold_high),
            fold_error_available=fold_available,
            notes=notes,
        )
    return AggregateRead(
        present=False,
        cl=None,
        fold_error=None,
        fold_error_low=None,
        fold_error_high=None,
        fold_error_available=False,
        notes=["no pksmart CL transcription present for this molecule."],
    )


def aggregate(
    molecules: Mapping[str, Sequence[Any]] | Sequence[Any],
) -> EndpointResult:
    """Decompose a compound set's clearance into renal / hepatic / aggregate reads that are never merged.

    ``molecules`` is the set (see ``_normalize_molecules`` for the accepted shapes); each molecule's bundle
    is a list of its model ``OutputRecord``s. For each molecule the four sources are routed into three
    separate labeled reads, each carrying its own unit string; nothing is averaged or summed across them
    (F-3). PKSmart CL, being ranking-only, is additionally given a relative rank across the set (1 =
    fastest clearance = worst FTO liability), always alongside its fold-error.
    """
    norm = _normalize_molecules(molecules)

    mols: list[MoleculeClearance] = []
    for mid, raw_recs in norm:
        recs = [_as_output_record(r) for r in raw_recs]
        renal = _renal_read(recs)
        hepatic = _hepatic_read(recs)
        agg = _aggregate_read(recs)
        mols.append(
            MoleculeClearance(
                mol_id=mid,
                renal=renal,
                hepatic=hepatic,
                aggregate=agg,
                notes=[
                    "renal / hepatic / aggregate are kept as SEPARATE labeled reads with distinct units; "
                    "they are never combined into one clearance number (F-3).",
                ],
            )
        )

    # Relative within-series ranking on the PKSmart CL ONLY (ranking-only quantity; no cross-unit math).
    # 1 = highest CL = fastest clearance = worst liability. Molecules with no CL get no rank.
    cl_keyed = [(m.mol_id, m.aggregate.cl) for m in mols if m.aggregate.cl is not None]
    cl_ordered = sorted(cl_keyed, key=lambda kv: kv[1], reverse=True)
    rank_by_id = {mid: i + 1 for i, (mid, _cl) in enumerate(cl_ordered)}
    for m in mols:
        m.aggregate.cl_rank = rank_by_id.get(m.mol_id)

    notes: list[str] = [
        "clearance is DECOMPOSED: three labeled reads per molecule, never a single combined number (F-3).",
    ]
    if not cl_keyed:
        notes.append("no PKSmart CL in the set: no relative clearance ranking could be computed.")

    return EndpointResult(
        molecules=mols,
        n_molecules=len(mols),
        n_cl_ranked=len(cl_keyed),
        notes=notes,
        deferred=[
            "the operational AD rule / conformal calibration that would turn the PKSmart fold-error and "
            "the F-17 low-weight flags into a calibrated confidence is DEFERRED (CLAUDE.md §4a).",
            "Watanabe CLr live-page unit confirmation is F-14 (watanabe_renal SOP), not decided here; "
            "the transcribed unit is recorded as-is and never converted.",
        ],
    )
