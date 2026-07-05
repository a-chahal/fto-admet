# cardiotox_net - CardioTox net hERG blocker probability (deep-learning meta-feature ensemble), hERG endpoint

CardioTox net (`Abdulk084/CardioTox`, Karim et al., J. Cheminformatics 2021) is a stacked deep-learning
meta-feature ensemble for hERG channel blockade. It is the healthiest, most drop-in hERG model in the
gate (a clean `cardiotox` package with one API call), on a legacy TensorFlow stack. It is a **primary**
hERG model: its output is P(hERG block), fed to the hERG gate's core probability average.

## Role: primary, an identity P(block)

`in_bulk_loop = True` - CardioTox net is a bulk-loop primary. Each molecule gets one **P(hERG block)**
in `(0, 1)` (**UP = more likely blocker**, more cardiotoxic), mapped straight into
`endpoint_values["P_block"]` (identity - it is already a probability). The hERG gate math that combines
this with the other hERG models (BayeshERG, ADMET-AI, ADMETlab, the CToxPred2 vote) is DEFERRED to t52;
this adapter only emits the raw per-model signal.

## The ensemble

Four base learners, each self-preprocessing, under a trained meta-learner (a small MLP over their
outputs):
- **DescModel** - a Mordred 2D-descriptor MLP (995 selected descriptors, from `des_file.txt`, normalized
  by a shipped scaler).
- **FingerprintModel** - an ECFP2 (1024) + PubChem (881) = 1905-bit fingerprint MLP (fingerprints via
  PyBioMed).
- **SVModel** - a SMILES-vector CNN (per-character tokenization, padded to 97).
- **FVModel** - a Morgan fingerprint-vector CNN (the on-bit index list of a radius-2, 1024-bit Morgan
  fingerprint, truncated to 93 - this is where the applicability limit comes from).

The stacked meta-learner ends in a single `sigmoid`, so `predict()` returns one P(block) per molecule.

## LANDMINE - bare array, POSITIONAL alignment (CLAUDE.md 4, IO_SPEC 1 #5)

`ensemble.predict(smiles, probabilities=False)` returns a **bare NumPy array** of P(block) - shape
`(N, 1)` from the meta-learner's single sigmoid - with **no named field to key on**. The adapter aligns
it **positionally** to the input list; a misalignment would silently mislabel every molecule. `run.py`
asserts the returned length equals the number of scored SMILES, and the smoke test asserts length + order.

(With `probabilities=True` the upstream helper expands the output to two columns
`[P(non-blocker), P(blocker)]` for LIME; column 1 there equals what `probabilities=False` already
returns, so `run.py` takes the simpler `probabilities=False` path.)

## LANDMINE - applicability limit (flag, never drop - CLAUDE.md 4, IO_SPEC 1 #5)

CardioTox net is documented as **"only suitable for SMILES with max number of 1's in Morgan fingerprint
<= 93"**: the fingerprint-vector base model truncates the on-bit index list to 93, so a molecule with
more on-bits falls outside the applicability domain. The adapter computes the on-bit count of the exact
fingerprint that base model uses (RDKit Morgan, **radius 2, 1024 bits**) and records:
- `uncertainty.ad_in_domain` = `True` when on-bits <= 93 (the reserved applicability-domain field),
- `uncertainty.extra.morgan_onbits` / `morgan_onbit_limit` (= 93) / `in_applicability_domain`,
- the same three mirrored in `raw`.

The molecule is **never dropped**; an out-of-range molecule is flagged so the hERG gate can down-weight
rather than trust it. Native aleatoric/epistemic uncertainty for CardioTox net is **INDIRECT**
(ensemble-vs-ensemble agreement, computed at t52), so `uncertainty.aleatoric` / `epistemic` stay `null`
here; only the applicability-domain flag is emitted.

## Output contract (the JSON keys the dispatcher validates)

`run.py` runs in this model's isolated env and cannot import `core`, so it writes plain JSON matching
`core.schemas.OutputRecord`. One input record -> one output object; a JSON array or `.smi` in -> a JSON
array out. Each record:

```json
{
  "model": "cardiotox_net",
  "endpoint_values": { "P_block": 0.123 },
  "uncertainty": {
    "aleatoric": null, "epistemic": null, "ad_in_domain": true,
    "extra": { "morgan_onbits": 41, "morgan_onbit_limit": 93, "in_applicability_domain": true }
  },
  "raw": {
    "smiles": "...", "mol_id": "...", "P_block": 0.123,
    "morgan_onbits": 41, "morgan_onbit_limit": 93, "in_applicability_domain": true
  },
  "provenance": { "model": "cardiotox_net", "tensorflow_version": "2.3.1", "upstream_commit": "...", "citation": "...", "license": "..." }
}
```

