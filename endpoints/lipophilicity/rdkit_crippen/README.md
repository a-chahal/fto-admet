# rdkit_crippen - Wildman-Crippen logP / MR (lipophilicity)

The **walking-skeleton model**: the first adapter built end to end and the **template every later model
copies**. The science is trivial (pure RDKit, no weights, no GPU); the point is the folder shape, the
uniform `run.py` CLI, and the `OutputRecord` mapping. Later model tasks say "follow the t10 pattern".

## Role: the SwissADME WLOGP lens

`rdkit.Chem.Crippen.MolLogP` is the Wildman-Crippen atom-contribution logP - this is **exactly
SwissADME's WLOGP lens**. It is reused by:
- the SwissADME reconstruction (t27), whose in-code consensus is the mean of the reproducible lenses
  (WLOGP / MLOGP / XLOGP3), and
- BOILED-Egg (t16), whose point-in-polygon test lives in (x = TPSA, y = WLOGP) space.

So this adapter is a shared building block, not just a standalone lipophilicity number.

## Output contract (the JSON keys the dispatcher validates)

`run.py` runs in this model's isolated env and cannot import `core`, so it writes plain JSON matching
`core.schemas.OutputRecord`. One input record -> one output object; a JSON array or `.smi` in -> a JSON
array out. Each record:

```json
{
  "model": "rdkit_crippen",
  "endpoint_values": { "logP_crippen": 0.09, "MR": 12.9 },
  "uncertainty": null,
  "raw": { "smiles": "...", "mol_id": "...", "logP_crippen": 0.09, "MR": 12.9 },
  "provenance": { "model": "rdkit_crippen", "method": "...", "rdkit_version": "...", "citation": "...", "license": "..." }
}
```

- **`logP_crippen`** - Wildman-Crippen logP. **Units:** log10 (dimensionless log units).
  **Direction: UP = more lipophilic.**
- **`MR`** - molar refractivity (`Chem.Crippen.MolMR`), a size/polarizability descriptor.
- **`uncertainty`** is `null`: the descriptor is deterministic, there is no native AD/uncertainty signal.
- **Invalid or empty SMILES** -> a valid record with `endpoint_values` null and the reason in `raw`
  (`raw.error`). The adapter does not crash, so one bad molecule never sinks a bulk batch.

## logP is NOT logD (flag F-12)

This emits **logP**, not logD. For the di-basic FTO series (F-16 di-cation) the logD conversion needs a
pKa and is done **downstream** with the single shared pKa source (F-13), never silently applied here.
Do not add a pKa or a protonation state in this adapter.

## Uniform CLI

```
python run.py --input <path> --output <path> [--gpu N]
```

`--gpu` is accepted and **ignored** (`requires_gpu=False`); it exists only so the dispatcher can build
one command for every model.

## Provenance

- **Upstream:** RDKit `rdkit.Chem.Crippen` (`MolLogP`, `MolMR`). Not a vendored third-party repo - it is
  a first-class RDKit module, so there is no `vendor/` folder. Exact RDKit version is recorded per run in
  `provenance.rdkit_version` (read live from `rdkit.rdBase.rdkitVersion`) and pinned by `pixi.lock`.
- **Citation:** Wildman SA, Crippen GM. "Prediction of Physicochemical Parameters by Atomic
  Contributions." J Chem Inf Comput Sci 1999, 39(5):868-873.
- **Access tag:** CODE-PKG.
- **License:** BSD-3-Clause (RDKit).
- **Quirks:** logP != logD (F-12, above); `MolLogP`/`MolMR` are deterministic (no uncertainty);
  `MolFromSmiles` returns `None` on unparseable input (handled as a per-record error, not a raise).

## Environment / lock

`pixi.toml` is intent (conda-forge: `python 3.11.*`, `rdkit`). `pixi.lock` is **solved on the box**
(Linux + conda-forge) and committed; it carries a real `linux-64` section with package hashes. macOS
cannot resolve the per-model env, so `platforms = ["linux-64"]`.

## Smoke

```
pixi run --manifest-path pixi.toml python run.py \
  --input ../../../tests/fixtures/fto43.smi --output /tmp/rdkit_crippen.out.json
```

yields a finite `logP_crippen` (and `MR`) for the FTO-43 fixture. `tests/test_model_rdkit_crippen.py`
(`@pytest.mark.model`) drives this on the box and validates the output against `core.schemas`.
