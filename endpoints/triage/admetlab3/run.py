#!/usr/bin/env python
"""admetlab3 adapter - ADMETlab 3.0 web API (CODE-API cross-cutting generalist).

Uniform model CLI (CLAUDE.md §2, SETTLED §6):

    python run.py --input <path> --output <path> [--gpu N]

Unlike the CODE-PKG adapters, ADMETlab 3.0 is a *remote service*: there is no local model to load, so
this adapter is an HTTP client. It runs in a tiny isolated env (stdlib ``urllib`` only, no ``requests``)
and shells out over the network to ``https://admetlab3.scbdd.com``. It emits plain JSON matching
``core.schemas.OutputRecord``; the dispatcher validates that JSON against the real schema on collection.

TRANSPORT (VERIFIED 2 Jul 2026 from ToxMCP/admetlab-mcp client/admet_client.py; IO_SPEC §1 #2, F-6):

  1. (optional) wash:    POST /api/washmol  body {"SMILES": [...]}            -> standardized SMILES
  2. predict (async):    POST /api/admet    body {"SMILES": [...],            -> JSON containing a taskId
                              "feature": <bool>, "uncertain": <bool>}
                         (fallback: POST /api/single/admet, same body)
  3. fetch results:      POST /api/admetCSV body {"taskId": <id>}             -> CSV, one molecule per row
                         (optional header X-API-KEY)

Constraints: <=1000 SMILES/request, <=5 rps. The service is async and reportedly unstable, so every call
goes through retry + exponential backoff, the predict endpoint has a documented fallback path, and the raw
CSV (plus the predict JSON) is cached to disk for reconstructibility (raw-output caching is IN SCOPE now,
CLAUDE.md §4a). Cache root resolves from ``ADMETLAB_CACHE_DIR`` or ``$FTO_ADMET_ROOT`` (both meant to sit
on ``/zfs``); everything else is configurable via ``ADMETLAB_*`` env vars (see README).

UNCERTAINTY (VERIFIED): for classification heads ADMETlab 3.0 turns its raw uncertainty score into a
per-endpoint high/low-confidence LABEL using that endpoint's max-Youden threshold. Request it with
``uncertain=true``. It is a BINARY confidence flag per endpoint, NOT a calibrated sigma, so it is routed
into the reserved ``Uncertainty.extra`` envelope as a flag, never assumed to be a variance (IO_SPEC §1 #2).

PLACEHOLDER SCHEMA / F-6 (the one residue): the CSV carries 119 endpoints, but the LITERAL column names
are only knowable from one live ``/api/admetCSV`` call (the reference wrapper passes the CSV through
without enumerating them). This adapter therefore parses the header GENERICALLY: whatever columns the live
CSV returns become ``endpoint_values`` (numeric cells coerced to float, the rest kept as strings) and are
mirrored verbatim in ``raw.columns``, with the raw header preserved in ``raw.header``. ``schema.py`` holds
the documented known heads plus a TODO to freeze the full 119-column contract once a live header is
captured. We do NOT fabricate column names (CLAUDE.md §5 no-fabricate; task status ends ``needs_aaran``).

F-16 (input standardization) is DEFERRED (CLAUDE.md §4a): this adapter feeds ADMETlab the single canonical
SMILES ``core`` hands it, UNMODIFIED. Server-side ``/api/washmol`` exists but is OFF by default
(``ADMETLAB_WASH=0``) so the pipeline's own upstream standardization stays the single source of truth
(reproducibility, task landmine). We do NOT silently pick a wash/protonation state here.

``--gpu`` is accepted for uniform-CLI compatibility and IGNORED (remote service, requires_gpu=False).

Robustness: an unparseable/empty SMILES yields a per-record result with null ``endpoint_values`` and the
reason in ``raw`` rather than raising; a whole-batch transport failure after the retry budget raises so the
dispatcher records a real error rather than a fabricated success (CLAUDE.md §5).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

MODEL = "admetlab3"

DEFAULT_BASE_URL = "https://admetlab3.scbdd.com"
WASH_PATH = "/api/washmol"
PREDICT_PATH = "/api/admet"
PREDICT_FALLBACK_PATH = "/api/single/admet"
CSV_PATH = "/api/admetCSV"

# Service-declared limits (IO_SPEC §1 #2): <=1000 SMILES/request, <=5 rps.
MAX_SMILES_PER_REQUEST = 1000
MAX_RPS = 5.0

# A transport callable: (url, body_bytes, headers) -> (status_code, response_bytes). Injectable so the
# unit test can drive the whole wash -> predict -> CSV flow with a fake transport (no network).
Transport = Callable[[str, bytes, dict[str, str]], "tuple[int, bytes]"]

_TASK_ID_RE = re.compile(r"task[_]?id", re.IGNORECASE)


def _env(name: str, default: str | None = None) -> str | None:
    """Read an ``ADMETLAB_``-prefixed env var (falls back to the bare name for FTO_ADMET_ROOT)."""
    return os.environ.get(name, default)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _default_cache_dir() -> Path:
    """Where raw CSV/JSON responses are cached. ADMETLAB_CACHE_DIR wins; else $FTO_ADMET_ROOT/cache."""
    explicit = os.environ.get("ADMETLAB_CACHE_DIR")
    if explicit:
        return Path(explicit).expanduser()
    root = os.environ.get("FTO_ADMET_ROOT")
    if root:
        return Path(root).expanduser() / "cache" / "admetlab3"
    return Path(".cache") / "admetlab3"


class AdmetLab3Error(RuntimeError):
    """A transport-level failure that survived the retry budget (real error, never fabricated away)."""


class AdmetLab3Client:
    """Thin retry/backoff/caching HTTP client for the three ADMETlab 3.0 endpoints.

    The transport is injectable (``transport=`` / default urllib) so the flow is unit-testable offline.
    Every POST is JSON in; the predict/wash endpoints return JSON, ``/api/admetCSV`` returns raw CSV bytes.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 4,
        backoff: float = 1.5,
        rps: float = MAX_RPS,
        cache_dir: Path | None = None,
        transport: Transport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.backoff = backoff
        self.min_interval = 1.0 / rps if rps and rps > 0 else 0.0
        self.cache_dir = cache_dir or _default_cache_dir()
        self._transport = transport or self._urllib_transport
        self._last_request_ts = 0.0

    # -- transport ------------------------------------------------------------------------------------

    def _urllib_transport(self, url: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
        """Default stdlib transport: POST ``body`` to ``url``; return (status, response bytes)."""
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.getcode(), resp.read()
        except urllib.error.HTTPError as exc:  # 4xx/5xx: keep status + body so retry logic can decide
            return exc.code, exc.read()

    def _throttle(self) -> None:
        """Keep to <=MAX_RPS by spacing successive requests at least ``min_interval`` apart."""
        if self.min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request_ts
        wait = self.min_interval - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_ts = time.monotonic()

    def _post(self, path: str, payload: dict[str, Any]) -> tuple[int, bytes]:
        """One throttled POST with a JSON body and the optional X-API-KEY header."""
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "*/*"}
        if self.api_key:
            headers["X-API-KEY"] = self.api_key
        self._throttle()
        return self._transport(url, body, headers)

    def _post_with_retry(self, path: str, payload: dict[str, Any], want_csv: bool = False) -> bytes:
        """POST with exponential backoff. Retries transport errors, 5xx, and (for CSV) not-ready replies.

        Returns the raw response bytes on success. Raises ``AdmetLab3Error`` once the retry budget is
        exhausted (a real error the dispatcher records, never swallowed into a fake pass).
        """
        last_detail = ""
        for attempt in range(self.max_retries):
            try:
                status, body = self._post(path, payload)
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                status, body, last_detail = 0, b"", f"transport error: {type(exc).__name__}: {exc}"
            else:
                if 200 <= status < 300:
                    if not want_csv or self._looks_like_csv(body):
                        return body
                    last_detail = f"result not ready yet (status {status}, body not CSV)"
                elif 400 <= status < 500:
                    # A client error will not fix itself on retry; surface it immediately.
                    raise AdmetLab3Error(
                        f"POST {path} returned {status}: {body[:400].decode('utf-8', 'replace')}"
                    )
                else:
                    last_detail = f"server error {status}: {body[:200].decode('utf-8', 'replace')}"

            if attempt < self.max_retries - 1:
                time.sleep(self.backoff ** attempt)
        raise AdmetLab3Error(f"POST {path} failed after {self.max_retries} attempts ({last_detail})")

    @staticmethod
    def _looks_like_csv(body: bytes) -> bool:
        """Heuristic: a ready CSV has a comma and a newline and is not a JSON error envelope."""
        if not body:
            return False
        head = body[:64].lstrip()
        if head[:1] in (b"{", b"["):
            return False
        text = body[:4096].decode("utf-8", "replace")
        return ("," in text) and ("\n" in text or "\r" in text)

    # -- flow -----------------------------------------------------------------------------------------

    def wash(self, smiles: list[str]) -> list[str]:
        """POST /api/washmol; return the standardized SMILES, falling back to the inputs on any mismatch.

        The washmol *response* shape is not part of the verified contract (only the endpoint + request
        body are), so parse defensively: pull a same-length list of strings if the reply provides one,
        otherwise keep the caller's SMILES. Wash is OFF by default (see run()); when a caller opts in we
        still never let an unrecognized reply silently drop molecules.
        """
        body = self._post_with_retry(WASH_PATH, {"SMILES": smiles})
        try:
            data = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return smiles
        washed = _find_smiles_list(data)
        if washed and len(washed) == len(smiles):
            return washed
        return smiles

    def submit(self, smiles: list[str], feature: bool, uncertain: bool) -> tuple[str, bytes]:
        """POST /api/admet (fallback /api/single/admet); return (taskId, raw predict-JSON bytes)."""
        payload = {"SMILES": smiles, "feature": feature, "uncertain": uncertain}
        try:
            body = self._post_with_retry(PREDICT_PATH, payload)
        except AdmetLab3Error:
            body = self._post_with_retry(PREDICT_FALLBACK_PATH, payload)
        try:
            data = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise AdmetLab3Error(f"predict reply was not JSON: {exc}") from exc
        task_id = _extract_task_id(data)
        if not task_id:
            raise AdmetLab3Error(f"predict reply carried no taskId: {str(data)[:400]}")
        return task_id, body

    def fetch_csv(self, task_id: str) -> bytes:
        """POST /api/admetCSV; poll (via retry) until the async result CSV is ready. Returns raw CSV bytes."""
        return self._post_with_retry(CSV_PATH, {"taskId": task_id}, want_csv=True)

    def cache_raw(self, task_id: str, name: str, body: bytes) -> Path:
        """Write a raw response to the cache dir keyed by taskId, for later reconstruction (§4a)."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        safe_task = re.sub(r"[^A-Za-z0-9_.-]", "_", task_id)[:80] or "task"
        path = self.cache_dir / f"{safe_task}.{name}"
        path.write_bytes(body)
        return path


def _find_smiles_list(data: Any) -> list[str] | None:
    """Best-effort: pull a list of SMILES strings out of an arbitrary washmol reply (defensive)."""
    if isinstance(data, list) and all(isinstance(x, str) for x in data):
        return list(data)
    if isinstance(data, dict):
        for key in ("smiles", "SMILES", "washed", "data", "result"):
            if key in data:
                got = _find_smiles_list(data[key])
                if got:
                    return got
    return None


def _extract_task_id(data: Any) -> str | None:
    """Recursively search a predict reply for a task-id value (keys like taskId / task_id, any nesting)."""
    if isinstance(data, dict):
        for key, val in data.items():
            if isinstance(key, str) and _TASK_ID_RE.fullmatch(key.replace(" ", "")) and val:
                return str(val)
        for val in data.values():
            found = _extract_task_id(val)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _extract_task_id(item)
            if found:
                return found
    return None


def parse_inputs(text: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse the ``--input`` payload into ``(records, single)`` (same contract as the CODE-PKG adapters).

    Accepts a single ``InputRecord`` JSON object (single=True), a JSON array of them (single=False), or a
    ``.smi`` file (``<SMILES><whitespace><title>`` per line, ``#`` comments; single=False).
    """
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        data = json.loads(stripped)
        if isinstance(data, dict):
            return [data], True
        if isinstance(data, list):
            return list(data), False
        raise ValueError("input JSON must be an object or an array of objects")

    records: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        mol_id = parts[1] if len(parts) > 1 else None
        records.append({"smiles": parts[0], "mol_id": mol_id})
    return records, False


