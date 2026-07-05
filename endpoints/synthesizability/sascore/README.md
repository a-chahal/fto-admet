# sascore - synthetic accessibility (synthesizability)

A **CODE-PKG rule** (no weights, no GPU): the Ertl & Schuffenhauer (2009) synthetic-accessibility score
computed by the **RDKit Contrib** `sascorer.py`. It follows the t10/t18/t19 folder/adapter shape (uniform
`run.py` CLI, box-solved `pixi.lock`, `OutputRecord`-shaped JSON), and is the **first task to use the
`vendor/` slot** of the template.

## Direction - LOWER = easier to synthesize (the landmine)

`SAscore` is a float on **1-10** where **lower = easier to synthesize** and higher = harder. This
**inverts** the "higher = better" intuition, so state it explicitly anywhere the value is consumed. The
direction is carried in every record's `raw.scale.direction` and in `provenance.method` so a downstream
reader never re-derives (and never flips) it.

## First rung of the synthesizability tier ladder (docs §2 / §25)

Synthesizability is an **escalating tier**, not a single scalar (docs IO_SPEC §2). The three rungs have
different scales and are reported as a tier/flag, never averaged:

```
SAscore (1-10, lower = easier)  ->  RAscore (P route findable)  ->  AiZynthFinder (solved bool + routes)
```

`sascore` is **rung 1**: a fast, deterministic triage screen. The synthesizability aggregator (t48)
consumes it as the first rung of that ladder. This adapter emits only the raw score; no tier/promotion
logic lives here.

## The field and its direction (docs §25)

| Field | Type | Meaning | Direction |
| --- | --- | --- | --- |
| `SAscore` | float 1-10 | `sascorer.calculateScore(mol)`, fragment-contribution complexity score | **lower = easier to synthesize** |

## Vendored files (the `vendor/` slot)

`sascorer.py` + `fpscores.pkl.gz` are **RDKit Contrib, not part of the importable `rdkit` package** -
they ship under `$RDBASE/Contrib/SA_Score/`. Both are **vendored** into `vendor/`:

- `vendor/sascorer.py` - `calculateScore(mol)` + `readFragmentScores()`.
- `vendor/fpscores.pkl.gz` - the fragment-score lookup table `sascorer` reads.

`run.py` prepends `vendor/` to `sys.path` and does `import sascorer`; `sascorer.readFragmentScores()`
loads `fpscores.pkl.gz` from its own `__file__` directory (i.e. this same `vendor/`), so the two files
must travel together. Both were copied from the **box-solved RDKit 2026.03.3** build
(`share/RDKit/Contrib/SA_Score/`), the same build pinned by `pixi.lock`; the version is also recorded per
run in `provenance.rdkit_version`.

## Output contract (the JSON keys the dispatcher validates)

`run.py` runs in this model's isolated env and cannot import `core`, so it writes plain JSON matching
`core.schemas.OutputRecord`. One input record -> one output object; a JSON array or `.smi` in -> a JSON
array out. Each record:

```json
{
  "model": "sascore",
  "endpoint_values": { "SAscore": 1.51 },
  "uncertainty": null,
  "raw": {
    "smiles": "...", "mol_id": "...",
    "scale": { "min": 1.0, "max": 10.0, "direction": "lower = easier to synthesize" },
    "tier": "synthesizability rung 1 of 3 (SAscore -> RAscore -> AiZynthFinder)"
  },
  "provenance": { "model": "sascore", "method": "...", "rdkit_version": "...", "citation": "...", "license": "..." }
}
```

- **`SAscore`** (float 1-10) - `sascorer.calculateScore(mol)`; lower = easier to synthesize.
- **`uncertainty`** is `null`: the score is a deterministic function of the molecular graph.
- **Invalid or empty SMILES** -> a valid record with `SAscore` `null` and the reason in `raw.error`. The
  adapter does not crash, so one bad molecule never sinks a bulk batch.

## Uniform CLI

```
python run.py --input <path> --output <path> [--gpu N]
```

`--gpu` is accepted and **ignored** (`requires_gpu=False`); it exists only so the dispatcher can build one
command for every model. This is a pure CPU fragment-score lookup.

## Provenance

- **Upstream:** RDKit Contrib `SA_Score` (`sascorer.py` + `fpscores.pkl.gz`), **vendored** from
  `$RDBASE/Contrib/SA_Score/` of the box-solved **RDKit 2026.03.3** conda-forge build (`py311`). Not
  pip-installable: the Contrib tree is not part of the importable `rdkit` package, hence the `vendor/`
  copy.
- **Citation:** Ertl P, Schuffenhauer A. Estimation of synthetic accessibility score of drug-like
  molecules based on molecular complexity and fragment contributions. J Cheminform 2009, 1:8.
- **Access tag:** CODE-PKG (RDKit Contrib).
- **License:** BSD-3-Clause (RDKit / RDKit Contrib).
- **Quirks:** `SAscore` direction is **inverted** (lower = easier, not higher = better). `sascorer.py`
  loads `fpscores.pkl.gz` relative to its own file, so the two vendored files must stay together.
  `calculateScore` returns `None` for a 0-atom mol; `MolFromSmiles` returns `None` on unparseable input
  (both handled as a per-record error, not a raise).

## Consistency check (unit test)

`tests/test_model_sascore.py` (`@pytest.mark.model`) runs on the box and, besides the FTO-43 smoke,
pins: (1) **type + range** - `SAscore` a finite float in [1, 10]; (2) a **direction sanity check** -
a trivial molecule (ethanol) scores below a stereochemically dense fused-ring scaffold (a morphinan-like
polycycle), proving the score tracks complexity in the documented direction (lower = easier) and is not
stubbed.

## Environment / lock

`pixi.toml` is intent (conda-forge: `python 3.11.*`, `rdkit`). `pixi.lock` is **solved on the box** (Linux
+ conda-forge, RDKit 2026.03.3) and committed; it carries a real `linux-64` section with package hashes.
macOS cannot resolve the per-model env, so `platforms = ["linux-64"]`. The vendored Contrib files come
from this same build.

## Smoke

```
pixi run --manifest-path pixi.toml python run.py \
  --input ../../../tests/fixtures/fto43.smi --output /tmp/sascore.out.json
```

yields the `SAscore` field for the FTO-43 fixture. Verified on the box (RDKit 2026.03.3): the FTO-43
placeholder returns `SAscore` 1.51 (finite, in [1, 10]); ethanol (1.98) scores below a morphinan-like
polycycle (5.27), confirming the lower = easier direction. `tests/test_model_sascore.py` drives this on
the box and validates the output against `core.schemas`.
