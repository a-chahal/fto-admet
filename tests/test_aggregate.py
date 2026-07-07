"""The one shared aggregator input contract: normalize_molecules turns every accepted shape into
``[(mol_id, records), ...]`` so callers never guess an aggregator's shape (no per-caller shim)."""

from __future__ import annotations

from core.aggregate import normalize_molecules
from core.schemas import OutputRecord


def _rec() -> OutputRecord:
    return OutputRecord(model="rdkit_crippen", endpoint_values={}, provenance={"m": "x"})


def test_mapping_is_the_canonical_shape():
    r = _rec()
    assert normalize_molecules({"a": [r], "b": [r, r]}) == [("a", [r]), ("b", [r, r])]


def test_flat_record_list_is_one_molecule():
    # A bare list of records is a single molecule, not one-molecule-per-record.
    r1, r2 = _rec(), _rec()
    assert normalize_molecules([r1, r2]) == [("mol_0", [r1, r2])]


def test_dict_records_are_detected_as_records():
    d1 = {"model": "rdkit_crippen", "endpoint_values": {}, "provenance": {}}
    assert normalize_molecules([d1, d1]) == [("mol_0", [d1, d1])]


def test_pairs_dicts_and_record_lists():
    r = _rec()
    assert normalize_molecules([("x", [r])]) == [("x", [r])]
    assert normalize_molecules([{"mol_id": "y", "records": [r]}]) == [("y", [r])]
    assert normalize_molecules([[r], [r, r]]) == [("mol_0", [r]), ("mol_1", [r, r])]


def test_empty_inputs():
    assert normalize_molecules([]) == []
    assert normalize_molecules({}) == []