def _coerce(cell: str) -> float | int | str | bool | None:
    """Coerce a CSV cell to a JSON-safe scalar: number where it parses, else the trimmed string / None."""
    if cell is None:
        return None
    text = cell.strip()
    if text == "" or text.upper() in ("NA", "N/A", "NAN", "NONE", "NULL"):
        return None
    try:
        i = int(text)
        return i
    except ValueError:
        pass
    try:
        f = float(text)
        if f != f or f in (float("inf"), float("-inf")):  # NaN / inf -> None
            return None
        return f
    except ValueError:
        return text


def parse_csv(csv_text: str) -> tuple[list[str], list[dict[str, Any]]]:
    """Parse the admetCSV body into (header, rows). Rows are {column_name: coerced cell}."""
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    if not rows:
        return [], []
    header = [h.strip() for h in rows[0]]
    records: list[dict[str, Any]] = []
    for raw in rows[1:]:
        if not any(cell.strip() for cell in raw):
            continue
        record = {header[i] if i < len(header) else f"col_{i}": _coerce(cell) for i, cell in enumerate(raw)}
        records.append(record)
    return header, records


def _provenance(base_url: str, header_len: int) -> dict[str, Any]:
    """Provenance stamped onto every emitted record."""
    return {
        "model": MODEL,
        "method": "ADMETlab 3.0 web API (DMPNN-Des: multi-task DMPNN + RDKit 2D descriptors); 119 endpoints",
        "service": base_url,
        "transport": "POST /api/admet -> taskId -> POST /api/admetCSV (wash via /api/washmol)",
        "csv_columns_seen": header_len,
        "citation": "Fu L, et al. ADMETlab 3.0. Nucleic Acids Res 52(W1):W422 (2024). doi:10.1093/nar/gkae236",
        "license": "web service (SCBDD); academic use per site terms",
        "schema_status": "PLACEHOLDER - literal 119-column contract pending one live /api/admetCSV header capture (F-6)",
    }


