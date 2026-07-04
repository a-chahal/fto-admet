# t35-model-admetlab3 - ADMETlab 3.0 (API adapter; live header = NEEDS_AARAN)

**Kind:** model-api · **Autonomy:** human · **Runs:** author laptop; live call needs an authenticated/live session
**Touch only:** `endpoints/triage/admetlab3/**`, `tests/test_model_admetlab3.py`
**Deps:** t12-gate-phase1 · **Template:** API adapter (transport + cache + placeholder schema)

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §1 #2 (ADMETlab transport - VERIFIED) + §3 F-6.
- `CLAUDE.md` §4 (ADMETlab landmine), §4a (raw-output caching is in scope now).

## Build (transport is fully known; only the literal column names are the residue)
- Base `https://admetlab3.scbdd.com`. Flow (VERIFIED from `ToxMCP/admetlab-mcp`):
  1. (optional) wash: `POST /api/washmol` body `{"SMILES":[...]}`.
  2. predict: `POST /api/admet` (fallback `POST /api/single/admet`) body
     `{"SMILES":[...], "feature": <bool>, "uncertain": <bool>}` → returns a **`taskId`** (async).
     Set `uncertain=true` to get the per-endpoint uncertainty.
  3. fetch: `POST /api/admetCSV` body `{"taskId": <id>}` → CSV (one molecule per row). Optional `X-API-KEY`.
- Constraints: **≤1000 SMILES/request, ≤5 rps.** Async + reportedly unstable → **retry/backoff + fallback
  endpoints + response caching** (cache raw CSV to `/zfs` per `CLAUDE.md` §4a). Env prefix `ADMETLAB_`.
- **Uncertainty** = per-endpoint **Youden-index high/low-confidence flag** (binary), not a continuous σ →
  map into `uncertainty` as a confidence flag, do not assume a calibrated variance.
- **Placeholder schema:** the **literal 119 CSV column names require one live `/api/admetCSV` call**
  (F-6) - cannot be obtained without hitting the service. Build the schema with the **known heads**
  (hERG; organ-tox: nephro/neuro/oto/hemato/genotox, RPMI-8226 immuno, A549/HEK293 cyto; plus the documented
  categories) and a `# TODO: capture full 119-column header from one live /api/admetCSV call`. Do **not**
  fabricate column names.
- Cross-cutting `endpoints = {triage, herg, metabolism, distribution, ppb, toxicity, permeability}`.

## Landmines
- **No fabricated columns.** Unknown literal names stay TODO; status ends `needs_aaran`.
- Standardize upstream even though server-side wash exists (reproducibility).

## Done (gate: model-api - client + retry + cache + placeholder schema + mocked test; status=needs_aaran)
- `run.py` implements the wash→predict→admetCSV flow with retry/backoff + caching; a **mocked** unit test
  covers the async taskId→CSV round-trip (no live call). README carries the F-6 TODO.
- `.result.json` status = `needs_aaran` (the one live `/api/admetCSV` header capture is the only residue).

## Blocked if
- The transport contract itself proves wrong when someone runs the live call → BLOCK with the discrepancy.
  (Not obtaining the header from here is expected - that's `needs_aaran`, not blocked.)
