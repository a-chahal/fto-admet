# pksmart - human i.v. PK (CL / VDss / t1/2 / fu / MRT + fold-error), clearance endpoint

The **first real isolated env** (t11) and the second model template: it proves the subprocess dispatch
pattern on a genuine upstream package with real transitive deps, the box-lockfile round-trip, **and** the
reserved uncertainty fields (PKSmart emits a native fold-error). It follows the t10 folder/adapter shape
and adds a real env + populated uncertainty.

## Role: aggregate human clearance (ranking-only) + a native fold-error

PKSmart is a two-stage random forest: it predicts animal PK (rat/dog/monkey VDss/CL/fu) and feeds those as
features to a human RF. Structure in -> five human i.v. PK parameters + a per-parameter fold-error
(similarity-to-training-space dependent; widens out of domain).

### Weak-CL caveat (read before using CL)

CL is **weak**: repeated nested CV **R^2 = 0.31, GMFE ~= 2.43** (external test a bit better, GMFE ~1.98,
R^2 0.45). So CL is for **coarse binning + relative within-series ranking only** - do **not** treat the
absolute mL/min/kg number as actionable, and **surface the fold-error, never the bare CL number**. CL is
the FTO liability lens (series anchor ~= 89.6 mL/min/kg). The other four params (VDss/t1/2/fu/MRT) are
emitted for the DMPK picture but carry their own fold-errors too.

Clearance stays **decomposed** (F-3, CLAUDE.md §4): this CL (mL/min/kg) must **never** be combined
numerically with ADMET-AI's `Clearance_Hepatocyte_AZ` / `Clearance_Microsome_AZ`, OPERA `Clint`, or DruMAP
CLint - different units and matrices. That harmonization is the clearance aggregator's job (t43); this
adapter only emits CL + its fold-error faithfully.

## Output contract (the JSON keys the dispatcher validates)

`run.py` runs in this model's isolated env and cannot import `core`, so it writes plain JSON matching
`core.schemas.OutputRecord`. One input record -> one output object; a JSON array or `.smi` in -> a JSON
array out. Each record:

```json
{
  "model": "pksmart",
  "endpoint_values": {
    "CL_mL_min_kg": 10.41, "VDss_L_kg": 0.23, "t_half_h": 0.34, "fu": 0.67, "MRT_h": 0.51
  },
  "uncertainty": {
    "fold_error_low": 2.18, "fold_error_high": 49.67, "ad_in_domain": true,
    "extra": { "cl_fold_error": 4.77, "vdss_fold_error": 2.85, "fup_fold_error": 1.48,
               "mrt_fold_error": 4.25, "thalf_fold_error": 3.61, "ad_alert": "" }
  },
  "raw": { "smiles": "...", "mol_id": "...", "smiles_r": "...", "human": {...}, "animal": {...}, "ad_alert": "..." },
  "provenance": { "model": "pksmart", "method": "...", "pksmart_version": "...", "mordred_impl": "...", "citation": "...", "license": "..." }
}
```

### `endpoint_values` (units baked into the key names, CLAUDE.md §4)

| key | quantity | unit | direction |
| --- | --- | --- | --- |
| `CL_mL_min_kg` | total body clearance | mL/min/kg | **UP = faster clearance** (the FTO liability; ranking-only) |
| `VDss_L_kg` | volume of distribution (steady state) | L/kg | UP = more tissue distribution |
| `t_half_h` | half-life | h | UP = longer |
| `fu` | fraction unbound in plasma | 0-1 | UP = more free |
| `MRT_h` | mean residence time | h | UP = longer |

### `uncertainty` - the native fold-error (DIRECT uncertainty)