def _uncertainty_envelope(uncertain: bool) -> dict[str, Any]:
    """The reserved Uncertainty envelope for one record.

    ADMETlab's DIRECT signal is a per-endpoint Youden-index high/low-confidence FLAG (binary), not a
    calibrated sigma, so it lives in ``extra`` as a flag rather than in ``ad_index`` / ``conf_index``. The
    per-column flag split cannot be materialized until the 119-column header is captured (F-6), so we record
    what was requested and leave the mapping as a TODO the header capture resolves.
    """
    return {
        "extra": {
            "uncertain_requested": uncertain,
            "confidence_flag_type": "per-endpoint Youden-index high/low-confidence (binary, NOT a sigma)",
            "todo": "map the per-endpoint confidence-flag columns once the live 119-column header is captured (F-6)",
        }
    }


def record_for(
    row: dict[str, Any] | None,
    header: list[str],
    rec: dict[str, Any],
    base_url: str,
    uncertain: bool,
    error: str | None = None,
) -> dict[str, Any]:
    """Assemble one ``OutputRecord``-shaped dict from a parsed CSV row (or an error placeholder)."""
    smiles = str(rec.get("smiles") or "").strip()
    mol_id = rec.get("mol_id")
    base: dict[str, Any] = {
        "model": MODEL,
        "provenance": _provenance(base_url, len(header)),
        "uncertainty": _uncertainty_envelope(uncertain),
    }
    if error is not None or row is None:
        return {
            **base,
            "endpoint_values": {},
            "raw": {"error": error or "no result row returned", "smiles": smiles, "mol_id": mol_id},
        }
    # Placeholder schema: every returned column becomes an endpoint_value (coerced) and is mirrored
    # verbatim in raw.columns. Literal names are captured live (F-6), not fabricated here.
    return {
        **base,
        "endpoint_values": dict(row),
        "raw": {
            "smiles": smiles,
            "mol_id": mol_id,
            "header": header,
            "columns": dict(row),
        },
    }


