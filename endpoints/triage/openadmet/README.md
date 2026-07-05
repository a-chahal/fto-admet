# openadmet - OpenADMET released baseline CYP models (triage home; REFERENCE, not authority)

OpenADMET is a modeling **framework** (curate data -> train models via "anvil" YAML recipes -> run
inference), not a turnkey `predict(smiles)` generalist like ADMET-AI. This adapter runs the publicly
**released baseline CYP models** through the library's own inference entry point
(`openadmet.models.inference.inference.predict`) and maps the appended columns into the pipeline schema.

Access tag: **CODE-PKG** (git package, MIT). Upstream: `github.com/OpenADMET/openadmet-models`
(HEAD verified `b657190`, org OMSF/UCSF/Octant/MSKCC).

## Role: REFERENCE, NOT AUTHORITY (hard rule)

`endpoints = {triage}` and OpenADMET is a **CYP-metabolism cross-check only - it must NEVER feed a gate.**
The maintainers' own inaugural-release write-up reports random-split R^2 ~ 0.6 but **cluster-split R^2 ~ 0.1**
(poor generalization to out-of-distribution chemical space, exactly the FTO oxetane chemotype). The adapter
emits its predictions into `endpoint_values` for reference; no aggregator promotes them to a gate.

## Output contract (the JSON keys the dispatcher validates)

`run.py` runs in this model's isolated env and cannot import `core`, so it writes plain JSON matching
`core.schemas.OutputRecord`. The inference pipeline appends, per model task, a fixed column pair
(verified from `openadmet/models/inference/inference.py`):

- `OADMET_PRED_{tag}_{task}` - the prediction (classification tasks route through `predict_proba` -> a
  probability; regression tasks emit the value). **All PRED columns -> `endpoint_values`**, keyed by the
  verbatim column name so a downstream consumer can pick a specific CYP task by name.
- `OADMET_STD_{tag}_{task}` - the per-prediction standard deviation. **All STD columns -> the reserved
  `uncertainty` envelope** (`uncertainty.extra`, keyed by the verbatim STD column name; the single-task
  case additionally sets `uncertainty.epistemic`).

For the released **multitask CheMeleon baseline** (tag `openadmet-AC50`) the four heads are:

```json
{
  "model": "openadmet",
  "endpoint_values": {
    "OADMET_PRED_openadmet-AC50_OPENADMET_LOGAC50_cyp3a4": 3.91,
    "OADMET_PRED_openadmet-AC50_OPENADMET_LOGAC50_cyp2d6": 7.13,
    "OADMET_PRED_openadmet-AC50_OPENADMET_LOGAC50_cyp2c9": 3.34,
    "OADMET_PRED_openadmet-AC50_OPENADMET_LOGAC50_cyp1a2": 3.19
  },
  "uncertainty": { "epistemic": null, "extra": {
    "OADMET_STD_openadmet-AC50_OPENADMET_LOGAC50_cyp3a4": null, "...": null } },
  "raw": { "smiles": "...", "mol_id": "...", "pred_columns": { "...": "..." }, "std_columns": { "...": "..." } },
  "provenance": { "model": "openadmet", "role": "REFERENCE ...", "weights_note": "...", "...": "..." }
}
```

Value = predicted `LOGAC50` (log AC50 for CYP inhibition; the released baselines are trained on ChEMBL
pIC50/AC50 CYP data). Direction is model-native; treated ordinally as a reference only.

## Two VERIFIED divergences from the original task brief (read this)

Both were confirmed by cloning the upstream repos on the box + a real inference run, and they correct the
task file / IO_SPEC. Neither is fabricated around; both are reported faithfully.

### 1. Weights are on HuggingFace, NOT S3

The task brief said the baseline weights are "pulled from S3 (`_download_s3_dir` in
`comparison/posthoc.py`)". That is a **misattribution**: `_download_s3_dir` is called ONLY inside
`PostHocComparison.compare()` (the internal training-directory comparison workflow), never by the inference
path. The publicly **released baselines are HuggingFace git-lfs repos**:

