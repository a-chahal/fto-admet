# t22-model-openadmet - OpenADMET (CYP reference; native σ)

**Kind:** model-code · **Autonomy:** review · **Runs:** author laptop; env + smoke on box
**Touch only:** `endpoints/triage/openadmet/**`, `tests/test_model_openadmet.py`
**Deps:** t12-gate-phase1 · **Template:** follow t11

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §1 #3 (OpenADMET - VERIFIED output scheme + S3 weights).
- `docs/FTO_ADMET_Model_Provenance_VERIFIED.md` §B#3.

## Build
- Framework, not turnkey. Run the released baselines for inference: **CYP3A4, CYP2J2**, and the multitask
  **CYP1A2/2D6/2C9/PXR/AhR** model. Repo `OpenADMET/openadmet-models`; `pixi install` on box; commit lock.
- **Weights are pulled from S3** (`_download_s3_dir` in `comparison/posthoc.py`) - not HuggingFace, not
  retrain-only. Ensure the S3 fetch works from the box (cache under `/zfs`).
- Output (VERIFIED): the inference appends `OADMET_PRED_{tag}_{task}` (prediction; classification via
  `predict_proba` → probability) and **`OADMET_STD_{tag}_{task}`** (per-prediction **σ → native uncertainty,
  DIRECT**). Map PRED → `endpoint_values`, and **populate `uncertainty` from the STD columns** (this is one
  of the few models shipping a real per-prediction σ - use it).
- `endpoints = {triage}`; role = **CYP-metabolism reference, NOT fed to gates** (cluster-split R²≈0.1).

## Landmines
- **Reference, not authority** - do not let OpenADMET feed a gate; it's a CYP cross-check. State in README.
- Weights from **S3** (correct the earlier HF assumption); confirm the download path + cache location.

## Done (gate: model kind - box-solved lock + smoke ok)
- Box smoke on FTO-43 returns `OADMET_PRED_*` values + `OADMET_STD_*` σ; `uncertainty` is populated from STD.
- README: reference-only role, S3 weights, native-σ note. Access CODE-PKG.

## Blocked if
- S3 weights unreachable from box, or the env won't resolve, after 3 attempts → BLOCK with the error.
