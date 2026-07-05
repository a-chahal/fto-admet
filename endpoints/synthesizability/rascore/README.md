# rascore - RAscore retrosynthetic-accessibility classifier, synthesizability endpoint

RAscore (`reymond-group/RAscore`, Thakkar et al., Chem. Sci. 2021) is a machine-learned binary
classifier that predicts whether a computer-aided synthesis planning tool (AiZynthFinder) can find a
synthetic route to a molecule. It was trained on 200,000 ChEMBL compounds labelled 1/0 by AiZynthFinder,
and is a fast (~4500x) surrogate for actually running the retrosynthesis search.

## Role: second rung of the synthesizability tier ladder

`in_bulk_loop = True`. The synthesizability tier is a **ladder**, not an average (docs IO_SPEC 1 #26 / 2):

```
SAscore (rung 1)  ->  RAscore (rung 2)  ->  AiZynthFinder (rung 3)
1-10, lower=easier    P(route findable)     real route search (is_solved + routes)
```

RAscore is **rung 2**: a cheap classifier for *route-findability*. It is **NOT a route search** - that
is rung 3, AiZynthFinder (task t32), a distinct model that actually runs the MCTS retrosynthesis. Keep
the two separate: RAscore answers "is a route *likely* findable?" as a probability; AiZynthFinder answers
"here *is* a route (or not)". The rungs use different scales and are reported as a tier, never averaged.

Each molecule gets one **RAscore** in `[0, 1]`, mapped straight into `endpoint_values["RAscore"]`.

| key | quantity | range | direction |
| --- | --- | --- | --- |
| `RAscore` | P(a synthetic route is findable by AiZynthFinder) | 0-1 | **UP = more likely synthesizable** |

Note the direction is the natural "higher = better" sense, the **opposite** of its rung-1 neighbour
SAscore (where **lower** = easier to synthesize). The t48 synthesizability aggregator harmonizes the two.

## Which classifier: XGB (ECFP-counts), not the DNN

RAscore ships two pretrained variants, both trained on the same 200k-ChEMBL AiZynthFinder labels and both
emitting the same P(route findable):
- **XGB / ECFP-counts** (`models/XGB_chembl_ecfp_counts/model.pkl`) - a pickled XGBoost sklearn wrapper
  over a counted ECFP6 (Morgan radius 3, 2048-fold) fingerprint. **This adapter uses this one.**
- **DNN / FCFP-counts** (`models/DNN_chembl_fcfp_counts/model.h5`) - a TensorFlow/Keras MLP over a
  counted FCFP6 fingerprint.

Two reasons for XGB:
1. **TF-free.** The DNN needs `tensorflow-gpu == 2.5.0` (a heavy CUDA dependency that fights the box's
   modern driver, the same fight the sibling hERG models had at t30). The XGB path is pure
   scikit-learn/xgboost/numpy/rdkit - the env resolves cleanly and the model unpickles on the box with no
   legacy-TF machinery.
2. **The NN default is broken upstream** at this pinned commit: `RAscore_NN.RAScorerNN()` loads
   `models/DNN_chembl_fcfp_counts/model.tf`, but the shipped `models.zip` contains only `model.h5`, so the
   default NN path raises. The XGB default (`model.pkl`) is present and correct.

## LANDMINE - pinned 2021 stack (CLAUDE.md 4, IO_SPEC 1 #26, task t31)

The pretrained classifier can **only be unpickled with the exact upstream versions**. Upstream's README
("Known Installation Issues") states this verbatim: *"The following versions must be used in order to use
the pretrained models ... because of the pickling method used to save the model and compatibility issues
arising between different versions."* The load-bearing pins:

- **`scikit-learn == 0.22.1`** - `model.pkl` is an `xgboost.sklearn` wrapper; a different sklearn fails to
  unpickle or unpickles into an object that predicts garbage.
- **`xgboost == 1.0.2`** - the version the classifier was saved with.
- **`python == 3.7`**, **`rdkit 2020.09`** (upstream used 2020.03; the ECFP6-count fingerprint is stable).

A wrong pin is a **silent** failure (the whole point of the landmine), so the smoke test asserts a finite
probability in `[0, 1]`, which only happens when the correct classifier actually loaded.

## Output contract (the JSON keys the dispatcher validates)

`run.py` runs in this model's isolated env and cannot import `core`, so it writes plain JSON matching
`core.schemas.OutputRecord`. One input record -> one output object; a JSON array or `.smi` in -> a JSON
array out. Each record:

```json
{
  "model": "rascore",
  "endpoint_values": { "RAscore": 0.87 },
  "uncertainty": null,
  "raw": {
    "smiles": "...", "mol_id": "...", "RAscore": 0.87,
    "model_variant": "XGB_chembl_ecfp_counts",
    "scale": { "min": 0.0, "max": 1.0, "direction": "higher = more likely a synthetic route exists (more synthesizable)" },
    "tier": "synthesizability rung 2 of 3 (SAscore -> RAscore -> AiZynthFinder)"
  },
  "provenance": { "model": "rascore", "model_variant": "XGB_chembl_ecfp_counts", "scikit_learn_version": "0.22.1", "xgboost_version": "1.0.2", "rdkit_version": "...", "upstream_commit": "...", "citation": "...", "license": "MIT ..." }
}
```

`uncertainty` is `null`: RAscore is a single-probability classifier with no native aleatoric/epistemic
split (the reserved schema fields stay null rather than fabricated, per CLAUDE.md 3).

### Invalid input

An empty / RDKit-unparseable SMILES -> a valid record with `RAscore` null and the reason in `raw.error`
(the upstream `RAScorerXGB.ecfp` does not guard against a bad parse, so `run.py` pre-validates with
RDKit). The adapter does not crash, so one bad molecule never sinks a bulk batch.

## Uniform CLI

```
python run.py --input <path> --output <path> [--gpu N]
```

`--gpu` is accepted and **ignored** (`requires_gpu=False`): the XGB classifier is CPU-only. It exists
only so the dispatcher can build one command for every model.

## Environment / install

`pixi.toml` is intent; `pixi.lock` is **solved on the box** (Linux + conda-forge) and committed, carrying
a real `linux-64` section with package hashes. `platforms = ["linux-64"]` because macOS cannot resolve
the per-model legacy env.

The upstream **code and trained models are NOT committed** (CLAUDE.md 0: never commit weights/data - the
models are ~64 MB in `models.zip`). Instead `run.py::_ensure_vendor()` **clones the whole upstream repo
once, on first use**, into the gitignored `vendor/RAscore`, pins it to the exact commit
`cb77db503ee5cbf0e8bb8963df6e5b76b3a94f06`, and unzips `models.zip` in place. `RAScorerXGB()` resolves
`model.pkl` by a path relative to the package dir. The clone needs network + `git` (both present on the
box; `git` is in the env).

Pins that matter (upstream `setup.cfg` + README "Known Installation Issues"; verified on the box):
- **`scikit-learn == 0.22.1`**, **`xgboost == 1.0.2`** - the unpickle landmine.
- **`python == 3.7`**, **`rdkit 2020.09`** (ECFP6-count fingerprint; upstream used 2020.03).
- `numpy` - resolver picks the py37/sklearn-0.22.1-compatible build.

## Provenance

- **Upstream:** `github.com/reymond-group/RAscore` (Reymond Group, University of Bern / MolecularAI
  AstraZeneca). Repo cloned + pinned at build time; code + `models.zip` live in the gitignored
  `vendor/RAscore` (never in git).
- **Citation:** Thakkar A, Chadimova V, Bjerrum EJ, Engkvist O, Reymond J-L. "Retrosynthetic
  accessibility score (RAscore): rapid machine learned synthesizability classification from AI driven
  retrosynthetic planning." *Chem. Sci.* 12:3339-3349 (2021). doi:10.1039/D0SC05401A (PMC8179384).
- **Access tag:** CODE-PKG.
- **License:** MIT (`LICENSE`, Copyright 2020 Reymond Research Group, University of Bern).
- **Quirks:** the pretrained model.pkl unpickles only under sklearn 0.22.1 + xgboost 1.0.2 (pinned); the
  DNN default path (`model.tf`) is broken in this commit (only `model.h5` ships), so the XGB variant is
  used; trained models (~64 MB) fetched at first use, not committed.

## Smoke

```
pixi run --manifest-path pixi.toml python run.py \
  --input ../../../tests/fixtures/fto43.smi --output /tmp/rascore.out.json
```

yields a finite `RAscore` in `[0, 1]` for the FTO-43 fixture. `tests/test_model_rascore.py`
(`@pytest.mark.model`) drives this on the box and validates the output against `core.schemas`.