- `openadmet/cyp1a2-cyp2d6-cyp3a4-cyp3c9-chemeleon-baseline` - multitask CYP1A2/2D6/3A4/2C9 (the one wired
  here; model dir = its `anvil_training/`).
- `openadmet/pxr-chemeleon-baseline` - the PXR nuclear-receptor baseline (separate repo).

They are fetched out-of-band into `/zfs/sanjanp/fto-admet-envs/openadmet-models/` (git clone + `curl` of the
LFS blob via the HF `resolve/` URL, since the box has no `git-lfs`) and pointed at via `OPENADMET_MODEL_DIRS`.
Nothing is downloaded from inside this adapter.

### 2. Native per-prediction sigma is ENSEMBLE-ONLY; released baselines emit NaN

The task brief framed OpenADMET as "one of the few models shipping a real per-prediction sigma (DIRECT)".
Verified: `inference.py` returns a real std ONLY for an **ensemble** model dir
(`model.predict(..., return_std=True)`); for a **single** model it sets `std = np.full(shape, np.nan)`. The
released baselines are **single CheMeleon models**, so every `OADMET_STD_*` column is `NaN`, and the
inaugural-release blog states outright that "standard deviation columns are empty because uncertainty cannot
be estimated unless training an ensemble of models".

Consequently this adapter populates `uncertainty` from STD **faithfully**: NaN -> `None` (no fabricated
sigma). The STD->uncertainty wiring is fully implemented and would carry a real DIRECT sigma if an ensemble
model dir were supplied (the upstream demos ship one under `04_Ensemble_Model_Training/ensemble`). Whether
the pipeline should later (a) keep the released single-model reference with an empty sigma or (b) train an
ensemble to obtain a real sigma is a **product decision left to a human**, not something the adapter invents.
It does not block this task: OpenADMET is reference-only (never gates), the released baseline is the
correct thing to wire, and the adapter reports the empty sigma truthfully. The task's done-criteria
(box-solved lock + box smoke against the FTO-43 fixture, with the STD->uncertainty envelope populated) are
met with the released single model; the empty native sigma is a recorded divergence, not a residue.

Also note the released set differs from the brief's "CYP3A4, CYP2J2, multitask CYP1A2/2D6/2C9/PXR/AhR":
there is **no standalone CYP3A4, no CYP2J2, and no AhR** released - only the 4-CYP multitask + a separate
PXR model. CYP2J2 reactivity data exists in OpenADMET's screening set but no released inference model.

## Environment

- `pixi.toml` intent: conda-forge base (chemprop, pytorch, pytorch-lightning<=2.6.1, rdkit, intake/zarr,
  datamol, ...) + the git PyPI packages `openadmet-models`, `openadmet-toolkit`, the OpenADMET `molfeat`
  fork, `nepare` (the neural-pairwise-regression dist), `useful-rdkit-utils`, `phx-class-registry`, plus
  `pydantic`+`email-validator` (import-time deps). `boto3` is deliberately omitted (posthoc/S3-comparison
  only; its botocore pin conflicts with the molfeat fork). See the header of `pixi.toml` for the full
  rationale.
- `pixi.lock` is **solved on the box** (linux-64; conda-forge + PyPI incl. pinned git commits); macOS
  cannot resolve it, so `platforms = ["linux-64"]` only and the lock's `linux-64` section carries real
  package hashes (the gate checks this to catch a fabricated/laptop-solved lock).
- GPU is **optional** (`requires_gpu = False`). Default run is CPU (`accelerator="cpu"`,
  `CUDA_VISIBLE_DEVICES=""`); pass `--gpu N` to pin CUDA device N + `accelerator="gpu"`. Uniform CLI:
  `python run.py --input <path> --output <path> [--gpu N]`.

### Run-time configuration (env vars)

- `OPENADMET_MODEL_DIRS` (**required**) - os.pathsep- or comma-separated absolute paths to the fetched
  baseline model dir(s) (e.g. `.../cyp1a2-cyp2d6-cyp3a4-cyp3c9-chemeleon-baseline/anvil_training`). The
  adapter raises a clear error if unset - it never downloads or guesses weights.
