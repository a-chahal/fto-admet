# ctoxpred2 - cardiac ion-channel toxicity (hERG / NaV1.5 / CaV1.2), hERG endpoint

CToxPred2 (issararab/CToxPred2, JCIM 2023/2024) is an automatable **multichannel secondary** model for
cardiotoxicity on three targets. It is the substitute for the web-only **CardioDPi** (CLAUDE.md §4). Its
**hERG** channel feeds the hERG gate (t52); **NaV1.5** and **CaV1.2** are context.

## Role: secondary, a VOTE (not a probability)

`in_bulk_loop = False` - CToxPred2 is a secondary, not a bulk-loop primary. Each channel emits a **binary
0/1 blocker VOTE** (1 = blocker) plus a **confidence**. The hERG gate consumes the hERG channel as a
**confidence-weighted VOTE**, NOT as a P(block) probability averaged into the hERG probability pool
(CLAUDE.md §4, docs IO_SPEC §2). The gate math itself (thresholds/weights) is DEFERRED to t52; this
adapter only emits the raw per-model signal.

## LANDMINE - the two exact parsing gotchas (CLAUDE.md §4, IO_SPEC §1 #6)

1. **0/1 vote, not a probability.** Each channel call is a binary `int` via `argmax` over the 2-class
   softmax (1 = blocker), NOT a continuous probability. Do **not** coerce it into the P(block) pool.
2. **Confidence is a percent STRING.** Upstream writes each confidence as `"{:.1%}"` (e.g. `"87.3%"`).
   The adapter reproduces that export string verbatim in `raw`, then **parses it** (strip `%`, divide by
   100) into a float in `[0, 1]`. The parsed value carries the export's 1-decimal-percent precision (that
   string is the shipped contract); the winning-class mean softmax is also the source, kept in provenance.

## Model choice: DNN (MC-dropout), not RF

CToxPred2 ships two model families (a GUI/setting toggle upstream):
- **DNN** - supervised MLPs with **MC-dropout** at inference (dropout left ON, 100 stochastic forward
  passes, averaged): the confidence is the winning class's mean softmax probability.
- **RF** - semi-supervised random forests; confidence via ensemble spread.

**This adapter ships the DNN (`variant = dl-sl`).** Reasons: (a) MC-dropout is a genuine Bayesian-style
uncertainty that maps cleanly onto the reserved `uncertainty` envelope (CLAUDE.md §3); (b) the DNN's
torch state-dicts load robustly across versions, whereas the RF's `joblib` pickles are scikit-learn
version-pinned and brittle; (c) verified end-to-end on the box. The RF weights ship in the same repo
(`vendor/CToxPred2/models/random_forest`) as an alternate path but are **not wired** here.

The DNN vote is deterministic in this adapter: a fixed `torch.manual_seed` is set before the MC-dropout
passes so the vote/confidence are reproducible for the ledger (the stochasticity is over dropout masks).

## Headless path

The upstream repo ships a Tk GUI (`app.py`) - **not used**. Prediction is driven through the notebook's
underlying DNN function (`notebooks/nutils.py::_generate_predictions_sl`), adapted into `run.py`, which
imports the vendored inner package's flat modules (`utils`, `pairwise_correlation`, `hERG_model`,
`nav15_model`, `cav12_model`). `matplotlib` / `matplotlib_venn` / `Draw` / `MolVS` (GUI + 2D-image +
standardization) and the GCN path (`architecture_framework.py`, torch-geometric) are **not** on the
prediction path and are excluded from the env.

`CorrelationThreshold` (the custom transformer inside the descriptor-preprocessing pipelines) is imported
by `run.py` so the `joblib` `.sav` pipelines unpickle: they were pickled with that class in `__main__`,
and `run.py` is `__main__` (exactly as the upstream notebook is).

## Output contract (the JSON keys the dispatcher validates)

`run.py` runs in this model's isolated env and cannot import `core`, so it writes plain JSON matching
`core.schemas.OutputRecord`. One input record -> one output object; a JSON array or `.smi` in -> a JSON
array out. Each record:

```json
{
  "model": "ctoxpred2",
  "endpoint_values": { "hERG_vote": 0, "NaV1.5_vote": 0, "CaV1.2_vote": 1 },
  "uncertainty": {
    "confidence": 0.998,
    "extra": {
      "nav15_confidence": 1.0, "cav12_confidence": 0.977,
      "hERG_confidence_pct": "99.8%", "nav15_confidence_pct": "100.0%", "cav12_confidence_pct": "97.7%"
    }
  },
  "raw": {
    "smiles": "...", "mol_id": "...",
    "hERG": 0, "hERG_confidence": "99.8%",
    "Nav1.5": 0, "Nav1.5_confidence": "100.0%",
    "Cav1.2": 1, "Cav1.2_confidence": "97.7%"
  },
  "provenance": { "model": "ctoxpred2", "variant": "dl-sl", "torch_version": "...", "citation": "...", "license": "..." }
}
```

### `endpoint_values` - the three 0/1 votes

| key | channel | type | meaning |
| --- | --- | --- | --- |
| `hERG_vote` | hERG | 0/1 int | 1 = predicted blocker (feeds the hERG gate as a confidence-weighted vote) |
| `NaV1.5_vote` | NaV1.5 | 0/1 int | 1 = predicted blocker (context) |
| `CaV1.2_vote` | CaV1.2 | 0/1 int | 1 = predicted blocker (context) |

### `uncertainty` - the parsed confidences