def run_batch(
    records: list[dict[str, Any]],
    client: AdmetLab3Client,
    feature: bool,
    uncertain: bool,
    wash: bool,
) -> list[dict[str, Any]]:
    """Drive wash -> predict -> admetCSV for one batch and align CSV rows back to the input records.

    Rows are aligned POSITIONALLY (the service returns one row per submitted SMILES, in order). Empty
    SMILES are dropped from the request but still get a null result record so the output length matches the
    input length (one bad molecule never sinks the batch; uniform-CLI contract).
    """
    if len(records) > MAX_SMILES_PER_REQUEST:
        raise AdmetLab3Error(
            f"batch of {len(records)} exceeds ADMETlab's {MAX_SMILES_PER_REQUEST}-SMILES/request limit; "
            "core should chunk before dispatch"
        )

    # Map each input position to its SMILES; blanks are held out of the request.
    smiles_by_pos: dict[int, str] = {}
    for i, rec in enumerate(records):
        s = str(rec.get("smiles") or "").strip()
        if s:
            smiles_by_pos[i] = s

    if not smiles_by_pos:
        return [
            record_for(None, [], rec, client.base_url, uncertain, error="empty SMILES")
            for rec in records
        ]

    positions = list(smiles_by_pos.keys())
    smiles_list = [smiles_by_pos[p] for p in positions]
    if wash:
        smiles_list = client.wash(smiles_list)

    task_id, predict_body = client.submit(smiles_list, feature=feature, uncertain=uncertain)
    client.cache_raw(task_id, "predict.json", predict_body)
    csv_body = client.fetch_csv(task_id)
    client.cache_raw(task_id, "result.csv", csv_body)

    header, rows = parse_csv(csv_body.decode("utf-8", "replace"))
    row_by_pos = {positions[j]: rows[j] for j in range(min(len(positions), len(rows)))}

    outputs: list[dict[str, Any]] = []
    for i, rec in enumerate(records):
        if i not in smiles_by_pos:
            outputs.append(record_for(None, header, rec, client.base_url, uncertain, error="empty SMILES"))
        elif i in row_by_pos:
            outputs.append(record_for(row_by_pos[i], header, rec, client.base_url, uncertain))
        else:
            outputs.append(
                record_for(None, header, rec, client.base_url, uncertain, error="no CSV row for this position")
            )
    return outputs


