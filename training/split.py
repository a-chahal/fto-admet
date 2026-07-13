"""Deterministic scaffold split for the fusion trainer.

Whole Bemis-Murcko scaffolds are kept together, so ``train`` / ``calibration`` / ``test`` never share a
scaffold. This is the honest split for CONTAMINATED public data (ChEMBL is dense with congeneric series):
a random split scatters near-neighbours of a training molecule across the train/test boundary and inflates
every metric. Scaffold-holdout forces the model to generalize to unseen chemotypes, which is closer to the
real ask (rank the OOD oxetane series). Small or single-scaffold sets auto-fall-back to a random split,
since there are then too few groups to fill three buckets.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

import numpy as np
from rdkit import Chem
from rdkit.Chem.Scaffolds import MurckoScaffold


def murcko_scaffold(smiles: str) -> str:
    """The Bemis-Murcko scaffold SMILES (atomic, chirality-stripped); ``""`` for an unparseable input."""
    mol = Chem.MolFromSmiles(smiles or "")
    if mol is None:
        return ""
    try:
        return MurckoScaffold.MurckoScaffoldSmiles(mol=mol, includeChirality=False)
    except Exception:
        return ""


def _random_split(n: int, fracs: tuple[float, float, float], seed: int):
    rng = np.random.default_rng(seed)
    perm = rng.permutation(n)
    n_tr, n_cal = int(fracs[0] * n), int(fracs[1] * n)
    return perm[:n_tr], perm[n_tr:n_tr + n_cal], perm[n_tr + n_cal:]


def scaffold_split(
    smiles: Sequence[str],
    fracs: tuple[float, float, float] = (0.6, 0.2, 0.2),
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return ``(train_idx, cal_idx, test_idx)`` positional arrays; whole scaffolds never span splits.

    Groups rows by generic Murcko scaffold, then assigns groups largest-first to whichever split is
    furthest below its target count (deterministic; ``seed`` only affects the random fallback). Falls back
    to a random split when there are fewer than three scaffolds, or when the greedy assignment leaves any
    split empty (one giant scaffold can starve a bucket) - both cases would break the 3-way conformal split.
    """
    n = len(smiles)
    if n == 0:
        empty = np.array([], dtype=int)
        return empty, empty, empty

    groups: dict[str, list[int]] = defaultdict(list)
    for i, s in enumerate(smiles):
        groups[murcko_scaffold(str(s))].append(i)

    if len(groups) < 3:
        return _random_split(n, fracs, seed)

    # Largest groups first; ties broken by scaffold string for determinism.
    ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    targets = [fracs[0] * n, fracs[1] * n, fracs[2] * n]
    buckets: list[list[int]] = [[], [], []]
    counts = [0.0, 0.0, 0.0]
    for _, idx in ordered:
        j = max(range(3), key=lambda k: targets[k] - counts[k])
        buckets[j].extend(idx)
        counts[j] += len(idx)

    if min(len(b) for b in buckets) == 0:  # a dominant scaffold starved a bucket: fall back
        return _random_split(n, fracs, seed)

    return (
        np.array(sorted(buckets[0]), dtype=int),
        np.array(sorted(buckets[1]), dtype=int),
        np.array(sorted(buckets[2]), dtype=int),
    )
