# t10-model-rdkit_crippen - walking skeleton + the canonical model-folder template

**Kind:** model-rule · **Autonomy:** review · **Runs:** author on laptop; env + smoke on the box
**Touch only:** `endpoints/lipophilicity/rdkit_crippen/**`, `endpoints/lipophilicity/__init__.py`,
`tests/test_model_rdkit_crippen.py`
**Deps:** t09-gate-core

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §20 (RDKit Crippen I/O).
- `docs/FTO_ADMET_Codebase_And_Environment_SETTLED.md` §3 (folder layout), §6 (adapter contract), §9 (lock on box).
- `CLAUDE.md` §0 (lock-on-box), §2 (uniform CLI), §5 (done + no-fabricate).

## Why this task is special
It is the **walking skeleton**: the first model built end-to-end, and the **template every later model
copies**. Get the folder shape, the `run.py` CLI, and the `OutputRecord` mapping exactly right here - later
model specs will say "follow the t10 pattern." The model itself is trivial (pure RDKit, no weights, no GPU),
so all the effort goes into the contract, not the science.

## Canonical model-folder layout (this is the template)
```
endpoints/lipophilicity/rdkit_crippen/
├── pixi.toml # isolated env INTENT (channels + deps)
├── pixi.lock # exact resolved env - SOLVED ON THE BOX, committed
├── run.py # uniform CLI adapter (below)
├── vendor/ # upstream code, unmodified - OMIT when there is none (pure RDKit here)
└── README.md # provenance: upstream, citation, access tag, license, quirks, direction/units
```

## Uniform adapter contract (`run.py`) - every model implements exactly this CLI
- `python run.py --input <path> --output <path> [--gpu N]`.
- `--input`: reads the pipeline input (one canonical SMILES per record; accept the `InputRecord`/`.smi`
  form the core feeds). `--gpu`: ignored here (`requires_gpu=False`).
- `--output`: writes one `OutputRecord` (from `core.schemas`) per input as JSON - but `run.py` runs in the
  **model env**, which cannot import `core`. So: write plain JSON matching the `OutputRecord` shape (the
  dispatcher validates it against `core.schemas` on collection). Document the exact keys in the README.

## Build
1. `pixi.toml`: minimal env - `rdkit` (recent), `python`. `pixi install` **on the box**; commit `pixi.lock`.
2. `run.py`: for each input SMILES → RDKit mol → `Chem.Crippen.MolLogP(mol)` (Wildman-Crippen logP, log
   units, **↑ = more lipophilic**) and `Chem.Crippen.MolMR(mol)` (molar refractivity). Emit
   `endpoint_values = {"logP_crippen": <float>, "MR": <float>}`, `uncertainty = None` (deterministic),
   `raw = {...}`, `provenance = {...}`. Invalid SMILES → a per-record error object, not a crash.
3. `endpoints/lipophilicity/__init__.py` so the endpoint is importable (aggregator comes later in t40).
4. `tests/test_model_rdkit_crippen.py` marked `@pytest.mark.model`: runs the adapter (on the box env)
   against the **FTO-43 fixture** and asserts a finite `logP_crippen` float of plausible sign/magnitude
   (do **not** hard-code an exact value - assert finite + within a wide sane band, e.g. -2..8).
5. `README.md`: this is the SwissADME **WLOGP lens** (reused by t27 SwissADME reconstruction and t16
   BOILED-Egg). Note **logP ≠ logD** for the di-basic FTO series (F-12) - this emits logP; logD conversion
   happens downstream with a pKa. Access tag CODE-PKG; license RDKit (BSD).

## Landmines
- **Lock solved on the box**, committed from laptop - never a laptop/macOS-solved lock (`CLAUDE.md` §0).
- `run.py` **cannot import `core`** (separate env) - emit JSON matching the schema; dispatcher validates.
- This is logP (the WLOGP lens), not logD. Do not silently apply a pKa here.
- FTO-43 fixture must be a **single canonical neutral parent** pending the F-16 decision - do not invent a
  protonation state.

## Done (gate: model kind - folder complete, lock box-solved, smoke ok)
- `endpoints/lipophilicity/rdkit_crippen/{pixi.toml,pixi.lock,run.py,README.md}` exist; `pixi.lock` has a
  `linux-64` section with real hashes (box-solved).
- `run.py` honors `--input/--output`; smoke test on the box yields a finite `logP_crippen` (+ `MR`) for
  FTO-43 in a sane band; `.result.json` records `smoke.ok=true`.
- README documents keys, direction (↑=more lipophilic), units (log), the WLOGP-lens role, and F-12 note.

## Blocked if
- `pixi install` cannot resolve `rdkit` on the box after 3 attempts → BLOCK with the exact solver error
  (unlikely for RDKit; if this blocks, the box env config from t00 is wrong).
