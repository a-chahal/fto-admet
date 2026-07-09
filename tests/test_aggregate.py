"""The shared aggregator contract: normalize_molecules (input shape) + ensemble (score/uncertainty math).

normalize_molecules turns every accepted shape into ``[(mol_id, records), ...]``; ensemble reduces a set
of same-scale values to (weighted mean, weighted std) so every endpoint scores/uncertainty the same way.
"""

from __future__ import annotations

import math

from core.aggregate import ensemble, normalize_molecules
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


# --------------------------------------------------------------------------- ensemble (score/uncertainty)
def test_ensemble_equal_weights_is_mean_and_population_std():
    mean, std = ensemble([0.6694, 0.66, 0.71])
    xs = [0.6694, 0.66, 0.71]
    m = sum(xs) / 3
    assert abs(mean - m) < 1e-12
    assert abs(std - math.sqrt(sum((x - m) ** 2 for x in xs) / 3)) < 1e-12   # population std


def test_ensemble_single_value_has_no_uncertainty():
    assert ensemble([0.5]) == (0.5, None)


def test_ensemble_empty_or_all_nonnumeric_is_none_none():
    assert ensemble([]) == (None, None)
    assert ensemble([None, "x"]) == (None, None)


def test_ensemble_ignores_nonnumeric_bool_and_nonfinite_but_keeps_the_rest():
    # None / strings / bools / inf-nan are dropped so a bad source never corrupts the mean
    mean, std = ensemble([0.4, None, "x", True, float("nan"), 0.6])
    assert mean == 0.5 and abs(std - 0.1) < 1e-12   # only 0.4 and 0.6 counted


def test_ensemble_weighted_mean_and_std_use_the_same_weights():
    # weight the 1.0 twice as hard as the 0.0 -> mean pulled toward 1.0
    mean, std = ensemble([0.0, 1.0], weights=[1.0, 2.0])
    assert abs(mean - (2.0 / 3.0)) < 1e-12
    var = (1 * (0.0 - mean) ** 2 + 2 * (1.0 - mean) ** 2) / 3
    assert abs(std - math.sqrt(var)) < 1e-12
