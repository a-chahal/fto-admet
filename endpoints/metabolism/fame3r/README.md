# fame3r - per-atom site-of-metabolism probability, metabolism endpoint

FAME3R (molinfo-vienna/FAME3R, Jacob et al., *J. Cheminform.* 2026) is the Python re-design of the legacy
Java FAME 3. It predicts, per atom, the probability that the atom is a **site of metabolism (SoM)** - a
starting point for a molecule's metabolic fate. It is the second model of the metabolism endpoint,
co-ranked ordinally with SMARTCyp (t42, F-2); the whole endpoint is JVM-free.

## Role: per-atom SoM ranking (probability) + a native applicability-domain score

- **Per-atom SoM probability** = a scikit-learn `RandomForestClassifier.predict_proba(...)[:, 1]` in
  `[0, 1]`, **UP = more likely SoM**.
- **FAME3RScore** = a separate `FAME3RScoreEstimator(n_neighbors=3)`: mean Tanimoto similarity to the k
  nearest reference atoms (`[0, 1]`, UP = more in-domain/reliable). This is the reliability signal, **not**
  Shannon entropy.

## Landmines (CLAUDE.md §4, IO_SPEC §1 #9)

- **No hard-coded 0.3 threshold.** 0.3 was the *legacy Java FAME 3* decision threshold; FAME3R emits a raw
  probability and this adapter applies **no** binarization. (The fame3r CLI defaults `--threshold 0.3` as a
  convenience for its own binary column; we bypass the CLI and emit the raw `predict_proba[:,1]`.) The t42
  aggregator co-ranks atoms **ordinally** with SMARTCyp, never by thresholding or averaging (F-2).
- **Direction:** higher FAME3R probability = more likely SoM - the **opposite** of SMARTCyp (lower
  `Score`/`Ranking` = more likely SoM). Co-rank ordinally; never average the two raw scales.
- **Atom indices are attached by the adapter.** FAME3R ships no `atom_id` column; atoms are supplied as
  atom-marked SMILES. RDKit marks one atom with an atom-map number (`atom_to_marked_smiles`), CDPKit inside
  `FAME3RVectorizer(input="smiles")` reads that mark, and the map rides through canonicalization, so
  `probs[i]` is the SoM probability of RDKit atom index `i`. The adapter attaches that index in `raw.atoms`.

## How FAME3R is packaged (the pivotal fact)

FAME3R v2.0.0 is **scikit-learn components, not a turnkey predictor, and it ships NO trained model.** The
public package (`pip install fame3r`, MIT) is `FAME3RVectorizer` + `FAME3RScoreEstimator` (both on the
CDPKit/CDPL toolkit) plus a CLI to *train your own* model. The per-atom SoM signal is produced by a
`RandomForestClassifier` you must supply.

### The production model is a GATED download (status = needs_aaran)

