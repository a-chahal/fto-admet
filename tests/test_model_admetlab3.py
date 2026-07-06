"""Mocked unit tests for the admetlab3 adapter (CODE-API; fast tier, NO network, NO box).

ADMETlab 3.0 is a remote web service, so its adapter is an HTTP client rather than a local model. There is
no `@pytest.mark.model` box smoke here: instead an INJECTED fake transport drives the full async round-trip
(wash -> POST /api/admet -> taskId -> POST /api/admetCSV -> CSV) entirely offline. These tests assert the
transport contract, retry/backoff, the predict fallback path, raw-output caching (CLAUDE.md §4a), positional
row alignment, per-record error isolation, and that the emitted JSON validates against the real
`core.schemas.OutputRecord`.

The literal 119 CSV column names are F-6 (needs a live call) and are NOT asserted here: the adapter parses
the header generically, so the test uses a small synthetic CSV and checks the columns survive round-trip.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from core.schemas import OutputRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_PY = REPO_ROOT / "endpoints" / "triage" / "admetlab3" / "run.py"


def _load_run_module() -> ModuleType:
    """Import the adapter's run.py by path (it is a script, not an installed package)."""
    spec = importlib.util.spec_from_file_location("admetlab3_run", RUN_PY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run = _load_run_module()


# A tiny synthetic CSV standing in for the real (F-6) 119-column response: two arbitrary heads + a row.
FAKE_CSV = "smiles,hERG,logP,note\nCCO,0.12,-0.31,ok\n"


class FakeTransport:
    """A programmable transport: maps a URL path to a queue of (status, body) replies it returns in order.

    Records every call so tests can assert which endpoints were hit (and that the fallback fired). A path
    with an exhausted queue reuses its last reply, so a single "ready" reply keeps answering polls.
    """

    def __init__(self, script: dict[str, list[tuple[int, bytes]]]) -> None:
        self.script = {k: list(v) for k, v in script.items()}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, url: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
        path = "/" + url.split("//", 1)[-1].split("/", 1)[1] if "//" in url else url
        self.calls.append((path, json.loads(body.decode("utf-8"))))
        queue = self.script.get(path)
        if not queue:
            raise AssertionError(f"no scripted reply for {path}")
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def paths(self) -> list[str]:
        return [p for p, _ in self.calls]


def _json(obj: Any) -> bytes:
    return json.dumps(obj).encode("utf-8")


def _client(transport: FakeTransport, tmp_path: Path, **kw: Any) -> Any:
    return run.AdmetLab3Client(
        base_url="https://admetlab3.scbdd.com",
        cache_dir=tmp_path / "cache",
        rps=0,  # no throttle sleep in tests
        backoff=0,  # no backoff sleep in tests
        transport=transport,
        **kw,
    )


# -- helpers ------------------------------------------------------------------------------------------


def test_extract_task_id_handles_nesting_and_variants() -> None:
    assert run._extract_task_id({"taskId": "abc"}) == "abc"
    assert run._extract_task_id({"data": {"task_id": 42}}) == "42"
    assert run._extract_task_id({"result": [{"taskId": "x9"}]}) == "x9"
    assert run._extract_task_id({"nope": 1}) is None


def test_coerce_numbers_strings_and_missing() -> None:
    assert run._coerce("3") == 3
    assert run._coerce("-0.31") == pytest.approx(-0.31)
    assert run._coerce("ok") == "ok"
    assert run._coerce("") is None
    assert run._coerce("NA") is None


def test_parse_csv_maps_header_to_rows() -> None:
    header, rows = run.parse_csv(FAKE_CSV)
    assert header == ["smiles", "hERG", "logP", "note"]
    assert rows[0]["hERG"] == pytest.approx(0.12)
    assert rows[0]["note"] == "ok"


# -- full flow ----------------------------------------------------------------------------------------


def test_full_flow_single_molecule(tmp_path: Path) -> None:
    transport = FakeTransport({
        "/api/admet": [(200, _json({"taskId": "T1"}))],
        "/api/admetCSV": [(200, FAKE_CSV.encode("utf-8"))],
    })
    client = _client(transport, tmp_path)
    outputs = run.run_batch(
        [{"smiles": "CCO", "mol_id": "m1"}], client, feature=False, uncertain=True, wash=False
    )
    assert len(outputs) == 1
    record = OutputRecord.model_validate(outputs[0])
    assert record.model == "admetlab3"
    assert record.endpoint_values["hERG"] == pytest.approx(0.12)
    assert record.raw["header"] == ["smiles", "hERG", "logP", "note"]
    # Uncertainty routed as a flag in the reserved extra envelope, not as a fabricated sigma.
    assert record.uncertainty is not None
    assert record.uncertainty.extra["uncertain_requested"] is True
    assert record.uncertainty.ad_index is None
    # transport hit predict then CSV (no wash, since wash=False)
    assert transport.paths() == ["/api/admet", "/api/admetCSV"]


def test_raw_csv_and_predict_json_are_cached(tmp_path: Path) -> None:
    transport = FakeTransport({
        "/api/admet": [(200, _json({"taskId": "CACHE1"}))],
        "/api/admetCSV": [(200, FAKE_CSV.encode("utf-8"))],
    })
    client = _client(transport, tmp_path)
    run.run_batch([{"smiles": "CCO"}], client, feature=False, uncertain=True, wash=False)
    cache = tmp_path / "cache"
    assert (cache / "CACHE1.result.csv").read_text() == FAKE_CSV
    assert json.loads((cache / "CACHE1.predict.json").read_text())["taskId"] == "CACHE1"


def test_csv_polls_until_ready(tmp_path: Path) -> None:
    # First admetCSV reply is a JSON "not ready" envelope; the retry loop polls until the CSV lands.
    transport = FakeTransport({
        "/api/admet": [(200, _json({"taskId": "T2"}))],
        "/api/admetCSV": [
            (200, _json({"status": "pending"})),
            (200, FAKE_CSV.encode("utf-8")),
        ],
    })
    client = _client(transport, tmp_path, max_retries=3)
    outputs = run.run_batch([{"smiles": "CCO"}], client, feature=False, uncertain=True, wash=False)
    assert outputs[0]["endpoint_values"]["hERG"] == pytest.approx(0.12)
    assert transport.paths().count("/api/admetCSV") == 2


def test_predict_retries_on_server_error(tmp_path: Path) -> None:
    transport = FakeTransport({
        "/api/admet": [
            (503, b"upstream busy"),
            (200, _json({"taskId": "T3"})),
        ],
        "/api/admetCSV": [(200, FAKE_CSV.encode("utf-8"))],
    })
    client = _client(transport, tmp_path, max_retries=3)
    outputs = run.run_batch([{"smiles": "CCO"}], client, feature=False, uncertain=True, wash=False)
    assert outputs[0]["endpoint_values"]["hERG"] == pytest.approx(0.12)
    assert transport.paths().count("/api/admet") == 2


def test_predict_falls_back_to_single_endpoint(tmp_path: Path) -> None:
    # Primary /api/admet returns a hard 4xx (not retried); submit() must fall back to /api/single/admet.
    transport = FakeTransport({
        "/api/admet": [(404, b"not found")],
        "/api/single/admet": [(200, _json({"taskId": "T4"}))],
        "/api/admetCSV": [(200, FAKE_CSV.encode("utf-8"))],
    })
    client = _client(transport, tmp_path)
    outputs = run.run_batch([{"smiles": "CCO"}], client, feature=False, uncertain=True, wash=False)
    assert outputs[0]["endpoint_values"]["hERG"] == pytest.approx(0.12)
    assert "/api/single/admet" in transport.paths()


def test_transport_failure_raises_after_budget(tmp_path: Path) -> None:
    # Both the primary and the fallback predict endpoints stay down: submit() exhausts its budget on each
    # and re-raises rather than fabricating a taskId.
    transport = FakeTransport({
        "/api/admet": [(500, b"boom")],
        "/api/single/admet": [(500, b"boom")],
    })
    client = _client(transport, tmp_path, max_retries=2)
    with pytest.raises(run.AdmetLab3Error):
        run.run_batch([{"smiles": "CCO"}], client, feature=False, uncertain=True, wash=False)


def test_batch_positional_alignment_with_empty_smiles(tmp_path: Path) -> None:
    # Two real molecules with a blank in the middle: the blank gets a null record, reals align to CSV rows.
    two_row_csv = "smiles,hERG\nCCO,0.1\nCCC,0.2\n"
    transport = FakeTransport({
        "/api/admet": [(200, _json({"taskId": "T5"}))],
        "/api/admetCSV": [(200, two_row_csv.encode("utf-8"))],
    })
    client = _client(transport, tmp_path)
    records = [{"smiles": "CCO", "mol_id": "a"}, {"smiles": "  ", "mol_id": "b"}, {"smiles": "CCC", "mol_id": "c"}]
    outputs = run.run_batch(records, client, feature=False, uncertain=True, wash=False)
    assert len(outputs) == 3
    assert outputs[0]["endpoint_values"]["hERG"] == pytest.approx(0.1)
    assert outputs[1]["endpoint_values"] == {} and "error" in outputs[1]["raw"]
    assert outputs[2]["endpoint_values"]["hERG"] == pytest.approx(0.2)
    # Only the two non-empty SMILES were submitted, in order.
    submit_call = next(body for path, body in transport.calls if path == "/api/admet")
    assert submit_call["SMILES"] == ["CCO", "CCC"]
    assert submit_call["uncertain"] is True


def test_wash_is_used_when_enabled(tmp_path: Path) -> None:
    transport = FakeTransport({
        "/api/washmol": [(200, _json({"smiles": ["OCC"]}))],
        "/api/admet": [(200, _json({"taskId": "T6"}))],
        "/api/admetCSV": [(200, FAKE_CSV.encode("utf-8"))],
    })
    client = _client(transport, tmp_path)
    run.run_batch([{"smiles": "CCO"}], client, feature=False, uncertain=True, wash=True)
    assert transport.paths()[0] == "/api/washmol"
    # The washed SMILES is what gets submitted.
    submit_call = next(body for path, body in transport.calls if path == "/api/admet")
    assert submit_call["SMILES"] == ["OCC"]


def test_all_empty_smiles_returns_null_records_without_network(tmp_path: Path) -> None:
    transport = FakeTransport({})  # nothing should be called
    client = _client(transport, tmp_path)
    outputs = run.run_batch([{"smiles": ""}, {"smiles": "   "}], client, feature=False, uncertain=True, wash=False)
    assert len(outputs) == 2
    assert all(o["endpoint_values"] == {} for o in outputs)
    assert transport.calls == []


def test_parse_inputs_forms(tmp_path: Path) -> None:
    recs, single = run.parse_inputs('{"smiles": "CCO", "mol_id": "m"}')
    assert single and recs == [{"smiles": "CCO", "mol_id": "m"}]
    recs, single = run.parse_inputs('[{"smiles": "CCO"}, {"smiles": "CCC"}]')
    assert not single and len(recs) == 2
    recs, single = run.parse_inputs("CCO ethanol\n# comment\nCCC propane\n")
    assert not single and recs[0] == {"smiles": "CCO", "mol_id": "ethanol"}


def test_main_end_to_end_writes_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Drive main() with the env-built client swapped for a fake-transport client (no network).
    transport = FakeTransport({
        "/api/admet": [(200, _json({"taskId": "MAIN1"}))],
        "/api/admetCSV": [(200, FAKE_CSV.encode("utf-8"))],
    })
    monkeypatch.setattr(run, "build_client", lambda: _client(transport, tmp_path))
    in_path = tmp_path / "in.json"
    out_path = tmp_path / "out.json"
    in_path.write_text(json.dumps({"smiles": "CCO", "mol_id": "m1"}))
    rc = run.main(["--input", str(in_path), "--output", str(out_path)])
    assert rc == 0
    payload = json.loads(out_path.read_text())
    record = OutputRecord.model_validate(payload)  # single input -> single object
    assert record.model == "admetlab3"
    assert record.endpoint_values["hERG"] == pytest.approx(0.12)
