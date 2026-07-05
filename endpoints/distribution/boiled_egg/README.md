# boiled_egg - BOILED-Egg (distribution BBB + permeability HIA)

A **CODE-ALGO rule** (no weights, no GPU): the **BOILED-Egg** (Daina & Zoete, ChemMedChem 2016), a
point-in-polygon screen that predicts passive gastro-intestinal absorption (**HIA**) and passive
blood-brain-barrier penetration (**BBB**) from two RDKit descriptors. It follows the t10/t14/t15
folder/adapter shape (uniform `run.py` CLI, box-solved `pixi.lock`, `OutputRecord`-shaped JSON).

## Role: ONE implementation, TWO endpoints

BOILED-Egg is a cross-cutting model: this single adapter feeds **both** endpoints (registry, t04:
`ModelSpec.endpoints = {distribution, permeability}`). The aggregators query the registry **by endpoint,
not by folder**, so the same record's two booleans land where each belongs:

- **`BBB_boiled_egg`** -> the **distribution** endpoint (passive brain penetration).
- **`HIA_boiled_egg`** -> the **permeability** endpoint (passive GI absorption).

## Mechanism: point-in-polygon in (x = TPSA, y = WLOGP) space

The "egg" is two closed regions in a 2-D physicochemical plane:

```
white region ("egg white") -> HIA  (passive GI absorption); True = absorbed
yolk  region ("egg yolk")  -> BBB  (passive brain penetration); True = permeant
```

Membership is a **point-in-polygon** test (NOT an inequality on one axis). The **yolk is the more
restrictive INNER region** (TPSA up to ~79, WLOGP ~0.4..6.0); the **white extends much further in TPSA**
(to ~142). So one molecule can be in the white but not the yolk (absorbed, not brain-penetrant), in both,
or in neither. Because the yolk lies inside the white, `BBB=True` implies `HIA=True`.

### Coordinate convention is load-bearing (F-9, the landmine)

**TPSA on x, WLOGP on y.** Swapping the axes silently inverts every call. The region vertices in
`regions.json` are stored as `[tpsa, wlogp]` and `run.py` feeds the membership test in that order. The
unit test pins this: a molecule known to sit in the yolk (diazepam) must return `BBB=True`; a swap would
flip it to `False`.

## Descriptors: the same WLOGP as t10, and TPSA with S and P (matches the original model)

| Field | RDKit call | Note |
|-------|-----------|------|
| WLOGP | `Crippen.MolLogP` (Wildman-Crippen 1999) | The **same lens as t10 rdkit_crippen**, not a different logP. RDKit names it `MolLogP`; the BOILED-Egg paper calls the descriptor WLOGP. |
| TPSA | `CalcTPSA(mol, includeSandP=True)` | **S and P contributions included.** The original BOILED-Egg was fit against TPSA-with-S-and-P, so the ellipse boundaries are only correct for that variant. RDKit's DEFAULT excludes S and P and would shift x for any S/P-containing molecule, silently misplacing it relative to the boundary. |

The `includeSandP=True` choice is verified from the reference implementation (`pyBOILEDegg` uses
`Descriptors.TPSA(m, includeSandP=True)` with the comment "used in the original BOILED-egg model").

## Region boundaries (`regions.json`)

The two ~100-vertex polygons are the **verbatim `gia_coords` (white/HIA) and `bbb_coords` (yolk/BBB)**
vertex lists from `bfmilne/pyBOILEDegg`, which trace the Daina & Zoete 2016 supporting-information
ellipses. They were **fetched and validated on the box**: point count (101 each, closed), and TPSA/WLOGP
extents match the published bounds - white TPSA `[0.02, 142.03]`, yolk TPSA `[-2.96, 79.10]`,
yolk WLOGP `[0.41, 5.96]`. Membership uses a self-contained **ray-casting** point-in-polygon test in
`run.py`, so the isolated env needs **only rdkit** (no shapely).

## Output contract (the JSON keys the dispatcher validates)

`run.py` runs in this model's isolated env and cannot import `core`, so it writes plain JSON matching
`core.schemas.OutputRecord`. One input record -> one output object; a JSON array or `.smi` in -> a JSON
array out. Each record:

```json
{
  "model": "boiled_egg",
  "endpoint_values": { "HIA_boiled_egg": true, "BBB_boiled_egg": false },
  "uncertainty": null,
  "raw": {
    "smiles": "...", "mol_id": "...",
    "WLOGP": 2.31, "TPSA": 84.4, "tpsa_includes_s_and_p": true,
    "in_white_gia": true, "in_yolk_bbb": false
  },
  "provenance": { "model": "boiled_egg", "method": "...", "rdkit_version": "...", "citation": "...", "license": "..." }
}
```

