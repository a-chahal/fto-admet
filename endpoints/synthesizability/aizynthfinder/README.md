# aizynthfinder - AiZynthFinder retrosynthesis route search, synthesizability endpoint

AiZynthFinder (`MolecularAI/aizynthfinder`, Genheden et al., J. Cheminform. 2020) is an open-source
computer-aided synthesis planning (CASP) tool: a Monte-Carlo tree search over a neural
template-expansion policy that tries to find a synthetic route from a target molecule down to
purchasable precursors (a configured "stock"). It is a **real route search**, not a classifier.

## Role: third (top) rung of the synthesizability tier ladder

`in_bulk_loop = False`. The synthesizability tier is a **ladder**, not an average (docs IO_SPEC 1 #26 / #27 / 2):

```
SAscore (rung 1)  ->  RAscore (rung 2)  ->  AiZynthFinder (rung 3)
1-10, lower=easier    P(route findable)     real route search (is_solved bool + routes)
```

AiZynthFinder is **rung 3**, the confirmatory rung. It actually runs the MCTS retrosynthesis, so it is
expensive (a tree search per molecule) and is run on the **shortlist only** (`in_bulk_loop = False`): it
confirms the cheap upstream rungs (SAscore triage, RAscore classifier) rather than scoring the bulk
library. The rungs use different scales and are reported as a **tier, never averaged**.

| key | quantity | range / type | direction |
| --- | --- | --- | --- |
| `is_solved` | a route to purchasable precursors was found (top route) | bool | **True = solved (route found)** |
| `top_score` | score of the top-ranked route (default "state score") | 0-1 float | **UP = better route** |
| `number_of_steps` | reaction steps in the top route | int | fewer = simpler |
| `number_of_routes` | distinct routes returned | int | context |
| `number_of_precursors` | leaf precursors of the top route | int | context |
| `number_of_precursors_in_stock` | how many precursors are purchasable | int | context |
| `number_of_nodes` | nodes explored in the search tree | int | context |

The go/no-go field is `is_solved`; survivors are ranked by `top_score` and `number_of_steps`. Full route
trees (`reaction_tree` + `all_scores` + `route_metadata`, from `RouteCollection.dict_with_scores()`) and
the complete per-target `statistics` dict are kept verbatim in `raw` for the raw-output cache / audit.

## LANDMINE - the key is `is_solved`, NOT `solved` (docs IO_SPEC 1 #27 / 3 F-11)

`extract_statistics()` returns the aggregated go/no-go statistic under **`is_solved`**. There is also an
internal per-node key `solved` on the search tree; reading that instead would **silently report every
target as unsolved**. This adapter reads `stats["is_solved"]` (verified on the box against
`aizynthfinder/analysis/tree_analysis.py::TreeAnalysis._tree_statistics_mcts`, which is exactly where the
`is_solved` key is produced).

## LANDMINE - a stock set + policy model are REQUIRED (the heavy part)

AiZynthFinder cannot solve anything without a configured **stock** (purchasable building blocks) and a
downloaded **expansion policy model**. Without them every target is trivially "unsolved". These are the
public USPTO template policy + ZINC stock, fetched **once** with the upstream `download_public_data` tool
and **cached on the box, never committed** (CLAUDE.md 0: never commit weights/data - the ZINC stock alone
is ~0.65 GB).

`run.py` does **not** download at run time. It resolves an existing `config.yml`, in order:
1. `--config <path>`
2. `$AIZYNTH_CONFIG`
3. `$FTO_ADMET_ENV_CACHE/aizynth-data/config.yml` (the cached default; `FTO_ADMET_ENV_CACHE` =
   `/zfs/sanjanp/fto-admet-envs`)

If none is found it raises a loud, actionable error rather than silently reporting "unsolved".

### One-time stock + policy setup (on the box)

```
pixi run --manifest-path pixi.toml download_public_data $FTO_ADMET_ENV_CACHE/aizynth-data
```

This writes the ONNX policy models, the template files, the ZINC `zinc_stock.hdf5`, and a `config.yml`
with box-absolute paths into `$FTO_ADMET_ENV_CACHE/aizynth-data/`.

**Build note (5 Jul 2026):** at build time `download_public_data` failed midway on ONE optional file -
the **ringbreaker** template CSV returned HTTP 500 from its Zenodo host
(`zenodo.org/record/7341155/files/uspto_ringbreaker_unique_templates.csv.gz`), which aborted the tool
before it reached the ZINC stock. The essential files were fetched directly instead and a `config.yml`
was written by hand pointing at them:

```yaml
expansion:
  uspto:
    - <aizynth-data>/uspto_model.onnx
    - <aizynth-data>/uspto_templates.csv.gz
filter:
  uspto: <aizynth-data>/uspto_filter_model.onnx
stock:
  zinc: <aizynth-data>/zinc_stock.hdf5
```

The **ringbreaker** expansion policy is an *optional secondary* policy and is **not needed** for a
shortlist route search: the standard single-target search uses the `uspto` expansion policy + `zinc`
stock (the `uspto` filter policy is an optional route-feasibility filter, included here because it did
download). If the ringbreaker CSV becomes reachable again, re-running `download_public_data` restores the
full default config; the adapter reads whatever `config.yml` provides and does not require ringbreaker.

## Output contract (the JSON keys the dispatcher validates)

`run.py` runs in this model's isolated env and cannot import `core`, so it writes plain JSON matching
`core.schemas.OutputRecord`. One input record -> one output object; a JSON array or `.smi` in -> a JSON
array out. Each record:

```json
{
  "model": "aizynthfinder",
  "endpoint_values": {
    "is_solved": true, "top_score": 0.99, "number_of_steps": 2, "number_of_routes": 5,
    "number_of_precursors": 3, "number_of_precursors_in_stock": 3, "number_of_nodes": 42
  },
  "uncertainty": null,
  "raw": {
    "smiles": "...", "mol_id": "...",
    "statistics": { "...": "full extract_statistics() dict" },
    "routes": [ { "...": "reaction_tree + all_scores + route_metadata per route" } ],
    "scale": { "top_score": { "min": 0.0, "max": 1.0, "direction": "higher = better route (default state score)" },
               "is_solved": "True = a route to purchasable precursors was found" },
    "tier": "synthesizability rung 3 of 3 (SAscore -> RAscore -> AiZynthFinder); shortlist only"
  },
  "provenance": { "model": "aizynthfinder", "expansion_policy": "uspto", "stock": "zinc",
                  "aizynthfinder_version": "4.4.1", "rdkit_version": "...", "config": "...",
                  "citation": "...", "license": "MIT ..." }
}
```

`uncertainty` is `null`: a route search emits no native aleatoric/epistemic signal (the reserved schema
fields stay null rather than fabricated, per CLAUDE.md 3).

### Invalid input

An empty / RDKit-unparseable SMILES -> a valid record with `is_solved` / `top_score` null and the reason
in `raw.error`. The adapter does not crash, so one bad molecule never sinks a batch.

## Uniform CLI

```
python run.py --input <path> --output <path> [--gpu N] [--config <config.yml>]
```

`--gpu` is accepted and **ignored** (`requires_gpu = False`): the shipped ONNX policy runs on
onnxruntime (CPU). It exists only so the dispatcher can build one command for every model.

## Environment / install

AiZynthFinder is **PyPI-only** (`pip install aizynthfinder`); it is **not on conda-forge** (verified on
the box, 5 Jul 2026). So `pixi.toml` uses a conda-forge python 3.11 base (aizynthfinder 4.x requires
`>=3.9,<3.12`) with `aizynthfinder` as a **pypi-dependency**, which brings rdkit, onnxruntime, pandas,
numpy, pyyaml. `pixi.toml` is intent; `pixi.lock` is **solved on the box** (Linux, conda-forge + PyPI)
and committed, carrying a real `linux-64` section with package hashes. `platforms = ["linux-64"]` because
macOS cannot resolve the per-model env (onnxruntime linux wheels).

The stock + policy models are **NOT committed** (CLAUDE.md 0): they are cached on the box under
`$FTO_ADMET_ENV_CACHE/aizynth-data/` (see the one-time setup above) and ignored via `.gitignore`.

## Provenance

- **Upstream:** `github.com/MolecularAI/aizynthfinder` (AstraZeneca MolecularAI). Installed release
  `aizynthfinder == 4.4.1`.
- **Citation:** Genheden S, Thakkar A, Chadimova V, Reymond J-L, Engkvist O, Bjerrum E. "AiZynthFinder:
  a fast, robust and flexible open-source software for retrosynthetic planning." *J. Cheminform.* 12:70
  (2020). doi:10.1186/s13321-020-00472-1.
- **Access tag:** CODE-PKG.
- **License:** MIT (`MolecularAI/aizynthfinder`). Public USPTO expansion policy + ZINC stock.
- **Quirks:** the go/no-go key is `is_solved`, not `solved` (the internal per-node key); a stock + policy
  model are required and are cached on the box (~0.8 GB), never committed; the `download_public_data`
  ringbreaker template CSV 500'd at build time (optional, not needed for the shortlist search).

## Smoke

```
pixi run --manifest-path pixi.toml python run.py \
  --input ../../../tests/fixtures/fto43.smi --output /tmp/aizynthfinder.out.json
```

with `$FTO_ADMET_ENV_CACHE/aizynth-data/config.yml` present yields a record with a real `is_solved` bool
and a finite `top_score` in `[0, 1]` for the FTO-43 fixture. `tests/test_model_aizynthfinder.py`
(`@pytest.mark.model`) drives this on the box and validates the output against `core.schemas`.
