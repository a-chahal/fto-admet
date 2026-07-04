"""Smoke test for the root/core environment (built by t00b-core-env).

Confirms the toolchain resolves before any core module exists. This is the target of t00b's gate;
it is deliberately independent of core/ so it can run first.
"""


def test_core_toolchain_imports():
    import pytest # noqa: F401
    import pydantic
    import pandas # noqa: F401
    import yaml # noqa: F401
    assert int(pydantic.VERSION.split(".")[0]) >= 2, "pydantic v2 required"


def test_rdkit_available():
    from rdkit import Chem
    assert Chem.MolFromSmiles("CCO") is not None