- **`HIA_boiled_egg`** (boolean) - **permeability** endpoint. **Direction: True = passively GI-absorbed.**
- **`BBB_boiled_egg`** (boolean) - **distribution** endpoint. **Direction: True = passively brain-penetrant.**
- The `(TPSA, WLOGP)` coordinates are echoed in `raw` for audit, so the point-in-polygon decision is
  reconstructible.
- **`uncertainty`** is `null`: the rule is deterministic.
- **Invalid or empty SMILES** -> a valid record with both endpoint values `null` and the reason in
  `raw` (`raw.error`). The adapter does not crash, so one bad molecule never sinks a bulk batch.

### A coarse passive screen, reconciled downstream (F-4)

BOILED-Egg is a **coarse passive-permeability screen**. On the distribution side its `BBB_boiled_egg`
boolean is **one signal among incompatible scales** (BBB Score 0-6, CNS MPO 0-6, BBB_Martins probability),
reconciled **ordinally, never averaged** (F-4). Do not gate on it alone.

## Uniform CLI

```
python run.py --input <path> --output <path> [--gpu N]
```

`--gpu` is accepted and **ignored** (`requires_gpu=False`); it exists only so the dispatcher can build one
command for every model. BOILED-Egg is pure CPU geometry.

## Provenance

- **Upstream:** the BOILED-Egg model (Daina & Zoete). Reimplemented here in pure RDKit (`Crippen.MolLogP`,
  `rdMolDescriptors.CalcTPSA`) plus a self-contained ray-casting point-in-polygon test; the region vertices
  are the `pyBOILEDegg` `gia_coords`/`bbb_coords` lists (verbatim, in `regions.json`). No vendored
  third-party runtime is imported, so there is no `vendor/` folder; the exact RDKit version is recorded per
  run in `provenance.rdkit_version` and pinned by `pixi.lock`.
- **Citation:** Daina A, Zoete V. "A BOILED-Egg To Predict Gastrointestinal Absorption and Brain
  Penetration of Small Molecules." ChemMedChem 2016, 11(11):1117-1121, DOI 10.1002/cmdc.201600182
  (open access). Reference implementation / vertex lists: `github.com/bfmilne/pyBOILEDegg`
  (`PyBOILEDegg.py`, fetched 4 Jul 2026).
- **Access tag:** CODE-ALGO.
- **License:** BSD-3-Clause (RDKit). The boundary vertices originate from `pyBOILEDegg` (GPL-3.0) and trace
  the open-access Daina & Zoete 2016 model data; recorded here in `provenance.license`.
- **Quirks:** axis convention is **TPSA on x, WLOGP on y** (swap inverts every call); WLOGP is the t10
  Crippen `MolLogP` (not a different logP); TPSA **includes S and P** (`includeSandP=True`) to match the
  original model; the **yolk is inside the white** so `BBB=True` implies `HIA=True`; a coarse passive
  screen, **not a gate** (reconciled ordinally at the distribution aggregator, F-4); `MolFromSmiles`
  returns `None` on unparseable input (handled as a per-record error, not a raise).

## Consistency check (unit test)

`tests/test_model_boiled_egg.py` (`@pytest.mark.model`) runs on the box and, besides the FTO-43 smoke,
pins the **axis convention** (F-9): a known in-yolk molecule (diazepam) returns `BBB=True`; a molecule
inside the white but past the yolk's TPSA reach (metronidazole) returns `HIA=True, BBB=False`; a large
very-polar molecule (sucrose) returns both `False`. A swapped axis or inverted region would fail these.

## Environment / lock

`pixi.toml` is intent (conda-forge: `python 3.11.*`, `rdkit`). `pixi.lock` is **solved on the box** (Linux
+ conda-forge) and committed; it carries a real `linux-64` section with package hashes. macOS cannot
resolve the per-model env, so `platforms = ["linux-64"]`.

## Smoke

```
pixi run --manifest-path pixi.toml python run.py \
  --input ../../../tests/fixtures/fto43.smi --output /tmp/boiled_egg.out.json
```

yields two booleans for the FTO-43 fixture. `tests/test_model_boiled_egg.py` drives this on the box,
validates the output against `core.schemas`, and pins the axis convention.
