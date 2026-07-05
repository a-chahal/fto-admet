"""Shared pytest fixtures and the two-tier test marker (CLAUDE.md §5; SETTLED §8 testing).

Two things live here so the whole suite can rely on them:

1. The **canonical FTO-43 fixture** (``fto43`` / ``fto43_input``): the single lead-compound input
   reused by every test and, later, by each model's opt-in smoke test. It is loaded from
   ``tests/fixtures/fto43.smi`` so there is one source of truth for the molecule.

   NEEDS_AARAN: the SMILES in that ``.smi`` is a documented PLACEHOLDER (the real canonical structure
   for PubChem CID 164886650 is a live lookup that could not run in this headless session). The
   ``smiles_is_placeholder`` flag surfaces that so no downstream test silently trusts a stand-in as the
   real FTO-43; the fast (non-model) suite does not depend on the chemical identity of the value.

2. The **two test tiers** (SETTLED §8): fast unit tests run by default; ``@pytest.mark.model`` tests
   shell into a model's isolated env on the box and are opt-in. The marker is registered here (and in
   ``pyproject.toml``) so ``-m "not model"`` selects the fast tier everywhere.

tmp-dir fixtures (``tmp_config``, ``tmp_ledger``, ``tmp_outputs``) hand a test a hermetic ``Config``
whose ledger / locks / outputs land under ``tmp_path`` (standing in for ``/zfs``), never the
developer's real ``.env`` environment.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from core.config import Config, load_config

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FTO43_SMI = FIXTURES_DIR / "fto43.smi"

# The lead compound's stable identity (docs Skeleton lines 25-26). The SMILES is *not* hardcoded here:
# it is read from the .smi so there is a single, swappable source of truth (see NEEDS_AARAN above).
FTO43_CID = 164886650


def pytest_configure(config: pytest.Config) -> None:
    """Register the opt-in ``model`` marker so ``-m "not model"`` works and ``--strict-markers`` passes.

    Also declared in ``pyproject.toml``; registering here as well keeps the marker defined even if the
    suite is run against a bare pytest config, and documents the two-tier split at the fixture layer.
    """
    config.addinivalue_line(
        "markers",
        "model: test shells into a model's isolated env on the box (opt-in; excluded from the fast "
        "tier via -m 'not model').",
    )


@dataclass(frozen=True)
class Molecule:
    """A canonical fixture molecule: the fields every adapter's ``--input`` needs, plus provenance.

    ``smiles_is_placeholder`` is ``True`` while ``smiles`` is the documented stand-in (the real FTO-43
    structure is a pending live lookup); it flips to ``False`` automatically once the ``.smi`` title is
    changed from ``FTO-43-PLACEHOLDER`` to ``FTO-43``.
    """

    smiles: str
    mol_id: str
    cid: int
    smiles_is_placeholder: bool

    def as_input(self) -> dict[str, str]:
        """The dict form fed to ``dispatch.run_model`` / ``run.run_endpoint`` (a valid ``InputRecord``)."""
        return {"smiles": self.smiles, "mol_id": self.mol_id}


def _read_smi(path: Path) -> tuple[str, str]:
    """Parse the one data line of a ``.smi`` file: ``<SMILES><whitespace><title>``; skip ``#`` comments."""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            raise ValueError(f"{path}: data line must be '<SMILES><whitespace><title>', got {line!r}")
        return parts[0], parts[1]
    raise ValueError(f"{path}: no data line found (only comments/blank lines)")


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Path to ``tests/fixtures/`` (the committed fixture inputs)."""
    return FIXTURES_DIR


@pytest.fixture(scope="session")
def fto43() -> Molecule:
    """The canonical FTO-43 lead-compound fixture, loaded from ``tests/fixtures/fto43.smi``.

    Reused across the suite and (later) by every model's ``@pytest.mark.model`` smoke test. See the
    module docstring / the ``.smi`` header for the placeholder caveat.
    """
    smiles, title = _read_smi(FTO43_SMI)
    is_placeholder = "PLACEHOLDER" in title.upper()
    mol_id = title.replace("-PLACEHOLDER", "") if is_placeholder else title
    return Molecule(smiles=smiles, mol_id=mol_id, cid=FTO43_CID, smiles_is_placeholder=is_placeholder)


@pytest.fixture
def fto43_input(fto43: Molecule) -> dict[str, str]:
    """The FTO-43 fixture as the ``--input`` payload dict (a valid ``InputRecord``)."""
    return fto43.as_input()


@pytest.fixture
def tmp_config(tmp_path: Path) -> Config:
    """A hermetic :class:`Config` with ledger / locks / outputs under ``tmp_path`` (stands in for /zfs).

    Reads no real ``.env``: paths are injected explicitly and ``dotenv_path`` points at a nonexistent
    file, so a test never depends on (or writes to) the developer's real environment.
    """
    return load_config(
        env={
            "FTO_ADMET_ROOT": str(tmp_path / "fto-admet"),
            "FTO_ADMET_ENV_CACHE": str(tmp_path / "fto-admet-envs"),
        },
        dotenv_path=tmp_path / "absent.env",
        create_dirs=True,
    )


@pytest.fixture
def tmp_ledger(tmp_config: Config) -> Path:
    """The ledger path inside the hermetic :func:`tmp_config` (its parent dir is created)."""
    return tmp_config.ledger


@pytest.fixture
def tmp_outputs(tmp_config: Config) -> Path:
    """The outputs dir inside the hermetic :func:`tmp_config` (created)."""
    return tmp_config.outputs
