"""The one input contract every endpoint aggregator shares.

Aggregators screen a batch of molecules. The canonical input is a mapping ``{mol_id: records}`` (or the
equivalent pair / dict-with-``records`` forms). :func:`normalize_molecules` turns any of those - and, for
ergonomics, a bare flat ``list[OutputRecord]`` for a single molecule - into ``[(mol_id, records), ...]``.
One normalizer means callers never have to guess an aggregator's shape (no per-caller shim), and the
contract can evolve in exactly one place instead of drifting across the thirteen aggregators.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


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
