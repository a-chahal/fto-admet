# toxicophores - toxicity structural alerts (toxicity)

A **CODE-PKG rule** (no weights, no GPU): a single structural-alert screen run from **RDKit's built-in
`FilterCatalog`**. It follows the t10/t16/t17 folder/adapter shape (uniform `run.py` CLI, box-solved
`pixi.lock`, `OutputRecord`-shaped JSON).

## The single chosen catalog: BRENK (and why one is documented)

"toxicophores" is **not one canonical RDKit catalog** (docs IO_SPEC §28, Provenance §B#30): RDKit's
`FilterCatalog` ships several alert sets (PAINS A/B/C, BRENK, NIH, ChEMBL sub-catalogs). The task
requires picking and documenting **exactly one** source. This adapter uses:

- **BRENK** (Brenk et al. 2008): `FilterCatalogParams.FilterCatalogs.BRENK` - the "unwanted /
  reactive functionality" alert set (known reactive / toxic substructures to strip from lead-like
  libraries). This is the documented **default** catalog per the task and docs §28.

The chosen catalog name is the module constant `CATALOG_NAME = "BRENK"`, is emitted in every record's
`endpoint_values["catalog"]`, and is recorded in `provenance.catalog` - so a downstream reader never
guesses which alert set produced a flag. The alert SMARTS **ship inside RDKit** (there is no vendored
upstream runtime), so the isolated env is just `python` + `rdkit`, and the exact RDKit version is
recorded per run in `provenance.rdkit_version` and pinned by `pixi.lock`.

## Toxicity intent, and how this differs from t17 (the landmine)

This model serves the **`toxicity`** endpoint with a **toxicity intent**: it flags **known toxic /
reactive substructures** (toxicophores). It is **DISTINCT** from the `structural_alerts`
`pains_brenk` screen (t17) by **intent, not mechanism** (docs §28):

- **t17 `pains_brenk`** (endpoint `structural_alerts`): flags **assay-interference** (PAINS pan-assay
  interference) plus BRENK, and emits `PAINS_*` / `BRENK_*` fields.
- **t18 `toxicophores`** (endpoint `toxicity`, this model): flags **toxicity** via one documented
  toxicity alert catalog and emits a single `tox_alert_*` flag/count with the `catalog` name.

Even though the BRENK SMARTS are reused, the **endpoint, the framing, and the emitted fields differ**.
That reuse is explicitly allowed by the task; the point of this model is the toxicity endpoint and the
toxicity framing, consumed later by the toxicity aggregator (which folds these alerts together with the
ADMETlab organ-tox heads into a per-endpoint P(toxic), docs IO_SPEC §2).

## Soft filter: look-closer, NOT auto-kill

Structural alerts **over-flag**. A hit is a **prompt to look closer**, never an automatic
disqualification - many marketed drugs carry BRENK substructures. This adapter only emits the raw
count / flag / matched substructures; the consuming policy (the `toxicity` aggregator) is downstream.

**Direction: more alerts = more flagged.** (`tox_alert_count` increases with more matches;
`tox_alert_hit` is `count > 0`.)

## Output contract (the JSON keys the dispatcher validates)

`run.py` runs in this model's isolated env and cannot import `core`, so it writes plain JSON matching
`core.schemas.OutputRecord`. One input record -> one output object; a JSON array or `.smi` in -> a JSON
array out. Each record:

```json
{
  "model": "toxicophores",
  "endpoint_values": { "tox_alert_hit": true, "tox_alert_count": 1, "catalog": "BRENK" },
  "uncertainty": null,
  "raw": {
    "smiles": "...", "mol_id": "...", "catalog": "BRENK",
    "tox_alert_matches": [ { "name": "nitro_group", "atoms": [0, 1, 2] } ],
    "tox_alert_names": [ "nitro_group" ],
    "soft_filter": true, "intent": "toxicity"
  },
  "provenance": { "model": "toxicophores", "method": "...", "catalog": "BRENK", "rdkit_version": "...", "citation": "...", "license": "..." }
}
```