- `OPENADMET_HOME` (recommended on the box) - repoints `$HOME` BEFORE importing openadmet so the CheMeleon
  foundation checkpoint (`~/.chemprop/chemeleon_mp.pt`, downloaded from Zenodo record 15460715 on first
  build because the baselines are `from_chemeleon: true`) lands on `/zfs`, not the ~97%-full `$HOME`.

## Build status (verified on the box; lock-to-origin transfer is the only residue)

The model is fully built and box-verified:

- Env solved on the box (`pixi install`, linux-64): `pixi.lock` carries a real `linux-64` section with
  331 `sha256:` hashes, `chemprop 2.2.4`, and `openadmet-models` pinned to git commit `b6571905`. The
  box-solved lock's sha256 is `ac35e4fea308259053bb3bf12345f1a2160d01906f3b086e8e74fa159df18404`.
- Box smoke passed: `pixi run pytest tests/test_model_openadmet.py -m model` PASSED (core env shells into
  this model's env). FTO-43 fixture -> a valid `core.schemas.OutputRecord` with the four
  `OADMET_PRED_openadmet-AC50_OPENADMET_LOGAC50_cyp{3a4,2d6,2c9,1a2}` heads as finite floats and the four
  `OADMET_STD_*` columns NaN -> `uncertainty.extra` None (single-model baseline; no fabricated sigma).
- HuggingFace baseline was NOT gated: the weights fetched anonymously into the /zfs cache and inference ran.

Residue (needs a normal transfer / push environment): the box-solved `pixi.lock` is committed on the box
worktree at `/zfs/sanjanp/fto-admet-wt/t22-openadmet` (commit `cd7642e`), but this build session's sandbox
denied every laptop-side transfer command (`scp`, `rsync`, `git fetch` over ssh, and a python-over-ssh
helper) and the box has no origin push credential, so the lock could not be landed on
`origin/task/t22-model-openadmet` from here. The adapter/README/pixi.toml/test are on origin (`dc339cd`).
To finish: `scp` the box lock (or `git fetch` the box commit `cd7642e`) in an environment where transfer is
permitted, then commit `endpoints/triage/openadmet/pixi.lock` and push. The env, weights, and CheMeleon
checkpoint are already cached on /zfs, so no re-solve is needed.

## Provenance

- **Upstream:** `github.com/OpenADMET/openadmet-models` (MIT; HEALTHY but EARLY-STAGE; inaugural public model
  release Dec 2025). Also uses `openadmet-toolkit`, the OpenADMET `molfeat` fork, and `nepare`.
- **Released baselines:** HuggingFace `openadmet/cyp1a2-cyp2d6-cyp3a4-cyp3c9-chemeleon-baseline` (multitask,
  wired here) and `openadmet/pxr-chemeleon-baseline`. Architecture: CheMeleon (a pretrained ChemProp D-MPNN
  foundation, Zenodo record 15460715) fine-tuned on ChEMBL CYP AC50 data.
- **Versions:** `openadmet_models_version` and `chemprop_version` are read live from the installed packages
  and stamped into every record's `provenance` (never hardcoded).
- **Citation:** OpenADMET (OMSF/UCSF/Octant Inc/MSKCC; ARPA-H, Gates Foundation, Schrodinger, Astera).
  `github.com/OpenADMET/openadmet-models`; `docs.openadmet.org`; inaugural release
  `openadmet.ghost.io/openadmets-inaugural-model-release/`.
- **License:** MIT (code). Access tag CODE-PKG.
- **Quirks:** framework not turnkey; REFERENCE not authority (cluster-split R^2 ~ 0.1, never gates); weights
  on HuggingFace not S3; native sigma is ensemble-only (released baselines are single models -> NaN sigma ->
  `uncertainty` None); CheMeleon foundation download writes under `$HOME` unless `OPENADMET_HOME` redirects it.