The paper-grade FAME3R models are trained on the **MetaQSAR** database and are **not** in the pip package.
They are published on **Zenodo, DOI [10.5281/zenodo.17223468](https://doi.org/10.5281/zenodo.17223468)**,
which is **restricted access** (the owner must approve a per-user request), and the MetaQSAR-derived models
additionally require a **commercial license from the Universita degli Studi di Milano** for for-profit use
(`nerdd.yml` / NERDD help text). Four subsets exist: all (phase 1+2), phase1, phase2, cyp.

The headless build session cannot make a restricted-access request or accept a license, so the real models
could not be fetched. This is the only outstanding step: **`needs_aaran`**. To finish:

1. Request access to Zenodo 10.5281/zenodo.17223468 (and clear the UniMi commercial-license terms if
   applicable), download the desired subset's `random_forest_classifier.joblib` +
   `fame3r_score_estimator.joblib`.
2. Drop both files into `endpoints/metabolism/fame3r/data/models/` (or point `FAME3R_MODELS_DIR` at them)
   and update `data/models/model_source.txt` to record the MetaQSAR provenance.
3. Re-run the smoke (`tests/test_model_fame3r.py`). No code change is needed - the adapter loads the bare
   estimators in the same layout the fame3r CLI / Zenodo archive use.

### The example model used to prove the adapter (the smoke)

To verify the adapter end-to-end without the gated weights, `build_example_model.py` trains the **upstream
tutorial-example model** - byte-for-byte the recipe in FAME3R's `docs/source/tutorials/PythonAPI.ipynb`, on
the `metatrans_autoannotated_cleaned` dataset shipped in that tutorial. Upstream states plainly this
example model "is not expected to be useful for real metabolism prediction"; it is a **stand-in that
exercises the machinery**, exactly like the FTO-43 placeholder SMILES fixture. run.py stamps
`provenance.model_source` onto every record, so no output ever silently claims to be the MetaQSAR paper
model. The smoke against this example model passes (valid per-atom table + FAME3RScore, correct
units/direction).

## Output contract (the JSON keys the dispatcher validates)

`run.py` runs in this model's isolated env and cannot import `core`, so it writes plain JSON matching
`core.schemas.OutputRecord`. One input record -> one output object; a JSON array / `.smi` in -> array out.

```json
{
  "model": "fame3r",
  "endpoint_values": { "max_som_probability": 0.62, "top_som_atom_index": 3, "n_atoms_scored": 24 },
  "uncertainty": {
    "ad_index": 0.71,
    "extra": { "fame3r_score_per_atom": [0.7, 0.68, ...], "fame3r_score_mean": 0.66, "ad_signal": "..." }
  },
  "raw": {
    "smiles": "...", "mol_id": "...", "radius": 5, "threshold_policy": "none applied; raw predict_proba[:,1]...",
    "atoms": [ { "atom_index": 0, "element": "C", "som_probability": 0.12, "fame3r_score": 0.7 }, ... ]
  },
  "provenance": { "model": "fame3r", "method": "...", "fame3r_version": "...", "model_source": "...", "citation": "...", "license": "...", "direction": "..." }
}
```

- **`endpoint_values`** holds only molecule-level SCALAR summaries derived from the per-atom table
  (`max_som_probability` = the softest spot; `top_som_atom_index` = which RDKit atom; `n_atoms_scored`).
  Per-atom values are deliberately **not** crammed into scalar `endpoint_values` (IO_SPEC §1 #9).
- **`raw.atoms`** is the load-bearing per-atom SoM table (RDKit `atom_index`, `element`, `som_probability`,
  `fame3r_score`) - the payload t42 co-ranks ordinally with SMARTCyp.
- **`uncertainty`** carries FAME3RScore: `ad_index` = the top-SoM atom's FAME3RScore (0-1, reserved AD
  field per CLAUDE.md §3); `extra.fame3r_score_per_atom` = the full per-atom list; `extra.fame3r_score_mean`.
  Native signal only - the operational AD rule is DEFERRED (CLAUDE.md §4a).

### Invalid input

An unparseable / empty SMILES -> a valid record with null summaries, `uncertainty: null`, and the reason in
`raw.error` (RDKit returns `None` on a bad parse; the adapter catches it). One bad molecule never sinks a
bulk batch.

## Uniform CLI

```
python run.py --input <path> --output <path> [--gpu N]
```

`--gpu` is accepted and **ignored** (`requires_gpu=False`); FAME3R is CPU-only.

## Environment / install

`pixi.toml` is intent; `pixi.lock` is **solved on the box** (Linux + conda-forge/pypi) and committed,
carrying a real `linux-64` section with package hashes. `platforms = ["linux-64"]` because macOS cannot
resolve the per-model env.

Deps that matter: `fame3r == 2.0.0` (pulls `cdpkit == 1.2.3`, the CDPL toolkit, as a pypi wheel),
`scikit-learn >= 1.5.1`, `numpy >= 2.3.2`, `joblib >= 1.4.2` (fame3r's floors), and `rdkit` (for
`atom_to_marked_smiles`). Build the example model once on the box after `pixi install`:

```
# fetch the tutorial dataset (gitignored) and train the example model into data/models/
pixi run --manifest-path pixi.toml python build_example_model.py \
    --train-sdf data/metatrans_autoannotated_cleaned/train.sdf --out data/models
```

Model artifacts + the training SDF live under `data/` (repo-wide gitignored - weights are never committed,
CLAUDE.md §0). Replace them with the gated MetaQSAR joblibs for production (see above).

## Provenance

- **Upstream:** `fame3r` PyPI **v2.0.0** (`pip install fame3r`; also conda-forge); repo
  `github.com/molinfo-vienna/FAME3R` (Kirchmair group, University of Vienna).
- **Citation:** Jacob RA, Gaskin L, Seidel T, Chen Y, Mazzolari A, Kirchmair J. "FAME 3R: A Fast, Compact,
  Flexible, and Practical Re-Design of the FAME 3 Model for Predicting Sites of Metabolism." *J.
  Cheminform.* 2026. doi:10.1186/s13321-026-01161-1.
- **Access tag:** CODE-PKG (the code). The trained MetaQSAR models are a separate GATED artifact (restricted
  Zenodo access + UniMi commercial license).
- **License:** code MIT. Trained MetaQSAR models **CC-BY-NC-4.0** (non-commercial research; for-profit use
  needs a UniMi commercial license) - any SoM call made with them inherits the non-commercial restriction.
- **Quirks:** ships no model (train your own / gated Zenodo download); components use CDPKit but atoms are
  fed as RDKit-marked SMILES; no `atom_id` column (adapter attaches RDKit indices); the CLI's `--threshold
  0.3` is the legacy FAME 3 value and is NOT applied; direction is opposite to SMARTCyp.

## Smoke

```
pixi run --manifest-path pixi.toml python run.py \
  --input ../../../tests/fixtures/fto43.smi --output /tmp/fame3r.out.json
```

yields a per-atom SoM-probability table (RDKit atom indices attached) plus FAME3RScore in `uncertainty` for
the FTO-43 fixture. `tests/test_model_fame3r.py` (`@pytest.mark.model`) drives this on the box and validates
the output against `core.schemas`.
