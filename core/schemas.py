"""Shared pydantic I/O contracts the dispatcher validates before and after every model run.

The point of this module is the *shared envelope* (CLAUDE.md §2/§3), not per-model exhaustiveness:
each model adapter adds its own ``OutputRecord`` subclass (typed payload fields) as it lands. What is
fixed here is the input record every adapter is fed, and the output record every adapter returns, plus
the reusable ``Uncertainty`` envelope.

Schema rule (CLAUDE.md §3): the uncertainty / applicability-domain (AD) fields are *reserved from day
one* so no adapter has to be re-touched when the AD policy is eventually written. Many upstreams emit a
native signal - OPERA ``AD`` / ``AD_index`` / ``Conf_index``, BayeshERG aleatoric/epistemic, PKSmart
fold-error, FAME3R ``FAME3RScore``, OCHEM's distance-to-model. ``Uncertainty`` has a home for each. The *policy* that consumes them
(the operational AD rule, conformal calibration) is DEFERRED (CLAUDE.md §4a): we reserve the fields,
we do not decide the rule.

Deferred boundaries honored here:
- F-16 (input standardization for the FTO di-cation) is DEFERRED. ``InputRecord`` only *carries* which
  canonical form was fed (``standardized`` / ``standardizer``); it does not implement a standardizer.
- The AD rule / calibration is DEFERRED: fields only, no policy.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.models import ModelName


class InputRecord(BaseModel):
    """The single canonical input handed to every model adapter (uniform CLI ``--input``).

    ``smiles`` is the canonical form the pipeline chose to feed. F-16 (the FTO di-cation
    protonation/tautomer/desalting decision) is DEFERRED: this record does not standardize anything, it
    only records *which* form was fed so a divergence (e.g. OCHEM wanting a desalted neutral parent) can
    be flagged downstream. ``standardized`` stays ``False`` until a real standardizer is wired.
    """

    model_config = ConfigDict(extra="forbid")

    smiles: str
    mol_id: str | None = None
    standardized: bool = False
    standardizer: str | None = None

    @field_validator("smiles")
    @classmethod
    def _reject_empty_smiles(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("smiles must be a non-empty, non-whitespace string")
        return stripped


class Uncertainty(BaseModel):
    """Reusable, all-optional envelope for every native uncertainty / AD signal in the model set.

    Nothing here is required: a model that emits no signal leaves it empty, a model that emits several
    fills the matching fields, and anything without a named home goes in ``extra``. This is deliberately
    a superset so no adapter needs retrofitting when the AD policy lands (CLAUDE.md §3).

    Field map to the native signals:
    - ``aleatoric`` / ``epistemic`` - BayeshERG MC-dropout decomposition.
    - ``fold_error_low`` / ``fold_error_high`` - PKSmart-style fold-error interval.
    - ``confidence`` (0-1) - a generic scalar confidence (e.g. a percent-string confidence once parsed).
    - ``ad_in_domain`` / ``ad_index`` / ``conf_index`` - OPERA's ``AD`` (bool) / ``AD_index`` /
      ``Conf_index``. ADStatus is *folded in here* rather than kept separate: OPERA emits all three per
      endpoint alongside the prediction, so one envelope keeps them together with the other signals.
    - ``extra`` - anything model-specific with no first-class field (e.g. FAME3R ``FAME3RScore``,
      OCHEM's distance-to-model).
    """

    model_config = ConfigDict(extra="forbid")

    aleatoric: float | None = None
    epistemic: float | None = None
    fold_error_low: float | None = None
    fold_error_high: float | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    ad_in_domain: bool | None = None
    ad_index: float | None = Field(default=None, ge=0.0, le=1.0)
    conf_index: float | None = Field(default=None, ge=0.0, le=1.0)
    extra: dict[str, Any] = Field(default_factory=dict)


class OutputRecord(BaseModel):
    """The base record every adapter returns; per-model subclasses add a typed payload as they land.

    ``endpoint_values`` is the generic scalar payload (one entry per emitted quantity). Direction and
    units live in the per-model schema notes / registry, not here (CLAUDE.md §4, F-3/F-12): this base
    only reserves the shape. Non-scalar outputs (per-atom site-of-metabolism tables from SMARTCyp /
    FAME3R) are NOT forced into ``endpoint_values`` - they live in ``raw`` as a list, which is the
    verbatim upstream payload kept for the raw-output cache / audit trail.
    """

    model_config = ConfigDict(extra="forbid")

    model: ModelName
    endpoint_values: dict[str, float | int | str | bool | None] = Field(default_factory=dict)
    uncertainty: Uncertainty | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any]


def validate_input(data: Any) -> InputRecord:
    """Validate an input payload (dict or record) into an ``InputRecord``. Called before subprocess launch."""
    return InputRecord.model_validate(data)


def validate_output(data: Any) -> OutputRecord:
    """Validate a model's collected output (dict or record) into an ``OutputRecord``. Called after collect."""
    return OutputRecord.model_validate(data)
