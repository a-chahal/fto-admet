"""The batch screen entry point: each model is dispatched ONCE over the whole set of molecules, and every
molecule still gets a full card assembled by reusing those records. A failing model is isolated."""

from __future__ import annotations

from core import screen as screenmod
from core.dispatch import DispatchError
from core.models import Endpoint, ModelName
from core.schemas import OutputRecord


def _rec(model: str) -> OutputRecord:
    return OutputRecord(model=model, endpoint_values={}, provenance={"model": model})


def test_screen_batch_dispatches_each_model_exactly_once(monkeypatch, tmp_path):
    calls: dict = {}

    def fake_batch(name, inputs, out_dir, *, config=None):
        calls[name] = calls.get(name, 0) + 1
        return [_rec(name.value) for _ in inputs]  # one record per input, in order

    monkeypatch.setattr(screenmod.dispatch, "run_model_batch", fake_batch)
    mols = [{"smiles": "CCO", "mol_id": "a"}, {"smiles": "CCC", "mol_id": "b"}, {"smiles": "CCN", "mol_id": "c"}]

    cards = screenmod.screen_batch(mols, config=object(), out_dir=tmp_path)

    assert len(cards) == 3
    # THE speed guarantee: every model dispatched once for the whole batch, not per endpoint per molecule.
    assert calls and max(calls.values()) == 1
    # admet_ai feeds many endpoints yet was dispatched exactly once.
    assert calls[ModelName.admet_ai] == 1
    for card, mol in zip(cards, mols):
        assert card["mol_id"] == mol["mol_id"]
        assert set(card["endpoints"]) == {ep.value for ep in Endpoint}


def test_screen_batch_isolates_a_failing_model(monkeypatch, tmp_path):
    def fake_batch(name, inputs, out_dir, *, config=None):
        if name == ModelName.admet_ai:
            raise DispatchError("boom")
        return [_rec(name.value) for _ in inputs]

    monkeypatch.setattr(screenmod.dispatch, "run_model_batch", fake_batch)

    cards = screenmod.screen_batch([{"smiles": "CCO", "mol_id": "a"}], config=object(), out_dir=tmp_path)

    assert len(cards) == 1
    # admet_ai is recorded as a failure on an endpoint it feeds, but the card still assembles.
    fails = cards[0]["endpoints"]["triage"]["failures"]
    assert any(f["model"] == "admet_ai" for f in fails)


def test_screen_single_delegates_to_batch(monkeypatch, tmp_path):
    seen: dict = {}

    def fake_batch(name, inputs, out_dir, *, config=None):
        seen[name] = len(inputs)
        return [_rec(name.value) for _ in inputs]

    monkeypatch.setattr(screenmod.dispatch, "run_model_batch", fake_batch)

    card = screenmod.screen("CCO", "ethanol", config=object(), out_dir=tmp_path)

    assert card["mol_id"] == "ethanol"
    # single-molecule screen still dispatches each model once (batch of 1), not once per endpoint.
    assert all(n == 1 for n in seen.values())
