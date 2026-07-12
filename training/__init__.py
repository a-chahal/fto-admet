"""Offline fusion trainer: clean experimental data -> committed core/fusion/specs/*.json.

Runs in the ``training`` pixi env (sklearn/pandas/rdkit), never inside ``core``. Imports ``core.fusion.spec``
to write the shared FusionSpec contract. See README.md for the flow.
"""