PKSmart's documented per-parameter fold-error IS exposed by `predict_pk_params()` (verified live at build
time; the repo's example CSVs only carried point predictions, so the field was read from the installed
package, not the CSV template). The **CL** prediction interval goes into the reserved
`uncertainty.fold_error_low` / `uncertainty.fold_error_high` (the lower / upper bounds = CL / fold-error and
CL * fold-error). Every parameter's raw fold factor (`*_fold_error`) and PKSmart's own applicability-domain
alert (`ad_alert`, a Tanimoto-to-training threshold message) are kept in `uncertainty.extra` so nothing
native is lost. `ad_in_domain` records that native alert (`true` = PKSmart raised no out-of-domain alert);
it is a native signal only - the operational AD rule and calibration are DEFERRED (CLAUDE.md §4a), not
decided here.

### Invalid input

An unparseable / empty SMILES -> a valid record with all `endpoint_values` null, `uncertainty` null, and
the reason in `raw.error` (PKSmart raises a `TypeError` from RDKit on a bad parse; the adapter catches it).
The adapter does not crash, so one bad molecule never sinks a bulk batch.

## Uniform CLI

```
python run.py --input <path> --output <path> [--gpu N]
```

`--gpu` is accepted and **ignored** (`requires_gpu=False`); PKSmart is CPU-only. It exists only so the
dispatcher can build one command for every model.

## Environment / lock

`pixi.toml` is intent; `pixi.lock` is **solved on the box** (Linux + conda-forge) and committed, carrying a
real `linux-64` section with package hashes. `platforms = ["linux-64"]` because macOS cannot resolve the
per-model env.

Pins that matter (verified on the box - a wrong pin silently fails to unpickle the shipped RF models):
- **`scikit-learn == 1.2.1`** - the version that loads PKSmart's shipped RF pickles. This is the landmine
  pin; do not bump it without re-verifying the pickles load.
- **`numpy == 1.23.5`**, **`pandas == 1.5.2`**, **`rdkit >=2023.3.3,<2024`** - pksmart v3.0.1's own pins.
- **`mordredcommunity`** (the maintained fork), **NOT** upstream `mordred` (unmaintained on modern Python).
  pksmart's wheel hard-pins `mordred==1.2.0`; mordredcommunity provides the same importable `mordred`
  package under a different distribution name, so the resolver will not treat it as satisfying that pin. We
  drop the transitive pin with a pypi `dependency-overrides` entry carrying an always-false env-marker
  (`sys_platform == 'never'`) and supply `mordredcommunity` from conda-forge as the real provider. This is
  a **packaging substitution only** (exactly the substitution this task mandates); no upstream science is
  touched. The resulting lock contains `mordredcommunity` and **no upstream `mordred` wheel**.

## Provenance

- **Upstream:** `pksmart` PyPI **v3.0.1** (`pip install pksmart`, py >=3.10,<3.12); repo
  `github.com/srijitseal/PKSmart` (Seal / Bender group); web `broad.io/PKSmart`. The RF model pickles ship
  inside the wheel; they land in the isolated env (gitignored), never in git.
- **Citation:** Seal S, et al. "PKSmart." *J. Cheminformatics* 17 (2025).
  doi:10.1186/s13321-025-01066-5 (peer-reviewed; supersedes the bioRxiv 2024.02.02.578658 preprint).
- **Access tag:** CODE-PKG.
- **License:** upstream code is open (CODE-PKG); mordred descriptors via mordredcommunity. Exact upstream
  license: see `srijitseal/PKSmart`.
- **Quirks:** CL is ranking-only (R^2=0.31) - surface the fold-error, never the bare CL; the in-memory
  DataFrame column names differ from the repo's external-test CSV names (read live, not from the CSV
  template); pksmart exposes no `__version__` (version read via `importlib.metadata`); upstream is chatty
  (loguru + tabulate) so the adapter silences logging to keep stdout clean.

## Smoke

```
pixi run --manifest-path pixi.toml python run.py \
  --input ../../../tests/fixtures/fto43.smi --output /tmp/pksmart.out.json
```

yields finite `CL_mL_min_kg` / `VDss_L_kg` / `t_half_h` / `fu` / `MRT_h` and a populated CL fold-error for
the FTO-43 fixture. `tests/test_model_pksmart.py` (`@pytest.mark.model`) drives this on the box and
validates the output against `core.schemas`.