### `endpoint_values`

| key | quantity | range | direction |
| --- | --- | --- | --- |
| `P_block` | P(hERG block) from the meta-ensemble | 0-1 | **UP = more likely blocker** (more cardiotoxic) |

### Invalid input

An empty / RDKit-unparseable SMILES -> a valid record with `P_block` null, `uncertainty` null, and the
reason in `raw.error`. The adapter does not crash, so one bad molecule never sinks a bulk batch.

## Uniform CLI

```
python run.py --input <path> --output <path> [--gpu N]
```

`--gpu` is accepted and **ignored** (`requires_gpu=False` in practice): the ensemble is tiny and the
legacy TF 2.3.1 / old-CUDA stack does not cooperate with the box's modern driver, so `run.py` forces CPU
(`CUDA_VISIBLE_DEVICES=-1`). It exists only so the dispatcher can build one command for every model.

## Environment / install

`pixi.toml` is intent; `pixi.lock` is **solved on the box** (Linux + conda-forge + pip) and committed,
carrying a real `linux-64` section with package hashes. `platforms = ["linux-64"]` because macOS cannot
resolve the per-model env.

The upstream **code and weights are NOT committed** (CLAUDE.md 0: never commit weights - the trained TF
checkpoints are ~216 MB). Instead `run.py::_ensure_vendor()` **clones the whole upstream repo once, on
first use**, into the gitignored `vendor/CardioTox` and pins it to the exact commit
`6096ef004016f82a64df99e5df8c1133d7092550`. `load_ensemble()` addresses its checkpoints by paths relative
to that repo root, so `run.py` chdirs into `vendor/CardioTox` for the load + predict. The clone needs
network + `git` (both present on the box; `git` is in the env).

Pins that matter (read from upstream `environment.yml`; verified on the box):
- **`tensorflow == 2.3.1`** - the **landmine pin**. The base models import the private
  `tensorflow.python.keras.*` API that TF >= 2.4 removed; a newer TF ImportErrors on import.
- **`keras == 2.4.3`** - `fv_model.py` does a standalone `import keras` (not `tf.keras`); 2.4.3 pairs
  with TF 2.3.
- **`numpy == 1.18.*`** (TF 2.3.1's `< 1.19` bound), **`h5py == 2.10.*`** (TF 2.3.1 requires `< 2.11`;
  used for checkpoint loading), **`pandas == 1.1.*`**, **`rdkit 2020.09`**, **`scikit-learn 0.24`**.
- **`mordredcommunity`** (maintained fork) supplies the `mordred` import for the descriptor base model;
  it emits the same descriptor names, so the 995 columns in `des_file.txt` resolve.
- **`openbabel == 3.1.1`** supplies `from openbabel import pybel` for PyBioMed's fingerprint module.
- **`PyBioMed`** (git-only, `gadsbyfly/PyBioMed`) computes the ECFP2 (1024) + PubChem (881) fingerprints
  (1905 total) the fingerprint base model was trained on.

## Provenance

- **Upstream:** `github.com/Abdulk084/CardioTox` (official). Repo cloned + pinned at build time; code +
  the `.ckpt` weights live in the gitignored `vendor/CardioTox` (never in git).
- **Citation:** Karim A, Lee M, Balle T, Sattar A. "CardioTox net: a robust predictor of hERG channel
  blockade based on deep learning meta-feature ensembles." *J. Cheminformatics* 13:60 (2021).
  doi:10.1186/s13321-021-00541-z (also BioModels MODEL2407180003).
- **Access tag:** CODE-PKG.
- **License:** upstream repo ships no explicit LICENSE file; code is a public research package (see
  `github.com/Abdulk084/CardioTox`). Any downstream use inherits whatever the upstream terms are.
- **Quirks:** legacy TF 2.3.1 (private `tensorflow.python.keras` API - do not bump TF); `predict()`
  returns a bare positional array (no named field); checkpoints addressed by paths relative to the repo
  root (so `run.py` chdirs into the vendor clone); applicability limited to <= 93 Morgan on-bits;
  weights (~216 MB) fetched at first use, not committed.

## Smoke

```
pixi run --manifest-path pixi.toml python run.py \
  --input ../../../tests/fixtures/fto43.smi --output /tmp/cardiotox_net.out.json
```

yields a finite `P_block` in `[0, 1]` aligned to the FTO-43 fixture and a populated applicability-domain
flag (`ad_in_domain` + Morgan on-bit count). `tests/test_model_cardiotox_net.py` (`@pytest.mark.model`)
drives this on the box and validates the output against `core.schemas`.