`confidence` = the **hERG** confidence parsed from `"{:.1%}"` to a `[0, 1]` float (the reserved scalar
field). NaV1.5/CaV1.2 confidences (context) and the verbatim upstream percent strings for all three go in
`extra`. The operational AD rule / calibration that would consume these is DEFERRED (CLAUDE.md §4a); we
reserve the fields, we do not decide the policy.

### Invalid input

An empty / RDKit-unparseable SMILES -> a valid record with all votes `null`, `uncertainty` null, and the
reason in `raw.error`. The adapter does not crash, so one bad molecule never sinks a bulk batch.

## Uniform CLI

```
python run.py --input <path> --output <path> [--gpu N]
```

`--gpu` is accepted and **ignored** (`requires_gpu=False`); the DNN is tiny and runs on CPU (the upstream
sl path pins `torch.device("cpu")`). It exists only so the dispatcher can build one command for every model.

## Environment / install

`pixi.toml` is intent; `pixi.lock` is **solved on the box** (Linux + conda-forge) and committed, carrying a
real `linux-64` section with package hashes. `platforms = ["linux-64"]` because macOS cannot resolve the
per-model env.

The upstream **code** is vendored unmodified under `vendor/CToxPred2/` (the inner package: `utils.py`,
`pairwise_correlation.py`, `hERG_model.py`, `nav15_model.py`, `cav12_model.py`, `architecture_framework.py`,
`__init__.py`, `LICENSE`). The **weights** are NOT committed (CLAUDE.md §0). Upstream ships them compressed
(`.rar`) under `CToxPred2/models`; on the box they are cloned and decompressed under
`vendor/CToxPred2/models` (gitignored). Decompression uses `unrar` (the archives are RAR; no `unrar`/`7z`
was on the box, so `pixi exec --spec unrar -- unrar x` is used). Setup on the box:

```
cd endpoints/herg/ctoxpred2
git clone --depth 1 https://github.com/issararab/CToxPred2.git /tmp/ctox_src
mkdir -p vendor/CToxPred2/models
cp /tmp/ctox_src/CToxPred2/models/*.rar vendor/CToxPred2/models/
cd vendor/CToxPred2/models
pixi exec --spec unrar -- unrar x -o+ model_weights.rar ./
pixi exec --spec unrar -- unrar x -o+ decriptors_preprocessing.rar ./   # (RF path also: random_forest.rar)
```

Pins that matter (mirror upstream `install.sh`; verified on the box):
- **`scikit-learn == 1.3.1`** - the version that unpickles the shipped descriptor-preprocessing pipelines.
- **`numpy == 1.23.5`**, **`scipy == 1.11.4`**, **`pandas == 2.0.3`**, **`python 3.9`** - upstream pins.
- **`pytorch == 1.12.1`** (CPU build) - loads the DNN checkpoints via `torch.load(map_location="cpu")`.
- **`mordredcommunity`** (maintained fork) supplies the `mordred` import for the 2D descriptors; it emits
  the same 1613 2D descriptor set the pipelines were fit on (verified: NaV1.5/CaV1.2 feature dims 2453 /
  2586 match the shipped checkpoints).
- **`openbabel == 3.1.1`** supplies `from openbabel import pybel` for PyBioMed's fingerprint module.
- **`PyBioMed`** (git-only) computes the ECFP2 (1024) + PubChem (881) fingerprints (1905 total).
- **Dropped vs upstream `install.sh`:** `torch-geometric` and `MolVS` (GUI / GCN / image / standardization
  only - not on the headless DNN prediction path).

## Provenance

- **Upstream:** `github.com/issararab/CToxPred2` (Issar Arab / Bittremieux group). Repo cloned at build
  time; the inner-package code is vendored, the `.rar` weights are decompressed into the env (gitignored).
- **Citations:**
  - Arab I, Laukens K, Bittremieux W. "Semisupervised Learning to Boost hERG, Nav1.5, and Cav1.2 Cardiac
    Ion Channel Toxicity Prediction by Mining a Large Unlabeled Small Molecule Data Set." *J. Chem. Inf.
    Model.* (2024). doi:10.1021/acs.jcim.4c01102
  - Arab I, et al. "Benchmarking of Small Molecule Feature Representations for hERG, Nav1.5, and Cav1.2
    Cardiotoxicity Prediction." *J. Chem. Inf. Model.* (2023). doi:10.1021/acs.jcim.3c01301
- **Access tag:** CODE-PKG.
- **License:** upstream code is **MIT** (Copyright (c) 2024 Issar Arab; see `vendor/CToxPred2/LICENSE`).
- **Quirks:** GUI-only entrypoint upstream (driven headless via the notebook's DNN function); confidence is
  a percent STRING that must be parsed; MC-dropout keeps dropout ON at inference (`.train()`) by design;
  the `.sav` pipelines unpickle only with `CorrelationThreshold` present in `__main__`; the weights ship
  as `.rar` and need `unrar`.

## Smoke

```
pixi run --manifest-path pixi.toml python run.py \
  --input ../../../tests/fixtures/fto43.smi --output /tmp/ctoxpred2.out.json
```

yields three 0/1 votes (`hERG_vote` / `NaV1.5_vote` / `CaV1.2_vote`) and three confidences parsed from the
`"{:.1%}"` strings for the FTO-43 fixture. `tests/test_model_ctoxpred2.py` (`@pytest.mark.model`) drives
this on the box and validates the output against `core.schemas`.
