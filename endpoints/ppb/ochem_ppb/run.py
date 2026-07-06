#!/usr/bin/env python
"""ochem_ppb adapter - OCHEM plasma-protein-binding via the async REST model web-service (CODE-API).

Uniform model CLI (CLAUDE.md §2, SETTLED §6):

    python run.py --input <path> --output <path> [--gpu N]

Unlike the isolated-env adapters (pksmart, etc.) this is an **api-model**: it has no upstream package
to install, so it runs a pure-stdlib HTTP client (``urllib``) and can run in the core env directly. It
follows the same folder/adapter shape and writes plain JSON matching ``core.schemas.OutputRecord``; the
dispatcher validates that JSON against the real schema on collection.

Endpoint: ppb (plasma protein binding). The common ppb quantity is **fraction bound (0-1)**, direction
↑ = more bound / less free (IO_SPEC §2). Not a gate; a modulator. Single tool acceptable.

What this adapter does (async two-step REST + poll, IO_SPEC §1 #18 / Provenance §20):

    submit:  GET  https://ochem.eu/modelservice/getPrediction.do?modelId=<MODEL_ID>&mol=<MOLECULE>
             -> returns a task id (the service queues the prediction)
    poll:    GET  https://ochem.eu/modelservice/getPrediction.do?taskId=<id>   (every 5-10 s)
             -> until the task reports ready, then carries the prediction(s)

Batching is via the SDF record separator ``$$$$`` (IO_SPEC §1 #18.A): several molecules are concatenated
into one ``mol`` payload and the returned predictions align **positionally** to the input order.

Robustness / infra (CLAUDE.md §4a, the api-model gate):
  - retry with exponential backoff on transport errors,
  - a raw-response cache on disk (raw-output caching IS in scope): a result stays reconstructible after
    the upstream service silently changes; a cache hit skips the network entirely,
  - one bad molecule (missing prediction) yields a null record with the reason in ``raw``, never a crash.

=== THE TWO LITERALS THAT MADE THIS NEEDS_AARAN (one now resolved, one still open) ===

1. modelId - RESOLVED. The project owner supplied the public model id: **MODEL_ID = 1121**
   ("Plasma protein binding_ASNN_[ALogPS, OEstate]", OCHEM article A29 = ochem.eu/article/29;
   Han et al., Eur. J. Pharm. Sci. 2024, 204:106946; PubMed 39490636). No login is needed for a public
   model id. See the README for the article/29 -> 1121 mapping.

2. The exact REST **response field names** and a **live fixture prediction** - STILL OPEN (needs_aaran).
   OCHEM's own docs (docs.ochem.eu) and the live model web-service were **unreachable from the build
   environment** (TLS certificate could not be verified for ochem.eu:443; rest.ochem.eu:443 refused the
   connection), so the response envelope (JSON vs XML, the exact key holding the value / accuracy / DM,
   the exact "task ready" signal) could NOT be verified against a real run. The field names below are
   **documented placeholders** grouped in one constant block so a single live run corrects them without
   touching any logic. The no-fabricate rule (CLAUDE.md §5) forbids inventing a "verified" header, so the
   transport is written tolerantly (tries JSON, then XML, then a small set of plausible key names) and the
   task's residue is the one live call. See ``TODO(needs_aaran)`` markers.

=== THE OUTPUT TRANSFORM (do not get this wrong) ===

The ASNN consensus model (id 1121) predicts PPB in **LogIt (logit) units, NOT a raw percentage**
(project-owner directive). Convert to percent bound via the inverse logit, then to the schema's fraction:

    pct_bound      = 100 / (1 + exp(-logit))          # inverse logit -> % bound
    fraction_bound = pct_bound / 100 = sigmoid(logit) # 0-1, the ppb aggregator's common quantity

Treating the raw prediction as a percent (or a fraction) directly would be wrong. ``endpoint_values``
carries both ``fraction_bound`` (0-1, the primary) and ``ppb_percent_bound`` (%, for readability); both
are ↑ = more bound.

ASNN emits a native prediction confidence / distance-to-model (DM) - one of the few models in the set
with a real native uncertainty (CLAUDE.md §3). It is routed into the reserved ``uncertainty`` envelope
(``extra.distance_to_model`` + ``extra.accuracy_error``); the operational AD *rule* that would turn a DM
into an in/out-of-domain call is DEFERRED (CLAUDE.md §4a), so ``ad_index`` / ``ad_in_domain`` are left
unset here rather than fabricated from an undecided threshold.

Input: OCHEM curated its PPB training set on the **desalted neutral parent** (salts/water stripped), so
this model expects a desalted neutral molecule. That diverges from the pipeline's single canonical input
under the DEFERRED F-16 standardization decision (CLAUDE.md §4a): we FLAG the divergence (README +
``provenance.input_expectation``) and feed the canonical input as-is; we do NOT silently pick a
protonation/desalting state per model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable

MODEL = "ochem_ppb"

# --- The one resolved literal ---------------------------------------------------------------------
# Public OCHEM model id for the article/29 consensus PPB model (project-owner supplied; no login for a
# public id). "Plasma protein binding_ASNN_[ALogPS, OEstate]" (Han et al. EJPS 2024;204:106946).
MODEL_ID = 1121

# --- Service endpoints ----------------------------------------------------------------------------
# TODO(needs_aaran): confirm the exact submit/poll URLs against docs.ochem.eu on a reachable network.
# The documented form is a single endpoint used both to submit (modelId+mol) and to poll (taskId).
BASE_URL = "https://ochem.eu/modelservice"
PREDICTION_ENDPOINT = f"{BASE_URL}/getPrediction.do"
# Alternate documented host (IO_SPEC §1 #18.A): rest.ochem.eu/predict - kept as a fallback note.
ALT_ENDPOINT = "https://rest.ochem.eu/predict"

# --- Response field-name placeholders (UNVERIFIED - see the needs_aaran note in the module docstring)
# TODO(needs_aaran): replace each with the real field name from one live getPrediction.do response.
# The parser tries each of these plus a few common synonyms, so a wrong guess here degrades gracefully
# to "prediction not found" (a null record with the raw body cached), never a fabricated value.
TASK_ID_KEYS = ("taskId", "task_id", "id")
STATUS_KEYS = ("status", "state")
PREDICTIONS_KEYS = ("predictions", "results", "rows", "predicted")
VALUE_KEYS = ("prediction", "value", "predicted", "result")  # holds the PPB value in LOGIT units
ACCURACY_KEYS = ("accuracy", "error", "std", "predictionError", "rmse")  # accuracy/error estimate
DM_KEYS = ("dm", "distanceToModel", "distance_to_model", "AD", "applicabilityDomain")  # DM / AD distance
# Status strings that mean "still running" (poll again) vs anything else = terminal.
PENDING_STATUSES = frozenset({"pending", "queued", "running", "in_progress", "processing", "0"})

# --- Batching -------------------------------------------------------------------------------------
SDF_SEPARATOR = "$$$$"  # IO_SPEC §1 #18.A: batch several molecules in one `mol` payload.

# --- Defaults (all overridable on the CLI) --------------------------------------------------------
DEFAULT_POLL_INTERVAL_S = 7.0   # "poll every 5-10 s" (IO_SPEC §1 #18.A)
DEFAULT_MAX_WAIT_S = 600.0      # give up after 10 min of polling one task
DEFAULT_RETRIES = 4             # transport-level retries per HTTP call
DEFAULT_BACKOFF_BASE_S = 1.0    # exponential backoff base
DEFAULT_TIMEOUT_S = 30.0        # per-request socket timeout


def _provenance() -> dict[str, Any]:
    """Provenance stamped onto every emitted record."""
    return {
        "model": MODEL,
        "method": (
            "OCHEM consensus PPB model (ASNN over ALogPS + E-state), async REST model web-service; "
            "prediction is in LogIt units, converted to % bound then fraction bound"
        ),
        "model_id": MODEL_ID,
        "model_page": "https://ochem.eu/article/29",
        "citation": (
            "Han R, et al. Consensus modeling of plasma protein binding. "
            "Eur J Pharm Sci 2024;204:106946. PMID 39490636."
        ),
        "access_tag": "CODE-API",
        "license": "OCHEM public model web-service; see ochem.eu terms",
        # Flag the desalted-neutral expectation against the DEFERRED F-16 standardization (CLAUDE.md §4a).
        "input_expectation": "desalted neutral parent (F-16 divergence; flagged, not silently applied)",
    }


# ==================================================================================================
# The output transform: LogIt -> % bound -> fraction bound.
# ==================================================================================================
def logit_to_fraction(logit: float) -> float:
    """Inverse logit (numerically stable sigmoid): LogIt units -> fraction bound in (0, 1).

    ``fraction_bound = 1 / (1 + exp(-logit))``. Stable for large |logit| (no overflow either side).
    """
    if logit >= 0.0:
        return 1.0 / (1.0 + math.exp(-logit))
    e = math.exp(logit)
    return e / (1.0 + e)


def logit_to_percent(logit: float) -> float:
    """LogIt units -> percent bound in (0, 100): ``100 / (1 + exp(-logit))`` (project-owner directive)."""
    return 100.0 * logit_to_fraction(logit)


def _f(value: Any) -> float | None:
    """Coerce a scalar to a finite float, or ``None`` if missing/non-finite/unparseable."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