- **`tox_alert_hit`** (bool) - `true` iff at least one BRENK alert matched.
- **`tox_alert_count`** (int) - number of matched BRENK alerts.
- **`catalog`** (str) - the documented catalog name, always `"BRENK"`.
- The **matched alert names** land in `raw` (non-scalar, so out of `endpoint_values`, per the schema
  note): `raw.tox_alert_names` (flat list of names) and `raw.tox_alert_matches` (each entry's `name` +
  the matched-atom substructure `atoms`: the molecule atom indices that triggered the alert,
  deduplicated + sorted). The matched atoms make each alert auditable / reconstructible.
- **`uncertainty`** is `null`: the rule is deterministic.
- **Invalid or empty SMILES** -> a valid record with `tox_alert_hit` / `tox_alert_count` `null`
  (`catalog` still carried, being a constant) and the reason in `raw` (`raw.error`). The adapter does
  not crash, so one bad molecule never sinks a bulk batch.

## Uniform CLI

```
python run.py --input <path> --output <path> [--gpu N]
```

`--gpu` is accepted and **ignored** (`requires_gpu=False`); it exists only so the dispatcher can build one
command for every model. This is pure CPU substructure matching.

## Provenance

- **Upstream:** RDKit's built-in `FilterCatalog` (`FilterCatalogs.BRENK`). No vendored third-party
  runtime is imported, so there is no `vendor/` folder; the alert SMARTS ship with RDKit and the exact
  RDKit version is recorded per run in `provenance.rdkit_version` and pinned by `pixi.lock`.
- **Citation:** Brenk R, Schipani A, James D, Krasowski A, Gilbert IH, Frearson J, Wyatt PG. "Lessons
  Learnt from Assembling Screening Libraries for Drug Discovery for Neglected Diseases." ChemMedChem
  2008, 3(3):435-444, DOI 10.1002/cmdc.200700139.
- **Access tag:** CODE-PKG.
- **License:** BSD-3-Clause (RDKit; the FilterCatalog SMARTS ship with RDKit).
- **Quirks:** "toxicophores" is not one canonical RDKit catalog, so **exactly one** is chosen and
  documented (BRENK, the default); the catalog name is carried in `endpoint_values["catalog"]` and
  `provenance.catalog`. Reuses the BRENK SMARTS also used by t17, but is **distinct by intent**
  (toxicity vs assay-interference) and endpoint (`toxicity` vs `structural_alerts`) - see above. A
  **soft filter that over-flags** - look-closer, not auto-kill. Matched-atom indices come from each
  `FilterMatch.atomPairs` second element (the atom index in the query molecule). `MolFromSmiles` returns
  `None` on unparseable input (handled as a per-record error, not a raise).

## Consistency check (unit test)

`tests/test_model_toxicophores.py` (`@pytest.mark.model`) runs on the box and, besides the FTO-43 smoke,
pins: (1) **field consistency** - `tox_alert_hit` is `tox_alert_count > 0`, `catalog == "BRENK"`, and
both `raw.tox_alert_matches` / `raw.tox_alert_names` list lengths equal the count; (2) a **known BRENK
positive** (nitrobenzene -> `nitro_group`) flags with a named entry + matched atoms, proving the catalog
actually loads and matches; (3) a **clean molecule** (ethane) trips nothing (count 0, empty lists).

## Environment / lock

`pixi.toml` is intent (conda-forge: `python 3.11.*`, `rdkit`). `pixi.lock` is **solved on the box** (Linux
+ conda-forge) and committed; it carries a real `linux-64` section with package hashes. macOS cannot
resolve the per-model env, so `platforms = ["linux-64"]`.

## Smoke

```
pixi run --manifest-path pixi.toml python run.py \
  --input ../../../tests/fixtures/fto43.smi --output /tmp/toxicophores.out.json
```

yields the three fields (`tox_alert_hit` / `tox_alert_count` / `catalog`) plus the matched name list for
the FTO-43 fixture. `tests/test_model_toxicophores.py` drives this on the box, validates the output against
`core.schemas`, and pins the consistency + known-positive/known-negative cases.
