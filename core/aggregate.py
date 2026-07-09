"""The shared aggregator contract: one input normalizer, one output shape, one ensemble reducer.

Aggregators screen a batch of molecules. The canonical INPUT is a mapping ``{mol_id: records}`` (or the
equivalent pair / dict-with-``records`` forms); :func:`normalize_molecules` turns any of those into
``[(mol_id, records), ...]``.

The canonical OUTPUT (the uniform shape every endpoint returns) is:

    EndpointVerdict{ endpoint, molecules: [ MoleculeVerdict{ endpoint, mol_id, features: [
        Feature{ feature, score, uncertainty, unit, sources: [ Source{model, value, raw, raw_unit} ] }
    ] } ] }

An endpoint measures one or more FEATURES. A feature's ``score`` is the (equally-weighted, for now) mean
of its sources' harmonized ``value``s, and its ``uncertainty`` is the weighted std over the same values
(:func:`ensemble`) - so "score + how much the models disagree" is the whole verdict. Sources keep both the
harmonized ``value`` (on the feature's common scale, what feeds the score) and the model's native ``raw``
value + ``raw_unit`` (for transparency). Values that genuinely measure different things stay as SEPARATE
features (never averaged). The per-endpoint SCIENCE (which models feed which feature, and the unit/direction
harmonization that makes a set of values a real same-scale ensemble) lives in each ``aggregate.py`` and is
documented in ``docs/ENDPOINTS.md``; the shape and the mean/std math live here, once.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.models import Endpoint

# The scalar types a harmonized/native value can carry (mirrors core.schemas.OutputRecord.endpoint_values).
Scalar = float | int | str | bool | None


def _is_record(x: Any) -> bool:
    """Heuristic: does ``x`` look like ONE model output record (vs a molecule's list of records)?

    Used only to tell a flat single-molecule ``list[OutputRecord]`` apart from a sequence of record-lists,
    so the former is treated as one molecule rather than one-molecule-per-record.
    """
    from core.schemas import OutputRecord  # local import: keeps this module dependency-light

    if isinstance(x, OutputRecord):
        return True
    return isinstance(x, Mapping) and ("endpoint_values" in x or "model" in x)


def normalize_molecules(
    molecules: Mapping[str, Sequence[Any]] | Sequence[Any],
) -> list[tuple[str, list[Any]]]:
    """Normalize any accepted input shape to ``[(mol_id, records), ...]``.

    Accepts: a mapping ``{mol_id: records}`` (the canonical form); a sequence of ``(mol_id, records)``
    pairs; a sequence of ``{"mol_id"|"id": ..., "records": [...]}`` dicts; a sequence of record-lists (ids
    default to ``mol_<i>``); or a flat ``list[OutputRecord]`` for a single molecule (detected because its
    items are records, so it is never mistaken for a list of record-lists).
    """
    if isinstance(molecules, Mapping):
        return [(str(mid), list(recs)) for mid, recs in molecules.items()]

    seq = list(molecules)
    if not seq:
        return []
    if _is_record(seq[0]):
        return [("mol_0", seq)]  # a bare flat list of records is one molecule

    out: list[tuple[str, list[Any]]] = []
    for i, item in enumerate(seq):
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


# --------------------------------------------------------------------------------------------------
# The uniform output shape + the ensemble reducer (score = mean, uncertainty = std).
# --------------------------------------------------------------------------------------------------
class Source(BaseModel):
    """One model's contribution to a feature.

    ``value`` is the model's read HARMONIZED onto the feature's common scale (this is what feeds the
    score/uncertainty). ``raw`` / ``raw_unit`` are the model's NATIVE value before harmonization, kept for
    transparency (``raw`` stays ``None`` when no transform was applied - ``value`` is already native).
    ``weight`` is for the (future) weighted mean/std; equal (1.0) for now. ``note`` is a short free-text
    marker (e.g. an error string or ``"N/A"`` when the model ran but did not report this feature).
    """

    model_config = ConfigDict(extra="forbid")

    model: str
    value: Scalar
    raw: Scalar = None
    raw_unit: str | None = None
    weight: float = 1.0
    note: str | None = None


class Feature(BaseModel):
    """One thing an endpoint measures: the ensemble score + its disagreement uncertainty + the raw sources.

    ``score`` is the (weighted, equal-for-now) mean of the numeric source ``value``s; ``uncertainty`` is the
    weighted std over the same values (``None`` for a single source - disagreement is undefined for one).
    Both are ``None`` when no source reported a numeric value. ``unit`` names the common scale ``score`` is on.
    """

    model_config = ConfigDict(extra="forbid")

    feature: str
    score: float | None = None
    uncertainty: float | None = None
    unit: str | None = None
    n_sources: int = 0
    sources: list[Source] = Field(default_factory=list)


class MoleculeVerdict(BaseModel):
    """One molecule's endpoint verdict: its feature list. This is what lands in the screening card."""

    model_config = ConfigDict(extra="forbid")

    endpoint: Endpoint
    mol_id: str
    features: list[Feature] = Field(default_factory=list)


class EndpointVerdict(BaseModel):
    """The batch result an ``aggregate(molecules)`` returns: one ``MoleculeVerdict`` per molecule.

    ``core.run.aggregate_records`` reads ``.molecules`` and pulls the per-molecule verdict for the card.
    """

    model_config = ConfigDict(extra="forbid")

    endpoint: Endpoint
    molecules: list[MoleculeVerdict] = Field(default_factory=list)
    n_molecules: int = 0


def ensemble(
    values: Sequence[Any],
    weights: Sequence[float] | None = None,
) -> tuple[float | None, float | None]:
    """Reduce a set of same-scale values to ``(score, uncertainty)`` = (weighted mean, weighted std).

    The one place the score/uncertainty math lives. Non-numeric values (``None``, strings, and bools -
    a flag is not a measurement) are ignored, so a failed/absent source never corrupts the mean. Returns
    ``(None, None)`` if no numeric value is present, and ``(mean, None)`` for a single value (disagreement
    is undefined for one point). The std is the population-style weighted std
    ``sqrt(sum w_i (x_i - mean)^2 / sum w_i)`` - equal weights by default, reducing to the population std;
    the SAME weights drive both the mean and the std (as intended for the later weight-tuning).
    """
    ws = list(weights) if weights is not None else [1.0] * len(values)
    pairs: list[tuple[float, float]] = []
    for v, w in zip(values, ws):
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)) and math.isfinite(v):
            pairs.append((float(v), float(w)))
    if not pairs:
        return None, None
    wsum = sum(w for _, w in pairs)
    if wsum <= 0:
        return None, None
    mean = sum(w * x for x, w in pairs) / wsum
    if len(pairs) < 2:
        return mean, None
    var = sum(w * (x - mean) ** 2 for x, w in pairs) / wsum
    return mean, math.sqrt(var)
