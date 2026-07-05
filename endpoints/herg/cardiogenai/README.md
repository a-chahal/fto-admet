# cardiogenai - discriminative cardiac ion-channel pIC50 (hERG / NaV1.5 / CaV1.2), hERG endpoint

CardioGenAI (gregory-kyro/CardioGenAI, Kyro et al. 2024) has **two entry points**. This adapter builds
**one** of them fully and ships the other as a refusing stub (CLAUDE.md §4, docs IO_SPEC §1 #7):

- **Discriminative (BUILT):** a graph + fingerprint + transformer ensemble that predicts a regression
  **pIC50** per cardiac ion channel. Its hERG head can join the hERG gate (t52) as an extra vote.
- **Generative (SCAFFOLD ONLY):** `optimize_cardiotoxic_drug` would emit optimized candidate SMILES. Its
  output is **GATED** on Kunhuan's FTO-binding + FTO-vs-ALKBH5 selectivity, and that cross-arm interface
  **does not exist yet**, so `--mode generative` refuses cleanly and never emits a candidate.

`in_bulk_loop = False` - CardioGenAI is a secondary, not a bulk-loop primary.

## LANDMINE - the two exact gotchas (CLAUDE.md §4, IO_SPEC §1 #7)

1. **The keys contain a literal space.** The discriminative outputs are keyed `"hERG pIC50"`,
   `"NaV1.5 pIC50"`, `"CaV1.2 pIC50"` (verified from `src/Optimization_Framework.py`,
   `input_data_entry[...]`). A key written without the space (`"hERG_pIC50"` / `"hERGpIC50"`) silently
   misses. `endpoint_values` uses these exact space-keyed labels.
2. **pIC50, not P(block).** The regression output is a **pIC50** (higher = stronger blocker = higher
   tox). Mapping pIC50 -> a P(block) probability (threshold pIC50 >= 5.0, or a logistic/calibration) is
   flag **F-1** and lives in the **DEFERRED** hERG gate math (t52). This adapter **emits the raw pIC50 and
   does not convert.** The VERIFIED non-blocker cutoff (pIC50 >= 5.0) is recorded in `raw` only, as a
   context class explicitly marked as the cutoff call, never as a probability.

## Two paths, one CLI

```
python run.py --input <path> --output <path> [--gpu N] [--mode discriminative|generative]
```

- `--mode discriminative` (default): scores the input SMILES and writes the three space-keyed pIC50s.
- `--mode generative`: **refuses** with `GATED: needs Kunhuan binding/selectivity interface (not built)`
  on stderr + a TODO, exits non-zero, and writes no output. It never loads the generative model. Wiring
  it live is blocked until Kunhuan's FTO-binding + FTO-vs-ALKBH5 selectivity filter exists; every
  generated candidate must be filtered through that gate before any is emitted as usable.
- `--gpu N`: pins `CUDA_VISIBLE_DEVICES=N` before torch is imported, then upstream selects `cuda:0` (which
  now maps to card N). Omit `--gpu` to force CPU (the model is small; the smoke runs on CPU). GPU claiming
  is manual (CLAUDE.md §1).

## Discriminative path (how it runs)

`run.py` drives the documented entry point `src.Discriminator.predict_cardiac_ion_channel_activity`
(`prediction_type="regression"`, all three channels). Upstream builds, per call:
- a **bidirectional transformer feature extractor** whose token vocabulary is built by reading the
  `prepared_transformer_data.csv` SMILES column (this is why that 746M CSV is required even for inference);
- the three per-channel **regression** discriminative models (GAT graph net + ECFP2 fingerprint +
  transformer vector).

Each input SMILES is featurized (openbabel/pybel graph, RDKit ECFP2 fingerprint, transformer vector) and a
forward pass yields the pIC50. The Tk-free notebook path is used; the GUI/figure modules in `vendor` are
never imported.

## Output contract (the JSON keys the dispatcher validates)

`run.py` runs in this model's isolated env and cannot import `core`, so it writes plain JSON matching
`core.schemas.OutputRecord`. One input record -> one output object; a JSON array or `.smi` in -> a JSON
array out. Each record:

```json
{
  "model": "cardiogenai",
  "endpoint_values": {
    "hERG pIC50": 4.5019874572753906,
    "NaV1.5 pIC50": 5.562858581542969,
    "CaV1.2 pIC50": 7.368969917297363
  },
  "uncertainty": null,
  "raw": {
    "smiles": "...", "mol_id": "...",
    "hERG pIC50": 4.50, "NaV1.5 pIC50": 5.56, "CaV1.2 pIC50": 7.37,
    "blocker_by_cutoff_pic50_ge_5": { "hERG": false, "NaV1.5": true, "CaV1.2": true },
    "cutoff_note": "cutoff class only (pIC50 >= 5.0); pIC50 -> P(block) is F-1, deferred to t52"
  },
  "provenance": { "model": "cardiogenai", "path": "discriminative", "prediction_type": "regression", "torch_version": "...", "citation": "...", "license": "..." }
}
```

### `endpoint_values` - the three space-keyed pIC50s

| key | channel | type | meaning |
| --- | --- | --- | --- |
| `hERG pIC50` | hERG | float | regression pIC50; higher = stronger blocker = higher tox (feeds the hERG gate as an extra vote) |
| `NaV1.5 pIC50` | NaV1.5 | float | regression pIC50 (context) |
| `CaV1.2 pIC50` | CaV1.2 | float | regression pIC50 (context) |

`uncertainty` is `null`: CardioGenAI discriminative emits no native uncertainty signal. The reserved
envelope stays empty (the AD rule / calibration that would consume it is DEFERRED, CLAUDE.md §4a).

### Deferred boundary (F-1)

The pIC50 -> P(block) mapping is **not** done here. It is flag F-1 and belongs to the DEFERRED hERG gate
math (t52). The `blocker_by_cutoff_pic50_ge_5` field in `raw` is the VERIFIED cutoff class (pIC50 >= 5.0),
provided as context only, and is explicitly **not** a probability.

### Invalid input

An empty / RDKit-unparseable SMILES -> a valid record with all three pIC50s `null`, `uncertainty` null,
and the reason in `raw.error`. The adapter does not crash, so one bad molecule never sinks a bulk batch.

## Environment / install

`pixi.toml` is intent; `pixi.lock` is **solved on the box** (Linux + conda-forge) and committed, carrying a
real `linux-64` section with package hashes. `platforms = [{ platform = "linux-64", cuda = "12" }]` so the
CUDA build of pytorch is pulled (verified: `pytorch-2.1.2-cuda120`, `torch.cuda.is_available() == True`);
macOS cannot resolve the per-model env.

The upstream **code** is vendored unmodified under `vendor/CardioGenAI/src/` (imported as the `src`
package: `Discriminator.py`, `Transformer.py`, `utils.py`, `Optimization_Framework.py`, and the unused
GUI/figure/data-prep modules) + `LICENSE`. The **weights** and the **746M transformer-vocabulary CSV** are
NOT committed (CLAUDE.md §0). On the box, at install time:

```
cd endpoints/herg/cardiogenai
# 1. fetch the upstream weights (discriminative + bidirectional transformer .pt are tracked in the repo)
git clone --depth 1 https://github.com/gregory-kyro/CardioGenAI.git /tmp/cgai_src
cp -r /tmp/cgai_src/model_parameters vendor/CardioGenAI/model_parameters

# 2. download the transformer-vocabulary CSV from the upstream Google Drive link (id below)
mkdir -p vendor/CardioGenAI/data/prepared_transformer_datasets
pixi exec --spec gdown -- gdown 1l2Osk7zFj4rTyrjAi7EJ1GMrsYMbcRHI \
  -O vendor/CardioGenAI/data/prepared_transformer_datasets/prepared_transformer_data.csv
```

Both `vendor/CardioGenAI/model_parameters/` and `vendor/CardioGenAI/data/` are gitignored.

Key deps (all conda-forge, resolved on the box): `python 3.11`, `pytorch 2.1.*` (cuda120 build),
`pytorch_geometric` (the GAT graph net), `openbabel 3.1.1` (`pybel` graph featurizer + bond iteration),
`rdkit` (ECFP2 fingerprints + ADMET descriptors), `pandas` / `scipy` / `scikit-learn` / `numpy`, `h5py`
(imported at the top of `Discriminator.py` for the `.h5` dataset input path), `matplotlib-base` (imported
at the top of `Discriminator.py`), `tqdm`.

## Provenance

- **Upstream:** `github.com/gregory-kyro/CardioGenAI` (Gregory W. Kyro / Batista group). Repo cloned at
  build time; the `src/` code is vendored, the `.pt` weights + transformer CSV are fetched into the env
  (gitignored).
- **Citation:** Kyro GW, Morgan PK, et al. "CardioGenAI: a machine learning-based framework for
  re-engineering drugs to reduce hERG liability while preserving therapeutic activity." *J. Chem. Inf.
  Model.* / *J. Cheminform.* (2024).
- **Access tag:** CODE-PKG.
- **License:** upstream code is **MIT** (Copyright (c) 2024 Gregory W. Kyro; see `vendor/CardioGenAI/LICENSE`).
- **Quirks:** two entry points (only discriminative is built; generative is GATED and refuses); the
  discriminative output keys **contain a literal space**; the regression head emits **pIC50, not P(block)**
  (F-1, deferred); even inference requires the 746M `prepared_transformer_data.csv` (to build the
  transformer token vocabulary); the discriminative weights + bidirectional transformer `.pt` are tracked
  in the upstream GitHub repo, but the transformer CSV is a Google Drive download.

## Smoke

```
pixi run --manifest-path pixi.toml python run.py \
  --input ../../../tests/fixtures/fto43.smi --output /tmp/cardiogenai.out.json
```

yields the three space-keyed pIC50 floats (`hERG pIC50` / `NaV1.5 pIC50` / `CaV1.2 pIC50`) for the FTO-43
fixture; `--mode generative` refuses with the GATED message. `tests/test_model_cardiogenai.py`
(`@pytest.mark.model`) drives both on the box and validates the output against `core.schemas`.
