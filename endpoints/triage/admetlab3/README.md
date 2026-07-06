# admetlab3 - ADMETlab 3.0 web-API adapter (triage home; cross-cutting)

A CODE-API adapter: ADMETlab 3.0 is a **remote web service**, not a local package, so this adapter is an
HTTP client over `https://admetlab3.scbdd.com`. It lives under `triage/`, but its registry `endpoints`
set spans **seven** endpoints - triage, herg, metabolism, distribution, ppb, toxicity, permeability - so a
single run feeds seven aggregators (model -> endpoint is a graph; aggregators query by endpoint, never by
folder: CLAUDE.md §2).

Access tag: **CODE-API**. Upstream service: SCBDD, `admetlab3.scbdd.com`. Reference wrapper (transport
source, not authority): `github.com/ToxMCP/admetlab-mcp` (`client/admet_client.py`, `settings.py`).
Citation: Fu L, et al. *ADMETlab 3.0*, Nucleic Acids Res 52(W1):W422 (2024), doi:10.1093/nar/gkae236.
Architecture: **DMPNN-Des** (multi-task DMPNN + RDKit 2D descriptors). License: academic use per site terms.

## Uniform CLI

```
pixi run --manifest-path endpoints/triage/admetlab3/pixi.toml python run.py \
    --input <path> --output <path> [--gpu N]
```

`--gpu` is accepted for uniform-CLI compatibility and **ignored** (remote service, `requires_gpu=False`).
The env is stdlib-only (`urllib`/`csv`/`json`); there is no third-party HTTP dependency, so **no
box-solved lockfile is required** for this api-model kind (CLAUDE.md §5).

## Transport (VERIFIED 2 Jul 2026 from ToxMCP/admetlab-mcp; IO_SPEC §1 #2, F-6)

1. (optional) **wash**: `POST /api/washmol` body `{"SMILES": [...]}` -> standardized SMILES.
2. **predict (async)**: `POST /api/admet` (fallback `POST /api/single/admet`) body
   `{"SMILES": [...], "feature": <bool>, "uncertain": <bool>}` -> JSON containing a **`taskId`**.
3. **fetch**: `POST /api/admetCSV` body `{"taskId": <id>}` -> CSV, one molecule per row.
   Optional header `X-API-KEY`.

Constraints: **<=1000 SMILES/request, <=5 rps.** The service is async and reportedly unstable, so the
client wraps every call in **retry + exponential backoff**, uses the documented **fallback** predict path,
throttles to <=5 rps, and **caches the raw CSV + the raw predict JSON** to disk keyed by `taskId`
(raw-output caching is IN SCOPE now, CLAUDE.md §4a). Rows are aligned to inputs **positionally**.

## Uncertainty (VERIFIED)

For classification heads, ADMETlab 3.0 converts its raw uncertainty score into a **per-endpoint
high/low-confidence flag** using that endpoint's max-Youden threshold. Requested with `uncertain=true`
(default on). It is a **binary confidence flag per endpoint, NOT a calibrated sigma**, so it is routed
into the reserved `Uncertainty.extra` envelope as a flag, never assumed to be a variance (schema §3). The
per-column flag map is materialized once the live 119-column header is captured (see F-6 TODO below).

## Configuration (env, prefix `ADMETLAB_`)

| var | default | meaning |
| --- | --- | --- |
| `ADMETLAB_BASE_URL` | `https://admetlab3.scbdd.com` | service base URL |
| `ADMETLAB_API_KEY` | (unset) | optional `X-API-KEY` header |
| `ADMETLAB_CACHE_DIR` | `$FTO_ADMET_ROOT/cache/admetlab3` | raw-response cache (should sit on `/zfs`) |
| `ADMETLAB_TIMEOUT` | `60` | per-request timeout (s) |
| `ADMETLAB_MAX_RETRIES` | `4` | retry budget per call |
| `ADMETLAB_BACKOFF` | `1.5` | exponential backoff base (s) |
| `ADMETLAB_RPS` | `5` | request rate cap (hard-capped at 5) |
| `ADMETLAB_FEATURE` | `0` | request the physchem feature block |
| `ADMETLAB_UNCERTAIN` | `1` | request the Youden confidence flags |
| `ADMETLAB_WASH` | `0` | server-side wash; OFF so core standardizes upstream (F-16) |

## F-16 (input standardization) - DEFERRED

The adapter feeds ADMETlab the single canonical SMILES `core` hands it, **unmodified**. Server-side
`/api/washmol` exists but is **off by default** so the pipeline's own upstream standardization stays the
single source of truth (reproducibility; task landmine). No wash/protonation state is silently chosen here.

## Placeholder schema and the F-6 residue (NEEDS_AARAN)

The `/api/admetCSV` response carries **119 endpoints**, each with a predicted value/probability, a
decision-state category, an uncertainty score, and alert highlights. The request/transport contract is
verified, but the **literal column names are only knowable from one live `/api/admetCSV` call** (the
reference wrapper passes the CSV through without enumerating them). Per the no-fabricate rule (CLAUDE.md
§5), we do **not** invent them:

- `run.py` parses the header **generically** - whatever columns the live CSV returns become
  `endpoint_values` (numeric cells coerced to float, others kept as strings), mirrored verbatim in
  `raw.columns`, with the raw header in `raw.header`.
- `schema.py` records only the **documented** head families (hERG; organ-tox nephro/neuro/oto/hemato/
  genotox, RPMI-8226 immuno, A549/HEK293 cyto; the eight ADMET categories) and leaves `KNOWN_COLUMNS`
  empty.

**TODO (F-6):** capture the full literal 119-column header from ONE live `/api/admetCSV` call, freeze it
in `schema.py::KNOWN_COLUMNS`, and wire the per-endpoint direction/units + the confidence-flag column map
into the aggregators.

**Live-call status for this task:** the one live header-capture call could not be made from the headless
build session (outbound network is denied by the sandbox, both from the laptop and via the box), which is
the documented expected outcome for this task. The transport, retry/backoff, cache, positional alignment,
and generic parse are all built and covered by mocked unit tests (`tests/test_model_admetlab3.py`). Status
is therefore **`needs_aaran`**: the sole remaining step is that one authenticated/live `/api/admetCSV`
call to freeze the 119-column header.
