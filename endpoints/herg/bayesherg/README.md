# bayesherg - hERG blocker probability + aleatoric/epistemic uncertainty split (hERG gate)

BayeshERG is a **concrete-dropout Bayesian graph neural network** (directed message-passing + multi-head
attention readout) for hERG channel block. It is a PRIMARY hERG model: its `score` is P(hERG block) fed to
the gate core average, and its MC-dropout uncertainty is decomposed into **aleatoric** (irreducible/noise)
and **epistemic** (out-of-domain) components. That split is what makes BayeshERG the hERG **split-case
adjudicator** (better than a single MC-dropout scalar), so the adapter emits it faithfully into the
reserved `uncertainty.aleatoric` / `uncertainty.epistemic` fields (CLAUDE.md 3, IO SPEC 1 #4).

This is the **oldest / most fragile env in the funnel** (t29, model-legacy): Python 3.6 + PyTorch 1.6.0 +
DGL 0.4.3 + RDKit 2021.03.5, run **CPU-only** (see Environment).

## Uncertainty-quality caveat (read before leaning on the split)

Independent 2024 work (AttenhERG, *J. Cheminformatics* 16:143, doi:10.1186/s13321-024-00940-y) states
BayeshERG's uncertainty estimation and accuracy "require considerable improvement." The hERG aggregator
leans on this split to break ties, so treat a **high-uncertainty disagreement as "measure it," not as a
resolved call**. The operational rule that consumes the split is DEFERRED (hERG gate math, t52).

## Output contract (the JSON keys the dispatcher validates)

`run.py` runs in this model's isolated env and cannot import `core`, so it writes plain JSON matching
`core.schemas.OutputRecord`. One input record -> one output object; a JSON array or `.smi` in -> a JSON
array out. Each record:

```json
{
  "model": "bayesherg",
  "endpoint_values": { "P_block": 0.087 },
  "uncertainty": { "aleatoric": 0.052, "epistemic": 0.011, "extra": { "mc_samples": 30 } },
  "raw": { "smiles": "...", "mol_id": "...", "score": 0.087, "alea": 0.052, "epis": 0.011 },
  "provenance": { "model": "bayesherg", "method": "...", "mc_samples": 30, "torch_version": "...",
                  "dgl_version": "...", "upstream_commit": "...", "citation": "...", "license": "..." }
}
```

### `endpoint_values`

| key | quantity | range | direction |
| --- | --- | --- | --- |
| `P_block` | P(hERG block) = upstream `score`, identity | 0-1 | **UP = more likely blocker** (more cardiotox); feeds the gate core average |

### `uncertainty` - the native aleatoric/epistemic split (DIRECT uncertainty)

Over `mc_samples` (=30) stochastic forward passes with concrete dropout left ON, per molecule:
- `score` = mean of P(block) across passes  ->  `endpoint_values.P_block`
- `aleatoric` = E[p(1-p)] across passes (irreducible / label-noise)  ->  `uncertainty.aleatoric`
- `epistemic` = Var[p] across passes (model / out-of-domain)  ->  `uncertainty.epistemic`

This is the exact decomposition upstream `main.py` computes (`alea`/`epis` columns). Both are floats >= 0;
UP = noisier / more out-of-domain. `uncertainty.extra.mc_samples` records the sample count. These are
native signals only - the operational applicability-domain rule and calibration are DEFERRED (CLAUDE.md
4a); this adapter emits the raw split and decides no policy.

### Invalid input

An unparseable / empty SMILES -> a valid record with `endpoint_values.P_block` null, `uncertainty` null,
and the reason in `raw.error` (RDKit returns `None` on a bad parse). The adapter does not crash, so one bad
molecule never sinks a bulk batch. A batch-level prediction failure degrades every record to a null with
the reason in `raw.error` rather than raising.

## Uniform CLI

```
python run.py --input <path> --output <path> [--gpu N]
```

`requires_gpu=True` in the registry, but a **CPU fallback is honored and is the default here**: the legacy
py3.6 + DGL 0.4.3 + torch 1.6.0 stack does not cooperate with the box's modern 575.x CUDA driver, so the
env pins the CPU torch build. `--gpu N` selects `cuda:N` only if a CUDA build is present AND available;
otherwise it silently falls back to CPU (the accepted shortlist behavior).

## Environment / lock

`pixi.toml` is intent; `pixi.lock` is **solved on the box** (Linux; channels `pytorch` + `dglteam` +
`conda-forge`) and committed, carrying a real `linux-64` section with package hashes.
`platforms = ["linux-64"]` because macOS cannot resolve this legacy Linux stack.

Pins that matter (taken from upstream `vendor/BayeshERG/environment.yml`):
- **`python == 3.6`**, **`pytorch == 1.6.0`** (+ `cpuonly` mutex -> CPU build), **`dgl == 0.4.3`** (CPU
  build, NOT `dgl-cuda10.2`), **`rdkit == 2021.03.5`**.
- `dgl 0.4.x` is a **hard pin, not a floor**: it exposes the `dgl.data.chem` featurizers
  (`CanonicalAtomFeaturizer`, `CanonicalBondFeaturizer`, `smiles_to_bigraph`) that both upstream `main.py`
  and this adapter use; those were removed in `dgl >= 0.5`.
- `requests == 2.25.1` (fetches the weights once), `tqdm == 4.38.0`, `dataclasses` (py3.6 backport), `numpy`.

## Weights + license (LANDMINE - dual license)

The BayeshERG **source code is MIT** (`vendor/BayeshERG/LICENSE`), but the **trained weights**
(`model/model_weights.pth`) are **CC-BY-NC-4.0** (`vendor/BayeshERG/CC-BY-NC-SA-4.0`): academic / individual
research use only, **no commercial use**. Because the model can only run with the shipped weights, the
usable artifact is non-commercial, and **any hERG hit found with them inherits that restriction** (fine for
an academic UCSD program; recorded in every emitted `provenance.license`).

The weights are **not committed to git** (binary + NC): `run.py` fetches them once, on first use, from the
pinned upstream commit `25e9466499905a952f9d41cc6bc6886c3f247acb` into the gitignored
`vendor/BayeshERG/model/model_weights.pth` and caches them there (retry/backoff; a missing weight is a loud
error, never a silent wrong prediction).

## Vendoring quirk (why we reimplement inference instead of shelling to upstream `main.py`)

Upstream `main.py` does `bg.ndata.pop('h')` inside its MC-sampling loop. In dgl 0.4.3, `dgl.batch` of a
**single-graph** list shares the node frame with the source graph, so the destructive `.pop('h')` strips
features from the source; the SECOND sampling pass then raises `KeyError: 'h'`. Upstream never hit this
because their example CSVs always held many molecules (multi-graph batches are copied, not shared). A
one-molecule input (e.g. the FTO-43 smoke) triggers it. `run.py` therefore reads features with
`bg.ndata['h']` / `bg.edata['e']` (NON-destructive, no `.pop`) - correct for batches of any size - and
computes the identical prediction/uncertainty math. It also skips the per-molecule attention `.svg`
rendering (not part of the bulk screening path). The upstream code lives **unmodified** under
`vendor/BayeshERG/`; the adapter imports its `model.BayeshERG_model` and featurizers.

## Provenance

- **Upstream:** `github.com/GIST-CSBL/BayeshERG` (official), pinned commit
  `25e9466499905a952f9d41cc6bc6886c3f247acb`. 92 commits, last modified 2022-11-18, no releases published.
- **Citation:** Kim H, Park M, Lee I, Nam H. "BayeshERG: a robust, reliable and interpretable deep learning
  model for predicting hERG channel blockers." *Brief. Bioinform.* 23(4):bbac211 (2022).
  doi:10.1093/bib/bbac211. Also: BioModels MODEL2408060001.
- **Access tag:** CODE-PKG.
- **License:** code MIT; trained weights + any hits **CC-BY-NC-4.0** (non-commercial). See the dual-license
  note above.
- **Quirks:** legacy py3.6 / DGL 0.4.3 / torch 1.6.0 stack, CPU-only on the box (modern-driver conflict);
  non-destructive feature read (dgl-0.4 single-graph batch landmine); MC-dropout seeded (`MC_SEED=0`) for a
  reproducible ledger value; uncertainty quality caveat (AttenhERG 2024). An Ersilia port (`eos4tcc`) exists
  as a fallback if the native legacy env ever stops resolving.

## Smoke

```
pixi run --manifest-path pixi.toml python run.py \
  --input ../../../tests/fixtures/fto43.smi --output /tmp/bayesherg.out.json
```

yields a finite `P_block` in [0, 1] plus non-negative `aleatoric` / `epistemic` for the FTO-43 fixture.
`tests/test_model_bayesherg.py` (`@pytest.mark.model`) drives this on the box and validates the output
against `core.schemas`.
