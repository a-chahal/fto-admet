# pains_brenk - PAINS + BRENK structural alerts (structural_alerts)

A **CODE-PKG rule** (no weights, no GPU): two substructure-alert screens run from **RDKit's built-in
`FilterCatalog`**. It follows the t10/t16 folder/adapter shape (uniform `run.py` CLI, box-solved
`pixi.lock`, `OutputRecord`-shaped JSON).

- **PAINS** (Baell & Holloway 2010): `FilterCatalogParams.FilterCatalogs.PAINS`, which is the **union of
  the three published sub-catalogs A / B / C**. Pan-Assay INterference compoundS - substructures that
  recur as false positives across many assays.
- **BRENK** (Brenk et al. 2008): `FilterCatalogParams.FilterCatalogs.BRENK` - unwanted / reactive
  functionality to strip from lead-like screening libraries.

Both alert SMARTS **ship inside RDKit** (there is no vendored upstream runtime), so the isolated env is
just `python` + `rdkit`, and the exact RDKit version is recorded per run in `provenance.rdkit_version`
and pinned by `pixi.lock`.

## Soft filter: look-closer, NOT auto-kill (the landmine)

Structural alerts, PAINS especially, **over-flag**. A hit is a **prompt to look closer**, never an
automatic disqualification. This matters concretely for this program because the **FTO biochemical assay
is fluorescence-based**: PAINS is enriched for assay-interfering scaffolds (fluorescent, redox-cycling,
aggregators, reactive), so a PAINS hit on an FTO-series member is a flag to **check for readout
interference** in that specific assay, not a reason to drop the compound. Many marketed drugs carry PAINS
or BRENK substructures. This adapter only emits the raw counts / flags / matched substructures; the
consuming policy (the structural_alerts aggregator) is downstream.

**Direction: more alerts = more flagged.** (Both `*_count` fields increase with more matches; both
`*_hit` booleans are `count > 0`.)

## Output contract (the JSON keys the dispatcher validates)

`run.py` runs in this model's isolated env and cannot import `core`, so it writes plain JSON matching
`core.schemas.OutputRecord`. One input record -> one output object; a JSON array or `.smi` in -> a JSON
array out. Each record:

```json
{
  "model": "pains_brenk",
  "endpoint_values": { "PAINS_hit": false, "PAINS_count": 0, "BRENK_hit": true, "BRENK_count": 1 },
  "uncertainty": null,
  "raw": {
    "smiles": "...", "mol_id": "...",
    "PAINS_matches": [ { "name": "quinone_A(370)", "atoms": [3, 4, 5, 6, 7, 8] } ],
    "BRENK_matches": [ { "name": "nitro_group", "atoms": [0, 1, 2] } ],
    "soft_filter": true
  },
  "provenance": { "model": "pains_brenk", "method": "...", "rdkit_version": "...", "citation": "...", "license": "..." }
}
```

- **`PAINS_hit`** (bool) / **`PAINS_count`** (int) - the PAINS A/B/C union catalog.
- **`BRENK_hit`** (bool) / **`BRENK_count`** (int) - the BRENK unwanted-functionality catalog.
- Per catalog the **matched filter entries** (each entry's descriptive `name`) and the **matched-atom
  substructure** (`atoms`: the molecule atom indices that triggered each alert, deduplicated + sorted)
  land in `raw` (non-scalar, so they live in `raw`, not `endpoint_values`, per the schema note). The
  matched atoms make each alert auditable / reconstructible.
- **`uncertainty`** is `null`: the rule is deterministic.
- **Invalid or empty SMILES** -> a valid record with the four endpoint values `null` and the reason in
  `raw` (`raw.error`). The adapter does not crash, so one bad molecule never sinks a bulk batch.

## Uniform CLI

```
python run.py --input <path> --output <path> [--gpu N]
```

`--gpu` is accepted and **ignored** (`requires_gpu=False`); it exists only so the dispatcher can build one
command for every model. PAINS/BRENK is pure CPU substructure matching.

## Provenance

- **Upstream:** RDKit's built-in `FilterCatalog` (`FilterCatalogs.PAINS` = union of A/B/C;
  `FilterCatalogs.BRENK`). No vendored third-party runtime is imported, so there is no `vendor/` folder;
  the alert SMARTS ship with RDKit and the exact RDKit version is recorded per run in
  `provenance.rdkit_version` and pinned by `pixi.lock`.
- **Citation:** Baell JB, Holloway GA. "New Substructure Filters for Removal of Pan Assay Interference
  Compounds (PAINS) from Screening Libraries and for Their Exclusion in Bioassays." J Med Chem 2010,
  53(7):2719-2740, DOI 10.1021/jm901137j. Brenk R et al. "Lessons Learnt from Assembling Screening
  Libraries for Drug Discovery for Neglected Diseases." ChemMedChem 2008, 3(3):435-444,
  DOI 10.1002/cmdc.200700139.
- **Access tag:** CODE-PKG.
- **License:** BSD-3-Clause (RDKit; the FilterCatalog SMARTS ship with RDKit).
- **Quirks:** `FilterCatalogs.PAINS` is the **union of A/B/C** (do not add PAINS_A/B/C separately as well
  or matches double-count); a **soft filter that over-flags** - look-closer, not auto-kill, and relevant
  to the fluorescence-based FTO assay (see above); matched-atom indices come from each
  `FilterMatch.atomPairs` second element (the atom index in the query molecule); `MolFromSmiles` returns
  `None` on unparseable input (handled as a per-record error, not a raise).

## Consistency check (unit test)

`tests/test_model_pains_brenk.py` (`@pytest.mark.model`) runs on the box and, besides the FTO-43 smoke,
pins: (1) **field consistency** - each `*_hit` is `*_count > 0` and each `raw.*_matches` list length
equals its count; (2) a **known BRENK positive** (nitrobenzene -> `nitro_group`) and a **known PAINS
positive** (catechol) each flag with a named entry + matched atoms, proving the catalogs actually load
and match; (3) a **clean molecule** (ethane) trips neither catalog (both counts 0, empty lists).

## Environment / lock

`pixi.toml` is intent (conda-forge: `python 3.11.*`, `rdkit`). `pixi.lock` is **solved on the box** (Linux
+ conda-forge) and committed; it carries a real `linux-64` section with package hashes. macOS cannot
resolve the per-model env, so `platforms = ["linux-64"]`.

## Smoke

```
pixi run --manifest-path pixi.toml python run.py \
  --input ../../../tests/fixtures/fto43.smi --output /tmp/pains_brenk.out.json
```

yields the four fields (`PAINS_hit`/`PAINS_count`/`BRENK_hit`/`BRENK_count`) plus the matched lists for the
FTO-43 fixture. `tests/test_model_pains_brenk.py` drives this on the box, validates the output against
`core.schemas`, and pins the consistency + known-positive/known-negative cases.