# ==================================================================================================
# Transport: a single injectable primitive (`_transport`) so the whole client is trivially mockable.
# ==================================================================================================
def _transport(url: str, *, timeout: float = DEFAULT_TIMEOUT_S) -> str:
    """The one network primitive: GET ``url`` and return the response body as text.

    Every HTTP call in this module goes through here, so a test monkeypatches exactly this one function
    to drive the submit -> poll -> ready sequence with no network. Kept pure-stdlib (``urllib``) so the
    api-model needs no third-party dependency.
    """
    req = urllib.request.Request(url, headers={"Accept": "application/json, text/xml, */*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https OCHEM host
        return resp.read().decode("utf-8", errors="replace")


def _request_with_retry(
    url: str,
    *,
    retries: int = DEFAULT_RETRIES,
    backoff_base: float = DEFAULT_BACKOFF_BASE_S,
    timeout: float = DEFAULT_TIMEOUT_S,
    transport: Callable[..., str] = _transport,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Call ``transport(url)`` with exponential backoff on transport errors.

    Retries ``URLError`` / ``HTTPError`` / ``TimeoutError`` up to ``retries`` times, sleeping
    ``backoff_base * 2**attempt`` between tries. Re-raises the last error if all attempts fail so the
    caller can surface it (never a fabricated success). ``transport`` and ``sleep`` are injectable for tests.
    """
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return transport(url, timeout=timeout)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt >= retries:
                break
            sleep(backoff_base * (2 ** attempt))
    raise RuntimeError(f"OCHEM request failed after {retries + 1} attempts: {last_exc!r}")


# ==================================================================================================
# Response parsing (tolerant: JSON first, then XML, then plausible key synonyms).
# ==================================================================================================
def _first_key(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """Return the first present (case-insensitive) key's value from ``mapping``, else ``None``."""
    lowered = {str(k).lower(): v for k, v in mapping.items()}
    for k in keys:
        if k.lower() in lowered:
            return lowered[k.lower()]
    return None


def parse_service_response(text: str) -> dict[str, Any]:
    """Parse a getPrediction.do body into a normalized dict, tolerating JSON or XML.

    Returns ``{"task_id", "status", "predictions": [ {"value", "accuracy", "dm"} ... ], "raw": text}``.
    Field extraction uses the placeholder key sets above; unknown shapes yield an empty ``predictions``
    list (a graceful "not found", surfaced downstream as a null record) rather than a guess.
    """
    text = (text or "").strip()
    doc: dict[str, Any] | None = None

    # 1) JSON
    if text[:1] in ("{", "["):
        try:
            loaded = json.loads(text)
            doc = loaded if isinstance(loaded, dict) else {"predictions": loaded}
        except json.JSONDecodeError:
            doc = None

    # 2) XML (OCHEM's model service has historically returned small XML envelopes)
    if doc is None and text[:1] == "<":
        try:
            root = ET.fromstring(text)
            doc = {child.tag: child.text for child in root}
            doc.setdefault(root.tag, root.text)
            # collect any repeated prediction-like children positionally
            preds = [
                {c.tag: c.text for c in node}
                for node in root
                if len(list(node)) > 0
            ]
            if preds:
                doc["predictions"] = preds
            # also fold root attributes (task id / status often live there)
            doc.update(root.attrib)
        except ET.ParseError:
            doc = None

    if doc is None:
        return {"task_id": None, "status": None, "predictions": [], "raw": text}

    task_id = _first_key(doc, TASK_ID_KEYS)
    status = _first_key(doc, STATUS_KEYS)
    raw_preds = _first_key(doc, PREDICTIONS_KEYS)

    predictions: list[dict[str, Any]] = []
    if isinstance(raw_preds, list):
        for item in raw_preds:
            if isinstance(item, dict):
                predictions.append({
                    "value": _f(_first_key(item, VALUE_KEYS)),
                    "accuracy": _f(_first_key(item, ACCURACY_KEYS)),
                    "dm": _f(_first_key(item, DM_KEYS)),
                })
            else:
                predictions.append({"value": _f(item), "accuracy": None, "dm": None})
    elif raw_preds is None:
        # Single-molecule shape: the value/accuracy/dm may sit at the top level.
        top_value = _f(_first_key(doc, VALUE_KEYS))
        if top_value is not None:
            predictions.append({
                "value": top_value,
                "accuracy": _f(_first_key(doc, ACCURACY_KEYS)),
                "dm": _f(_first_key(doc, DM_KEYS)),
            })

    return {
        "task_id": str(task_id) if task_id is not None else None,
        "status": str(status) if status is not None else None,
        "predictions": predictions,
        "raw": text,
    }


def _is_ready(parsed: dict[str, Any]) -> bool:
    """A task is ready when it has predictions and its status is not a pending marker."""
    status = (parsed.get("status") or "").strip().lower()
    if status in PENDING_STATUSES:
        return False
    return bool(parsed.get("predictions"))


# ==================================================================================================
# Submit + poll.
# ==================================================================================================
def _build_mol_payload(smiles_list: list[str]) -> str:
    """Join a batch of SMILES with the SDF ``$$$$`` separator into one ``mol`` payload (IO_SPEC §1 #18.A)."""
    return f"\n{SDF_SEPARATOR}\n".join(smiles_list)


def submit(
    smiles_list: list[str],
    *,
    model_id: int = MODEL_ID,
    endpoint: str = PREDICTION_ENDPOINT,
    retries: int = DEFAULT_RETRIES,
    timeout: float = DEFAULT_TIMEOUT_S,
    transport: Callable[..., str] = _transport,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Submit a batch; return the parsed first response (may already carry a task id or predictions)."""
    mol = _build_mol_payload(smiles_list)
    query = urllib.parse.urlencode({"modelId": model_id, "mol": mol})
    url = f"{endpoint}?{query}"
    body = _request_with_retry(url, retries=retries, timeout=timeout, transport=transport, sleep=sleep)
    return parse_service_response(body)


def poll_until_ready(
    task_id: str,
    *,
    endpoint: str = PREDICTION_ENDPOINT,
    poll_interval: float = DEFAULT_POLL_INTERVAL_S,
    max_wait: float = DEFAULT_MAX_WAIT_S,
    retries: int = DEFAULT_RETRIES,
    timeout: float = DEFAULT_TIMEOUT_S,
    transport: Callable[..., str] = _transport,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Poll ``getPrediction.do?taskId=<id>`` every ``poll_interval`` s until ready or ``max_wait`` elapses.

    Raises ``TimeoutError`` if the task never reports ready. ``sleep`` / ``clock`` / ``transport`` are
    injectable so a test drives the loop deterministically with no wall-clock wait.
    """
    start = clock()
    query = urllib.parse.urlencode({"taskId": task_id})
    url = f"{endpoint}?{query}"
    while True:
        body = _request_with_retry(url, retries=retries, timeout=timeout, transport=transport, sleep=sleep)
        parsed = parse_service_response(body)
        if _is_ready(parsed):
            return parsed
        if clock() - start >= max_wait:
            raise TimeoutError(
                f"OCHEM task {task_id} not ready after {max_wait:.0f}s "
                f"(last status={parsed.get('status')!r})"
            )
        sleep(poll_interval)


def fetch_predictions(
    smiles_list: list[str],
    *,
    model_id: int = MODEL_ID,
    endpoint: str = PREDICTION_ENDPOINT,
    poll_interval: float = DEFAULT_POLL_INTERVAL_S,
    max_wait: float = DEFAULT_MAX_WAIT_S,
    retries: int = DEFAULT_RETRIES,
    timeout: float = DEFAULT_TIMEOUT_S,
    transport: Callable[..., str] = _transport,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Full submit -> (poll) -> ready path for one batch. Returns the parsed ready response.

    If the submit already carries predictions (a synchronous small-batch reply), returns it directly;
    otherwise polls the returned task id until ready.
    """
    submitted = submit(
        smiles_list, model_id=model_id, endpoint=endpoint,
        retries=retries, timeout=timeout, transport=transport, sleep=sleep,
    )
    if _is_ready(submitted):
        return submitted
    task_id = submitted.get("task_id")
    if not task_id:
        raise RuntimeError(
            f"OCHEM submit returned neither predictions nor a task id (status={submitted.get('status')!r}); "
            f"the REST envelope may differ from the documented placeholder - see needs_aaran TODO"
        )
    return poll_until_ready(
        task_id, endpoint=endpoint, poll_interval=poll_interval, max_wait=max_wait,
        retries=retries, timeout=timeout, transport=transport, sleep=sleep, clock=clock,
    )


# ==================================================================================================
# Raw-response cache (CLAUDE.md §4a: raw-output caching is IN SCOPE).
# ==================================================================================================
def default_cache_dir() -> Path:
    """Resolve the raw-response cache dir. Prefer ``$FTO_ADMET_ROOT/cache/ochem_ppb`` (on /zfs), else a
    repo-local ``.cache/ochem_ppb`` fallback so the adapter still runs off-box (e.g. in a mocked test)."""
    root = os.environ.get("FTO_ADMET_ROOT")
    if root:
        return Path(root).expanduser() / "cache" / MODEL
    return Path(__file__).resolve().parent / ".cache"


def _cache_key(model_id: int, smiles: str) -> str:
    """Stable cache key for one (model, molecule) pair."""
    return hashlib.sha256(f"{model_id}|{smiles}".encode()).hexdigest()


def cache_load(cache_dir: Path, model_id: int, smiles: str) -> dict[str, Any] | None:
    """Return a cached prediction dict for ``smiles`` if present, else ``None``."""
    path = cache_dir / f"{_cache_key(model_id, smiles)}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def cache_store(cache_dir: Path, model_id: int, smiles: str, entry: dict[str, Any]) -> None:
    """Persist one raw+parsed prediction entry so a result stays reconstructible after upstream drift."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{_cache_key(model_id, smiles)}.json"
    path.write_text(json.dumps(entry, indent=2), encoding="utf-8")


# ==================================================================================================
# Record assembly.
# ==================================================================================================
def record_for(rec: dict[str, Any], prediction: dict[str, Any] | None) -> dict[str, Any]:
    """Build one ``OutputRecord``-shaped dict from an input record + its (LogIt) prediction.

    ``prediction`` is ``{"value": <logit>, "accuracy": <err|None>, "dm": <distance|None>}`` or ``None``
    when the service returned no prediction for this molecule (null record + reason in ``raw``).
    """
    smiles = str(rec.get("smiles") or "").strip()
    mol_id = rec.get("mol_id")
    base: dict[str, Any] = {"model": MODEL, "provenance": _provenance()}

    if prediction is None or _f(prediction.get("value")) is None:
        return {
            **base,
            "endpoint_values": {"fraction_bound": None, "ppb_percent_bound": None},
            "uncertainty": None,
            "raw": {
                "error": "no prediction returned for this molecule",
                "smiles": smiles,
                "mol_id": mol_id,
                "prediction": prediction,
            },
        }

    logit = float(prediction["value"])
    fraction = logit_to_fraction(logit)
    percent = 100.0 * fraction

    accuracy = _f(prediction.get("accuracy"))
    dm = _f(prediction.get("dm"))
    # Native ASNN uncertainty into the reserved envelope. DM is a distance (unbounded), not a 0-1 index,
    # and the AD *rule* is DEFERRED (CLAUDE.md §4a), so it goes in `extra`, NOT `ad_index`; likewise the
    # accuracy/error estimate is in LOGIT units (same space as the raw prediction) and is kept in `extra`
    # with that unit noted, rather than forced into a %-space field.
    uncertainty: dict[str, Any] | None = None
    if accuracy is not None or dm is not None:
        uncertainty = {
            "extra": {
                "distance_to_model": dm,
                "accuracy_error_logit": accuracy,
                "note": "ASNN native DM + accuracy; AD threshold policy DEFERRED (F-7/CLAUDE.md §4a)",
            }
        }

    return {
        **base,
        "endpoint_values": {
            "fraction_bound": fraction,        # 0-1, ↑ = more bound (the ppb aggregator's common quantity)
            "ppb_percent_bound": percent,      # %, ↑ = more bound (readability companion)
        },
        "uncertainty": uncertainty,
        "raw": {
            "smiles": smiles,
            "mol_id": mol_id,
            "logit": logit,                    # verbatim upstream prediction, in LogIt units
            "prediction": prediction,
            "transform": "pct = 100/(1+exp(-logit)); fraction = pct/100",
        },
    }


def predict_records(
    records: list[dict[str, Any]],
    *,
    model_id: int = MODEL_ID,
    cache_dir: Path | None = None,
    use_network: bool = True,
    refresh: bool = False,
    endpoint: str = PREDICTION_ENDPOINT,
    poll_interval: float = DEFAULT_POLL_INTERVAL_S,
    max_wait: float = DEFAULT_MAX_WAIT_S,
    retries: int = DEFAULT_RETRIES,
    timeout: float = DEFAULT_TIMEOUT_S,
    transport: Callable[..., str] = _transport,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> list[dict[str, Any]]:
    """Predict PPB for a batch of input records: cache-first, then one batched submit+poll for the misses.

    Cache hits skip the network entirely. Cache misses are submitted together as one ``$$$$`` batch, the
    task is polled to ready, and predictions align positionally to the miss order. Every fetched result is
    written back to the cache (raw + parsed). ``use_network=False`` serves cache-only (misses -> null
    records), which is how the mocked/offline path behaves without a reachable OCHEM.
    """
    cache_dir = cache_dir or default_cache_dir()

    predictions: list[dict[str, Any] | None] = [None] * len(records)
    miss_indices: list[int] = []
    miss_smiles: list[str] = []

    for i, rec in enumerate(records):
        smiles = str(rec.get("smiles") or "").strip()
        if not smiles:
            predictions[i] = None
            continue
        if not refresh:
            cached = cache_load(cache_dir, model_id, smiles)
            if cached is not None:
                predictions[i] = cached.get("parsed_prediction")
                continue
        miss_indices.append(i)
        miss_smiles.append(smiles)

    if miss_smiles and use_network:
        ready = fetch_predictions(
            miss_smiles, model_id=model_id, endpoint=endpoint, poll_interval=poll_interval,
            max_wait=max_wait, retries=retries, timeout=timeout, transport=transport,
            sleep=sleep, clock=clock,
        )
        preds = ready.get("predictions", [])
        for pos, idx in enumerate(miss_indices):
            pred = preds[pos] if pos < len(preds) else None
            predictions[idx] = pred
            # Cache raw batch body + this molecule's parsed slice (reconstructible after upstream drift).
            cache_store(cache_dir, model_id, miss_smiles[pos], {
                "smiles": miss_smiles[pos],
                "model_id": model_id,
                "parsed_prediction": pred,
                "raw_response": ready.get("raw"),
                "batch_position": pos,
            })

    return [record_for(records[i], predictions[i]) for i in range(len(records))]


# ==================================================================================================
# Input parsing + CLI (identical contract to the isolated-env adapters).
# ==================================================================================================
def parse_inputs(text: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse ``--input`` into ``(records, single)``: an InputRecord object, an array, or a ``.smi`` file."""
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OCHEM PPB adapter (uniform model CLI; async REST).")
    parser.add_argument("--input", required=True, type=Path, help="InputRecord JSON, JSON array, or .smi")
    parser.add_argument("--output", required=True, type=Path, help="where to write the OutputRecord JSON")
    parser.add_argument("--gpu", type=int, default=None, help="ignored (OCHEM is a remote service); uniform CLI")
    parser.add_argument("--model-id", type=int, default=MODEL_ID, help=f"OCHEM model id (default {MODEL_ID})")
    parser.add_argument("--cache-dir", type=Path, default=None, help="raw-response cache dir (default $FTO_ADMET_ROOT/cache/ochem_ppb)")
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL_S, help="seconds between polls")
    parser.add_argument("--max-wait", type=float, default=DEFAULT_MAX_WAIT_S, help="give up after this many seconds")
    parser.add_argument("--no-network", action="store_true", help="cache-only; do not call OCHEM (offline)")
    parser.add_argument("--refresh", action="store_true", help="ignore cached entries and re-fetch")
    args = parser.parse_args(argv)

    records, single = parse_inputs(args.input.read_text(encoding="utf-8"))
    outputs = predict_records(
        records,
        model_id=args.model_id,
        cache_dir=args.cache_dir,
        use_network=not args.no_network,
        refresh=args.refresh,
        poll_interval=args.poll_interval,
        max_wait=args.max_wait,
    )
    payload: Any = outputs[0] if (single and len(outputs) == 1) else outputs

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
