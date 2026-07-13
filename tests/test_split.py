"""Unit tests for the scaffold split used by the fusion trainer (training/split.py)."""

from __future__ import annotations

import numpy as np

from training.split import murcko_scaffold, scaffold_split

# Eight distinct ring systems, four terminal-chain analogs each (Murcko strips the chain -> shared core).
_CORES = ("c1ccccc1", "c1ccccn1", "c1cccc2ccccc12", "c1cccc2ccccc2n1",
          "c1ccc2[nH]ccc2c1", "c1ccco1", "c1cccs1", "c1ccncn1")
_MULTI_SCAFFOLD = [f"{'C' * k}{core}" for core in _CORES for k in (1, 2, 3, 4)]


def _all_indices_partitioned(splits, n):
    joined = np.concatenate(splits)
    assert sorted(joined.tolist()) == list(range(n))  # exact partition: no dupes, no gaps


def test_scaffolds_never_span_splits():
    tr, cal, te = scaffold_split(_MULTI_SCAFFOLD, seed=0)
    _all_indices_partitioned((tr, cal, te), len(_MULTI_SCAFFOLD))
    assert len(tr) > 0 and len(cal) > 0 and len(te) > 0
    scaf = [murcko_scaffold(s) for s in _MULTI_SCAFFOLD]
    for a, b in ((tr, cal), (tr, te), (cal, te)):
        assert not ({scaf[i] for i in a} & {scaf[i] for i in b})  # no scaffold shared across two splits


def test_deterministic():
    a = scaffold_split(_MULTI_SCAFFOLD, seed=0)
    b = scaffold_split(_MULTI_SCAFFOLD, seed=0)
    for x, y in zip(a, b):
        assert x.tolist() == y.tolist()


def test_random_fallback_when_too_few_scaffolds():
    # A single shared scaffold -> fewer than 3 groups -> random split, still a clean 3-way partition.
    smiles = [f"{'C' * k}c1ccccc1" for k in range(1, 11)]
    tr, cal, te = scaffold_split(smiles, seed=0)
    _all_indices_partitioned((tr, cal, te), len(smiles))
    assert len(tr) > 0 and len(cal) > 0 and len(te) > 0


def test_empty():
    tr, cal, te = scaffold_split([], seed=0)
    assert len(tr) == len(cal) == len(te) == 0
