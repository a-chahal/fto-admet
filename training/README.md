# training - the offline fusion trainer

Turns clean, leakage-free experimental data into committed **fusion specs**
(`core/fusion/specs/<endpoint>__<feature>.json`) that the aggregators apply at inference via
`core.fusion.fuse`. The trained model per feature is ~5 numbers (per-source calibration + fusion weights +
intercept + a conformal quantile), stored as human-readable JSON - not a model blob.

## Layout
```
training/
  recipes/<endpoint>__<feature>.yaml   # the reviewed scientific plan per feature (target, dataset, sources)
  datasets/                            # loaders for each clean source (biogen, kpuu, chembl_temporal, tox)
  features.py                          # batch-screen a dataset's SMILES on the box -> feature matrix
  fit.py                               # per-source calibration + fusion weights (nnls/ridge/logistic)
  conformal.py                         # normalized (input-dependent) conformal quantile
  train_endpoint.py                    # CLI orchestrator: recipe -> data -> screen -> fit -> spec
  pixi.toml                            # cross-platform trainer env (sklearn/pandas/rdkit)
```

## What is committed vs on /zfs
- **Committed:** this code, the `recipes/`, and the tiny trained `core/fusion/specs/*.json`.
- **Gitignored, on `$FTO_ADMET_ROOT/training/` (/zfs):** raw clean datasets (`data/`), the exclusion index
  (`exclusion_index/index.parquet`), screened feature matrices (`features/`), and run reports (`reports/`).

## Flow (`python -m training.train_endpoint --feature <endpoint>__<feature>`)
1. Read the recipe (target, transform, clean dataset, sources, calibration, leakage set).
2. Load + standardize the clean dataset (RDKit: salt-strip, neutralize, canonical tautomer -> InChIKey).
3. **Subtract leakage** against `exclusion_index/index.parquet` (drop any molecule in a contributing
   model's training union). Refuse to proceed if the surviving count is below the recipe's floor.
4. Batch-screen the survivors on the box -> feature matrix `X` (the frozen models' outputs), cached to
   `/zfs/.../features/<feature>.parquet`.
5. Split (scaffold + a strict InChIKey hold-out); fit per-source calibration + weights on train; fit the
   normalized-conformal quantile on the calibration split.
6. Write `core/fusion/specs/<endpoint>__<feature>.json` (+ a `/zfs/.../reports/<feature>.md`).
7. The aggregator picks it up on the next screen (no aggregator code change).

## Conventions
- A spec is ONLY ever written by `train_endpoint.py` - never hand-edited (no-fabricate, CLAUDE.md §5).
- Every spec stamps its dataset hash, exclusion-index hash, n_train/n_calib, held-out metrics + conformal
  coverage, and the git sha, so any trained score is reconstructible.
- Small data is fine (~5 params): ~10-20 points/param for the weights, but keep >= ~100 for the conformal
  calibration split, and keep per-source calibration LINEAR (not isotonic) below a few hundred points.
```
