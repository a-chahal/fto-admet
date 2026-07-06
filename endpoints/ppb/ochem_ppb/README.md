# ochem_ppb - OCHEM plasma-protein-binding via the async REST model web-service (CODE-API)

The **ppb** endpoint's primary model (t36). An **api-model** (CLAUDE.md §5): no upstream package to
install, just a pure-stdlib HTTP client (`urllib`) that submits a molecule to OCHEM's model web-service,
polls the async task to completion, and normalizes the prediction into `core.schemas.OutputRecord`.

## Role: fraction bound (0-1), a ppb modulator (not a gate)

OCHEM's published consensus PPB model returns plasma-protein binding. The common ppb quantity across the
pipeline is **fraction bound (0-1)**, direction UP = more bound / less free (IO_SPEC §2). ppb is a
modulator (it scales free fraction, informs the DMPK picture), not a hard gate; a single tool is
acceptable here (IO_SPEC §1 #18).

## The two literals this task turned on

1. **`MODEL_ID = 1121` - RESOLVED.** The project owner supplied the public OCHEM model id for the
   `ochem.eu/article/29` consensus model: **1121**, "Plasma protein binding_ASNN_[ALogPS, OEstate]"
   (article A29; Han et al., *Eur. J. Pharm. Sci.* 2024, 204:106946; PubMed 39490636). A public model id
   needs no login. `article/29` is the human-readable publication page; `1121` is the numeric id the REST
   `modelId=` parameter wants. This closes the original `needs_aaran` residue on the id.

2. **The REST response field names + a live fixture prediction - STILL OPEN (`needs_aaran`).**
   `TODO(needs_aaran)`: read the exact response envelope from `docs.ochem.eu` and one live
   `getPrediction.do` call, then replace the placeholder key sets in `run.py`
   (`TASK_ID_KEYS` / `STATUS_KEYS` / `PREDICTIONS_KEYS` / `VALUE_KEYS` / `ACCURACY_KEYS` / `DM_KEYS`) and
   the submit/poll URL constants with the verified literals. **These could not be verified in this build:
   OCHEM was unreachable from the build environment** - `ochem.eu:443` failed TLS certificate
   verification and `rest.ochem.eu:443` refused the connection. Per the no-fabricate rule (CLAUDE.md §5)
   the field names are documented **placeholders**, not a claimed-verified header; the parser is written
   tolerantly (JSON first, then XML, then a set of plausible key synonyms) so a wrong guess degrades to
   "prediction not found" (a null record with the raw body cached), never a fabricated number.

## The output transform (LogIt -> % bound -> fraction) - do not mis-implement

The ASNN consensus model (id 1121) predicts PPB in **LogIt (logit) units, NOT a raw percentage**
(project-owner directive). The adapter converts:

```
pct_bound      = 100 / (1 + exp(-logit))          # inverse logit -> % bound
fraction_bound = pct_bound / 100 = sigmoid(logit) # 0-1, the ppb aggregator's common quantity
```

Treating the raw prediction as a percent (or a fraction) directly is **wrong**. `endpoint_values` carries
both `fraction_bound` (0-1, primary) and `ppb_percent_bound` (%, readability); both are UP = more bound.
The transform is unit-tested in `tests/test_model_ochem_ppb.py` (logit 0 -> 50%, ln 9 -> 90%, etc.).

## Native uncertainty (ASNN DM + accuracy)

ASNN emits a native prediction confidence / **distance-to-model (DM)** - one of the few models in the set
with a real native uncertainty (CLAUDE.md §3). It is routed into the reserved `uncertainty` envelope:
`uncertainty.extra.distance_to_model` and `uncertainty.extra.accuracy_error_logit`. DM is a distance
(unbounded), not a 0-1 index, and the accuracy/error estimate is in **logit** units (same space as the
raw prediction), so neither is forced into `ad_index` / `ad_in_domain`: the operational AD *rule* that
would turn a DM into an in/out-of-domain call is **DEFERRED** (F-7 / CLAUDE.md §4a). We reserve the
fields and record the native signals; we do not decide the threshold.

## Input: desalted neutral parent (F-16 divergence, FLAGGED)

OCHEM curated its PPB training set on the **desalted neutral parent** (salts / water stripped), so the
model expects a desalted neutral molecule. This diverges from the pipeline's single canonical input under
the **DEFERRED F-16** standardization decision (the FTO di-cation protonation/tautomer/desalting is not
yet decided; CLAUDE.md §4a). The adapter **flags** the divergence (this README +
`provenance.input_expectation = "desalted neutral parent (F-16 divergence; ...)"`) and feeds the
canonical input as-is. It does **not** silently pick a protonation/desalting state per model.

## REST protocol (async submit -> poll)

```
submit:  GET https://ochem.eu/modelservice/getPrediction.do?modelId=1121&mol=<MOLECULE>  -> task id
poll:    GET https://ochem.eu/modelservice/getPrediction.do?taskId=<id>   (every 5-10 s) -> ready + value
```

Batching is via the SDF record separator **`$$$$`** (IO_SPEC §1 #18.A): several molecules concatenate
into one `mol` payload and the returned predictions align **positionally** to the input order.
`rest.ochem.eu/predict` is the documented alternate host (kept as `ALT_ENDPOINT`).
`TODO(needs_aaran)`: confirm the exact submit/poll URL shape (single endpoint for both, vs a separate
fetch URL) on a reachable network.

Infra (CLAUDE.md §4a; the api-model gate):
- **retry with exponential backoff** on transport errors (`_request_with_retry`),
- **raw-response cache** on disk (`$FTO_ADMET_ROOT/cache/ochem_ppb/`, on /zfs; repo-local `.cache/`
  fallback off-box) - a result stays reconstructible after upstream silently changes, and a cache hit
  skips the network entirely,
- one bad / missing molecule -> a null record with the reason in `raw`, never a crash.

## Output contract (the JSON keys the dispatcher validates)

One input record -> one output object; a JSON array or `.smi` in -> a JSON array out. Each record:

```json
{
  "model": "ochem_ppb",
  "endpoint_values": { "fraction_bound": 0.90, "ppb_percent_bound": 90.0 },
  "uncertainty": {
    "extra": { "distance_to_model": 0.4, "accuracy_error_logit": 0.25, "note": "ASNN native DM + accuracy; AD threshold policy DEFERRED (F-7/CLAUDE.md §4a)" }
  },
  "raw": { "smiles": "...", "mol_id": "...", "logit": 2.197, "prediction": {...}, "transform": "pct = 100/(1+exp(-logit)); fraction = pct/100" },
  "provenance": { "model": "ochem_ppb", "model_id": 1121, "model_page": "https://ochem.eu/article/29", "citation": "...", "access_tag": "CODE-API", "input_expectation": "desalted neutral parent (F-16 divergence; ...)" }
}
```

| key | quantity | unit | direction |
| --- | --- | --- | --- |
| `fraction_bound` | plasma-protein binding | 0-1 (fraction) | **UP = more bound** (less free) - the ppb common quantity |
| `ppb_percent_bound` | plasma-protein binding | % | UP = more bound (readability companion) |

## Uniform CLI

```
python run.py --input <path> --output <path> [--gpu N]
  [--model-id 1121] [--cache-dir <dir>] [--poll-interval 7] [--max-wait 600] [--no-network] [--refresh]
```

`--gpu` is accepted and **ignored** (OCHEM is a remote service); it exists only so the dispatcher can
build one command for every model. `--no-network` serves cache-only (offline); `--refresh` ignores cached
entries and re-fetches.

## Environment / lock

This is an **api-model**: `run.py` is pure stdlib (`urllib`, `json`, `math`, `hashlib`), so it runs in
the **core env** directly and needs no upstream package. The api-model milestone (CLAUDE.md §5) is an HTTP
client + retry/backoff + cache + placeholder modelId + a **mocked** unit test - **not** an on-box smoke or
a box-solved lock. A per-model pixi env is therefore intentionally **not** shipped here; if this model is
ever promoted into the bulk `pixi run` dispatch loop, a trivial python-only env can be solved on the box
at that point.

## Provenance

- **Upstream:** OCHEM public model web-service (Tetko group), model `ochem.eu/article/29`, numeric
  `modelId = 1121` ("Plasma protein binding_ASNN_[ALogPS, OEstate]"). No local install (REST only).
- **Citation:** Han R, et al. "Consensus modeling of plasma protein binding." *Eur. J. Pharm. Sci.*
  2024, 204:106946. PubMed 39490636. (Consensus PPB model, R^2 ~= 0.90/0.91.)
- **Access tag:** CODE-API (async REST + poll).
- **License:** OCHEM public model web-service terms (`ochem.eu`); results transcribed like a web tool.
- **Quirks:**
  - prediction is in **LogIt units**, converted to % then fraction (see the transform above) - the single
    most important non-obvious fact about this model;
  - expects a **desalted neutral parent** input (F-16 divergence, flagged);
  - async: submit returns a **task id**, poll every 5-10 s; batch via **`$$$$`**;
  - native **DM + accuracy** uncertainty (routed to `uncertainty.extra`; AD rule DEFERRED);
  - the exact **response field names** are placeholders pending one live call (`needs_aaran`).

## Smoke / test

`tests/test_model_ochem_ppb.py` is a **mocked** unit test (fast tier, no network, no box): it
monkeypatches the single network primitive (`run._transport`) to drive submit -> pending -> ready and
pins the poll loop, the LogIt -> % -> fraction transform, retry/backoff recovery, `$$$$` batch positional
alignment, the raw-response cache (hit skips the network), and validation against
`core.schemas.OutputRecord`. A **live** smoke (a real % bound for a real molecule) is the `needs_aaran`
residue: it needs OCHEM reachable (it was not, from the build environment) to verify the response field
names and record an actual prediction.
