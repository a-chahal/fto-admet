"""Mocked unit test for the ochem_ppb api-model adapter (fast tier, NO network, NO box).

This is an **api-model** (CLAUDE.md §5): the done-criteria is an async client + poll loop + retry/backoff
+ response cache + placeholder modelId + a *mocked* unit test - NOT an on-box smoke (there is no isolated
env and OCHEM is a remote service). So this test runs in the core env and drives the whole submit -> poll
-> parse -> transform -> cache path with the network primitive (``run._transport``) monkeypatched: no
socket is ever opened. It is deliberately unmarked (fast tier), unlike the ``@pytest.mark.model`` smokes.

What it pins:
  - the LogIt -> % -> fraction transform math (the project-owner directive that must not be mis-implemented),
  - the poll loop actually iterates over "pending" responses before returning the ready one,
  - retry/backoff recovers from a transient transport error,
  - ``$$$$`` batching aligns predictions positionally,
  - the raw-response cache is written and a second call is served from it (no network),
  - the emitted record validates against the real ``core.schemas.OutputRecord`` with the native
    DM/accuracy routed into ``uncertainty``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from core.schemas import OutputRecord

import importlib.util

# Load the adapter module directly (it lives outside any importable package).
_RUN_PY = Path(__file__).resolve().parent.parent / "endpoints" / "ppb" / "ochem_ppb" / "run.py"
_spec = importlib.util.spec_from_file_location("ochem_ppb_run", _RUN_PY)
assert _spec and _spec.loader
run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run)


# --------------------------------------------------------------------------------------------------
# The transform math (the directive: prediction is in LogIt units, not a percent).
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "logit, expected_pct",
    [
        (0.0, 50.0),                 # logit 0 -> 50% bound
        (math.log(9.0), 90.0),       # ln(9) -> 90% bound
        (-math.log(9.0), 10.0),      # -ln(9) -> 10% bound
        (math.log(19.0), 95.0),      # ln(19) -> 95% bound
    ],
)
def test_logit_transform(logit: float, expected_pct: float) -> None:
    assert run.logit_to_percent(logit) == pytest.approx(expected_pct, abs=1e-6)
    assert run.logit_to_fraction(logit) == pytest.approx(expected_pct / 100.0, abs=1e-8)


def test_logit_transform_is_stable_at_extremes() -> None:
    # No overflow either side (underflow to 0.0 is fine, the point is it does not raise).
    assert 0.0 <= run.logit_to_fraction(-800.0) < 1e-100
    assert run.logit_to_fraction(800.0) == pytest.approx(1.0, abs=1e-12)


# --------------------------------------------------------------------------------------------------
# A fake OCHEM service: submit returns a task id, the first poll is "pending", the second is ready.
# --------------------------------------------------------------------------------------------------
def _ready_body(logits: list[float]) -> str:
    return json.dumps({
        "status": "success",
        "predictions": [
            {"value": v, "accuracy": 0.25, "dm": 0.4} for v in logits
        ],
    })


class _FakeService:
    """Sequences submit -> pending -> ready and records the URLs it was called with."""

    def __init__(self, logits: list[float], *, pending_polls: int = 2) -> None:
        self.logits = logits
        self.pending_polls = pending_polls
        self.calls: list[str] = []
        self._polls_seen = 0

    def __call__(self, url: str, *, timeout: float = 0.0) -> str:
        self.calls.append(url)
        if "taskId" not in url:
            # submit: hand back a task id, no predictions yet (async)
            return json.dumps({"status": "queued", "taskId": "abc-123"})
        self._polls_seen += 1
        if self._polls_seen <= self.pending_polls:
            return json.dumps({"status": "running", "taskId": "abc-123"})
        return _ready_body(self.logits)


def test_poll_loop_and_transform_end_to_end(tmp_path: Path) -> None:
    service = _FakeService([math.log(9.0)], pending_polls=2)  # -> 90% bound
    sleeps: list[float] = []

    records = [{"smiles": "CCO", "mol_id": "ethanol"}]
    out = run.predict_records(
        records,
        cache_dir=tmp_path / "cache",
        transport=service,
        sleep=lambda s: sleeps.append(s),
    )

    # The poll loop iterated: one submit + (2 pending + 1 ready) polls, and it slept between polls.
    poll_calls = [c for c in service.calls if "taskId" in c]
    assert len(poll_calls) == 3, f"expected submit + 3 polls, got calls={service.calls}"
    assert len(sleeps) == 2, "should sleep once per pending poll"

    rec = OutputRecord.model_validate(out[0])
    assert rec.model == "ochem_ppb"
    assert rec.endpoint_values["ppb_percent_bound"] == pytest.approx(90.0, abs=1e-6)
    assert rec.endpoint_values["fraction_bound"] == pytest.approx(0.9, abs=1e-8)
    # Native ASNN DM + accuracy routed into the reserved uncertainty envelope's extra (AD rule DEFERRED).
    assert rec.uncertainty is not None
    assert rec.uncertainty.extra["distance_to_model"] == pytest.approx(0.4)
    assert rec.uncertainty.extra["accuracy_error_logit"] == pytest.approx(0.25)
    # AD threshold policy is DEFERRED -> ad_index / ad_in_domain are NOT fabricated.
    assert rec.uncertainty.ad_index is None
    assert rec.uncertainty.ad_in_domain is None
    # Raw carries the verbatim logit + the documented transform.
    assert rec.raw["logit"] == pytest.approx(math.log(9.0))


def test_cache_hit_skips_network(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    first = _FakeService([0.0], pending_polls=0)  # -> 50%
    run.predict_records([{"smiles": "CCO"}], cache_dir=cache, transport=first,
                        sleep=lambda s: None)
    assert first.calls, "first call should hit the (fake) network"

    # Second call: a transport that explodes if touched proves the cache served it.
    def _boom(url: str, *, timeout: float = 0.0) -> str:  # pragma: no cover - must not run
        raise AssertionError("network called on a cache hit")

    out = run.predict_records([{"smiles": "CCO"}], cache_dir=cache, transport=_boom,
                              sleep=lambda s: None)
    rec = OutputRecord.model_validate(out[0])
    assert rec.endpoint_values["ppb_percent_bound"] == pytest.approx(50.0, abs=1e-6)


def test_retry_backoff_recovers_from_transient_error(tmp_path: Path) -> None:
    import urllib.error

    state = {"n": 0}

    def _flaky(url: str, *, timeout: float = 0.0) -> str:
        state["n"] += 1
        if state["n"] == 1:
            raise urllib.error.URLError("transient")
        return _ready_body([0.0])  # ready on the retry

    out = run.predict_records([{"smiles": "CCO"}], cache_dir=tmp_path / "c",
                              transport=_flaky, sleep=lambda s: None)
    rec = OutputRecord.model_validate(out[0])
    assert rec.endpoint_values["fraction_bound"] == pytest.approx(0.5, abs=1e-8)
    assert state["n"] == 2, "should have retried exactly once after the transient error"


def test_batch_positional_alignment(tmp_path: Path) -> None:
    # Two molecules, two logits -> aligned positionally to input order.
    service = _FakeService([0.0, math.log(9.0)], pending_polls=0)
    out = run.predict_records(
        [{"smiles": "CCO", "mol_id": "a"}, {"smiles": "CCC", "mol_id": "b"}],
        cache_dir=tmp_path / "cache", transport=service, sleep=lambda s: None,
    )
    a = OutputRecord.model_validate(out[0])
    b = OutputRecord.model_validate(out[1])
    assert a.endpoint_values["ppb_percent_bound"] == pytest.approx(50.0, abs=1e-6)
    assert b.endpoint_values["ppb_percent_bound"] == pytest.approx(90.0, abs=1e-6)

    # The two molecules were batched into one submit with the $$$$ SDF separator (URL-encoded as %24).
    submit_call = next(c for c in service.calls if "taskId" not in c)
    assert "%24%24%24%24" in submit_call, f"expected a $$$$-batched submit, got {submit_call}"


def test_missing_prediction_yields_null_record_not_crash(tmp_path: Path) -> None:
    # Service returns fewer predictions than molecules -> the unmatched one is a null record.
    service = _FakeService([0.0], pending_polls=0)
    out = run.predict_records(
        [{"smiles": "CCO"}, {"smiles": "CCC"}],
        cache_dir=tmp_path / "cache", transport=service, sleep=lambda s: None,
    )
    ok = OutputRecord.model_validate(out[0])
    missing = OutputRecord.model_validate(out[1])
    assert ok.endpoint_values["fraction_bound"] == pytest.approx(0.5, abs=1e-8)
    assert missing.endpoint_values["fraction_bound"] is None
    assert missing.uncertainty is None
    assert "no prediction" in missing.raw["error"]


def test_empty_smiles_is_null_record(tmp_path: Path) -> None:
    out = run.predict_records([{"smiles": "  "}], cache_dir=tmp_path / "cache",
                              use_network=False, sleep=lambda s: None)
    rec = OutputRecord.model_validate(out[0])
    assert rec.endpoint_values["fraction_bound"] is None


def test_poll_timeout_raises(tmp_path: Path) -> None:
    # A task that never becomes ready should raise TimeoutError (never a fabricated value).
    clock = {"t": 0.0}

    def _always_pending(url: str, *, timeout: float = 0.0) -> str:
        if "taskId" not in url:
            return json.dumps({"status": "queued", "taskId": "x"})
        return json.dumps({"status": "running", "taskId": "x"})

    def _tick() -> float:
        clock["t"] += 5.0
        return clock["t"]

    with pytest.raises(TimeoutError):
        run.fetch_predictions(
            ["CCO"], transport=_always_pending, sleep=lambda s: None,
            clock=_tick, max_wait=20.0, poll_interval=7.0,
        )