def build_client() -> AdmetLab3Client:
    """Construct the client from the ``ADMETLAB_*`` environment (all optional; sane defaults)."""
    return AdmetLab3Client(
        base_url=_env("ADMETLAB_BASE_URL", DEFAULT_BASE_URL) or DEFAULT_BASE_URL,
        api_key=_env("ADMETLAB_API_KEY"),
        timeout=_env_float("ADMETLAB_TIMEOUT", 60.0),
        max_retries=_env_int("ADMETLAB_MAX_RETRIES", 4),
        backoff=_env_float("ADMETLAB_BACKOFF", 1.5),
        rps=min(_env_float("ADMETLAB_RPS", MAX_RPS), MAX_RPS),
        cache_dir=_default_cache_dir(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ADMETlab 3.0 web-API adapter (uniform model CLI).")
    parser.add_argument("--input", required=True, type=Path, help="pipeline input (InputRecord JSON, JSON array, or .smi)")
    parser.add_argument("--output", required=True, type=Path, help="where to write the OutputRecord JSON")
    parser.add_argument("--gpu", type=int, default=None, help="accepted for uniform CLI; IGNORED (remote service)")
    args = parser.parse_args(argv)

    records, single = parse_inputs(args.input.read_text(encoding="utf-8"))

    feature = _env_bool("ADMETLAB_FEATURE", False)
    uncertain = _env_bool("ADMETLAB_UNCERTAIN", True)  # opt in to the Youden confidence flags by default
    wash = _env_bool("ADMETLAB_WASH", False)  # OFF by default: core standardizes upstream (reproducibility)

    client = build_client()
    outputs = run_batch(records, client, feature=feature, uncertain=uncertain, wash=wash)
    payload: Any = outputs[0] if (single and len(outputs) == 1) else outputs

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
