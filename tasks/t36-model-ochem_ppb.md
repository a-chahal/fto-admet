# t36-model-ochem_ppb - OCHEM PPB (API adapter; live modelId = NEEDS_AARAN)

**Kind:** model-api · **Autonomy:** human · **Runs:** author laptop; modelId lookup needs an authenticated session
**Touch only:** `endpoints/ppb/ochem_ppb/**`, `endpoints/ppb/__init__.py`, `tests/test_model_ochem_ppb.py`
**Deps:** t12-gate-phase1 · **Template:** API adapter (async REST + cache + placeholder modelId)

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §1 #18 (OCHEM PPB) + §3 F-7.
- `docs/FTO_ADMET_Model_Provenance_VERIFIED.md` §E.1/§E.8 (REST confirmed; modelId manual).

## Build
- Async REST: `https://ochem.eu/modelservice/getPrediction.do?modelId=<ID>&mol=<MOLECULE>` → returns a task
  id → **poll every 5-10 s** until ready (also `rest.ochem.eu/predict`). Batch via the **`$$$$`** SDF separator.
  Wrap with **retry/backoff + response caching** (raw responses to `/zfs`, `CLAUDE.md` §4a).
- **Model to pin:** `ochem.eu/article/29` = the Han et al. 2025 consensus PPB model (R² 0.90/0.91). The
  **numeric `modelId` is a live authenticated OCHEM-UI lookup** (login/navigation; not scrapable) → this is
  the `needs_aaran` residue. Use a **placeholder `MODEL_ID` constant** + a
  `# TODO: set OCHEM modelId from the ochem.eu/article/29 model-service page`.
- **Output = % bound** (VERIFIED from the training data curation) → normalize to **fraction bound (÷100)** for
  the schema; direction ↑ = more bound (less free). OCHEM also returns an **accuracy/error estimate + an
  applicability-domain distance** → map into `uncertainty` (confidence + ad_index). Confirm exact JSON field
  names from `docs.ochem.eu` at build time; if unread, keep them as documented placeholders (no fabrication).
- **Input = desalted neutral parent** (OCHEM curation stripped salts/water) - note this against the deferred
  F-16 standardization decision.
- `endpoints = {ppb}`; not a gate; single tool acceptable.

## Landmines
- **modelId is live-only** - placeholder + TODO; status `needs_aaran`. Do not guess a numeric id.
- Output is **% → normalize to fraction**; OCHEM expects **desalted neutral** input (F-16 note).

## Done (gate: model-api - async client + poll + retry + cache + placeholder modelId + mocked test; status=needs_aaran)
- `run.py` implements submit→poll→result with `$$$$` batching, retry/backoff, caching; `%`→fraction
  normalization; accuracy/AD → `uncertainty`. Mocked unit test covers the poll loop. README carries the
  modelId TODO + the desalted-input + %-bound notes.
- `.result.json` status = `needs_aaran` (modelId lookup is the only residue).

## Blocked if
- The REST mechanism proves wrong on a live run → BLOCK with the discrepancy. (Missing modelId ⇒ `needs_aaran`.)
