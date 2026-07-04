# t04-core-registry - `core/registry.py` (`ModelSpec` frozen dataclass + `REGISTRY`)

**Kind:** core · **Autonomy:** review · **Runs:** laptop, core env, no GPU
**Touch only:** `core/registry.py`, `tests/test_registry.py`
**Deps:** t02-core-models, t03-core-schemas

## Read first
- `CLAUDE.md` §2 (`ModelSpec` fields, cross-cutting = endpoints is a **set**), §4 (dropped models).
- `docs/FTO_ADMET_Codebase_And_Environment_SETTLED.md` §5 (model×endpoint table: bulk/gpu/access), §6 (contract).
- `docs/FTO_ADMET_Model_IO_SPEC.md` §2 (which endpoints' aggregators consume each model - the source of the endpoint **sets**).

## Build
1. **`ModelSpec`** (frozen dataclass): `name: ModelName`, `endpoints: frozenset[Endpoint]`,
   `env_manifest: Path | None` (path to the model's `pixi.toml`; `None` for web-only / out-of-band-runtime
   models), `entrypoint: Path | None` (`run.py`), `input_schema`, `output_schema`, `requires_gpu: bool`,
   `in_bulk_loop: bool`, `provenance: Provenance` (`upstream_commit`, `citation`, `access_tag`, `license`).
2. **`REGISTRY: dict[ModelName, ModelSpec]`** - one entry per `ModelName`, curated. Folder paths follow
   `endpoints/<home_endpoint>/<model>/`. Paths need not exist yet (folders are built later); web-only and
   out-of-band models have `env_manifest = entrypoint = None`. Schemas may reference the `OutputRecord`
   base for now (per-model subclasses land with each model).
3. Provide `registry_validate()` used by the core gate.

### Authoritative spec table (home endpoint · bulk · gpu · access · env?)
Singles (endpoints = {home}) unless marked cross-cutting below.

| model | home | bulk | gpu | access | env_manifest |
|---|---|---|---|---|---|
| admet_ai | triage | yes | opt | CODE-PKG | pixi (**cross-cutting**) |
| admetlab3 | triage | yes | no | CODE-API | pixi http-client (**cross-cutting**) |
| openadmet | triage | yes | opt | CODE-PKG | pixi |
| bayesherg | herg | yes | yes | CODE-PKG | pixi (legacy) |
| cardiotox_net | herg | yes | yes | CODE-PKG | pixi (legacy) |
| ctoxpred2 | herg | no | opt | CODE-PKG | pixi |
| cardiogenai | herg | no | yes | CODE-PKG | pixi |
| smartcyp | metabolism | yes | no | CODE-PKG | pixi (RDKit, **no jvm**) |
| fame3r | metabolism | yes | no | CODE-PKG | pixi |
| watanabe_renal | clearance | no | no | WEB-ONLY | **None** |
| pksmart | clearance | yes | opt | CODE-PKG | pixi |
| pbpk | clearance | no | no | CODE (R/.NET) | **None** (out-of-band) |
| bbb_score | distribution | yes | no | CODE-ALGO | pixi |
| boiled_egg | distribution | yes | no | CODE-ALGO | pixi (**cross-cutting**) |
| cns_mpo | distribution | yes | no | CODE-ALGO | pixi |
| pgp | distribution | yes | opt | CODE | pixi (**cross-cutting**) |
| watanabe_pgp_brain | distribution | no | no | WEB-ONLY | **None** |
| ochem_ppb | ppb | yes | no | CODE-API | pixi http-client |
| sfi | solubility | yes | no | CODE-ALGO | pixi |
| rdkit_crippen | lipophilicity | yes | no | CODE-PKG | pixi |
| opera | lipophilicity | yes | no | CODE-STANDALONE | **None** (MATLAB/Java out-of-band) (**cross-cutting**) |
| swissadme | lipophilicity | yes | no | WEB-SUBSTITUTABLE | pixi (code recon) |
| pains_brenk | structural_alerts | yes | no | CODE-PKG | pixi |
| sascore | synthesizability | yes | no | CODE-PKG | pixi |
| rascore | synthesizability | yes | opt | CODE-PKG | pixi (legacy) |
| aizynthfinder | synthesizability | no | opt | CODE-PKG | pixi |
| toxicophores | toxicity | yes | no | CODE-PKG | pixi |
| protox | toxicity | no | no | WEB-ONLY | **None** |
| lipinski_veber_qed | druglikeness | yes | no | CODE-PKG | pixi |

### Cross-cutting endpoint sets (from IO_SPEC §2 - use these exactly, not just the home)
- **admet_ai:** `{triage, herg, metabolism, clearance, ppb, solubility, lipophilicity, permeability, distribution, toxicity}`
- **admetlab3:** `{triage, herg, metabolism, distribution, ppb, toxicity, permeability}`
- **boiled_egg:** `{distribution, permeability}`
- **opera:** `{lipophilicity, clearance, ppb}` (LogD/pKa home; Clint→clearance cross-check; FuB→ppb)
- **pgp:** `{distribution, permeability}`

## Landmines
- **`endpoints` is a `frozenset`.** Aggregators query the registry by endpoint membership, never by folder.
- **29 entries, exactly.** No `deephit`/`spielvogel`/`cardiodpi`/`fame3`.
- Web-only + OPERA + PBPK have `env_manifest=None` (they never enter the bulk `pixi run` path).

## Done (gate: `pixi run pytest tests/test_registry.py -q` green)
- Every `ModelName` has exactly one `ModelSpec`; `len(REGISTRY) == 29`.
- Every spec's `endpoints ⊆ Endpoint` and non-empty; the 5 cross-cutting sets match above.
- `requires_gpu`/`in_bulk_loop` are set for all; provenance is non-empty (has `access_tag`).
- `ModelSpec` is immutable (frozen); mutating raises.
- `registry_validate()` returns cleanly.

## Blocked if
- Laptop-only; should not block. Record any error and BLOCK.
