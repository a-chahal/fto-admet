"""The FusionSpec schema - the committed, human-readable trained-weights artifact for one feature.

A fusion spec is the ~KB output of the offline trainer (``training/``) for a single endpoint feature.
It lives at ``core/fusion/specs/<endpoint>__<feature>.json`` and is applied at inference by
``core.fusion.fuse`` with pure arithmetic (no sklearn). It is deliberately a small, diffable config:
per-source calibration ``gᵢ``, the fusion weights ``wᵢ`` + intercept, the conformal uncertainty recipe,
and full provenance so every trained score is auditable.

No-fabricate (CLAUDE.md §5) extends here: a spec is only ever written by ``training/train_endpoint.py``,
never hand-edited. The schema lives in ``core`` (pydantic only) so both the trainer (which produces
specs) and the aggregators (which consume them) share one contract without pulling training deps into core.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Target(BaseModel):
    """The experimental quantity the feature is trained to predict (defines its meaning + units)."""

    model_config = ConfigDict(extra="forbid")

    name: str                                             # e.g. "logD7.4", "Kp_uu_brain"
    units: str                                            # e.g. "log", "unitless"
    transform: Literal["identity", "log", "logit"] = "identity"  # space the fit was done in


class SourceCalibration(BaseModel):
    """Per-source map ``gᵢ`` from the model's harmonized value onto the target scale.

    ``identity`` passes the value through; ``linear`` applies ``a*x + b`` (``params=[a, b]``);
    ``logistic`` applies ``sigmoid(a*x + b)`` (``params=[a, b]``). ``impute_value`` is the calibrated
    value substituted when this source is absent for a molecule (the training-set mean), so a missing
    source does not silently bias the linear sum.
    """

    model_config = ConfigDict(extra="forbid")

    model: str
    kind: Literal["identity", "linear", "logistic"] = "identity"
    params: list[float] = Field(default_factory=list)
    impute_value: float | None = None


class Fusion(BaseModel):
    """The trained combination: ``score = Σ wᵢ·gᵢ(valueᵢ) + intercept`` over the calibrated sources."""

    model_config = ConfigDict(extra="forbid")

    weights: dict[str, float]                             # model -> wᵢ
    intercept: float = 0.0
    method: Literal["nnls", "ridge", "linear", "logistic", "equal"] = "equal"
    regularization: float | None = None                  # ridge/elastic-net lambda, if used
    link: Literal["identity", "logistic"] = "identity"   # "logistic": score = sigmoid(Σwᵢ·gᵢ + intercept) -> a probability


class UncertaintySpec(BaseModel):
    """The normalized-conformal recipe: the interval half-width is ``quantile * scale(x)``.

    ``scale = "disagreement_std"`` makes the width ride on the (calibrated) source spread - wide where
    the models disagree, narrow where they converge - which is the input-dependent trust signal. For a
    single-source feature (no disagreement) use ``"native_sigma"`` (a per-source σ) or ``"constant"``.
    ``quantile`` (Q) is fit on a held-out calibration split so the interval has real coverage at ``1-alpha``.
    """

    model_config = ConfigDict(extra="forbid")

    method: Literal["normalized_conformal", "none"] = "none"
    alpha: float = 0.1
    quantile: float | None = None                        # Q (the calibrated multiplier)
    scale: Literal["disagreement_std", "native_sigma", "constant"] = "disagreement_std"
    scale_floor: float = 0.0
    constant_width: float | None = None                  # base width when scale = "constant"


class Provenance(BaseModel):
    """Exactly what produced this spec, so a trained score is reconstructible and auditable (no-fabricate)."""

    model_config = ConfigDict(extra="forbid")

    dataset: str                                         # clean training set, e.g. "biogen_adme_2023"
    dataset_hash: str | None = None
    exclusion_index_hash: str | None = None
    n_train: int | None = None
    n_calib: int | None = None
    metrics: dict[str, float] = Field(default_factory=dict)   # mae / r2 / conformal_coverage / ...
    trained_at: str | None = None                        # stamped by the trainer (never a live clock in core)
    git_sha: str | None = None
    notes: str | None = None


class FusionSpec(BaseModel):
    """One feature's trained fusion: target, per-source calibration, weights, uncertainty, provenance."""

    model_config = ConfigDict(extra="forbid")

    feature: str
    endpoint: str
    target: Target
    sources: list[SourceCalibration]
    fusion: Fusion
    uncertainty: UncertaintySpec = Field(default_factory=UncertaintySpec)
    provenance: Provenance
