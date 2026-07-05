# sfi - Solubility Forecast Index (solubility)

A **CODE-ALGO rule** (no weights, no GPU): the Solubility Forecast Index, a fast physchem heuristic for
aqueous solubility. It follows the t10 folder/adapter shape (uniform `run.py` CLI, box-solved `pixi.lock`,
`OutputRecord`-shaped JSON) and reuses the t10 Wildman-Crippen cLogP lens inside its cLogD term.

## Role: the solubility rule lens (LOWER = better)

```
SFI = cLogD(7.4) + (#aromatic rings)        -> single float
```

Rising lipophilicity (cLogD) and rising aromatic-ring count both push a molecule toward poorer aqueous
solubility, so **a higher SFI means worse solubility and a LOWER SFI means better (more soluble)**.

### Direction: LOWER = better (landmine)

This **inverts** vs a generalist solubility model, where a higher log S = better (more soluble). Do not
average or compare SFI against a generalist log S directly. The **t41 solubility aggregator** reconciles
the two directions (co-rank ordinally / negate for co-ranking, per the IO spec's direction table); this
adapter just emits SFI faithfully with the direction stated here.

## Output contract (the JSON keys the dispatcher validates)

`run.py` runs in this model's isolated env and cannot import `core`, so it writes plain JSON matching
`core.schemas.OutputRecord`. One input record -> one output object; a JSON array or `.smi` in -> a JSON
array out. Each record:

```json
{
  "model": "sfi",
  "endpoint_values": { "SFI": -1.52, "cLogD_7.4": -1.52, "n_aromatic_rings": 0 },
  "uncertainty": null,
  "raw": {
    "smiles": "...", "mol_id": "...",
    "SFI": -1.52, "cLogD_7.4": -1.52, "cLogP_crippen": 0.09, "n_aromatic_rings": 0,
    "pka": 9.0, "pka_source": "placeholder-constant (...)", "ph": 7.4
  },
  "provenance": { "model": "sfi", "method": "...", "rdkit_version": "...", "pka": 9.0, "pka_source": "...", "citation": "...", "license": "..." }
}
```

- **`SFI`** - Solubility Forecast Index. **Units:** dimensionless. **Direction: LOWER = better (more
  soluble).**
- **`cLogD_7.4`** - the distribution coefficient at pH 7.4 used inside SFI (see F-12 below).
- **`n_aromatic_rings`** - `rdkit.Chem.rdMolDescriptors.CalcNumAromaticRings`, a non-negative integer.
- **`uncertainty`** is `null`: the rule is deterministic given the injected pKa. The IO spec's
  "SFI-vs-generalist (`Solubility_AqSolDB`) discrepancy" uncertainty is a **downstream (t41) signal**
  computed by the aggregator against a generalist model, not a native output of this rule.
- **Invalid or empty SMILES** -> a valid record with `endpoint_values` null and the reason in `raw`
  (`raw.error`). The adapter does not crash, so one bad molecule never sinks a bulk batch.

## cLogD, not cLogP (flag F-12)

SFI uses **cLogD(7.4), not cLogP**. For the di-basic FTO series logP != logD at pH 7.4, so the pKa
correction must not be skipped. cLogD is derived from Crippen cLogP (the same Wildman-Crippen WLOGP lens
as t10 `rdkit_crippen`) corrected via Henderson-Hasselbalch. For a base:

```
cLogD(7.4) = cLogP - log10(1 + 10^(pKa - 7.4))
```

Anchor sanity: the measured series logD is approximately 1.

## pKa is a placeholder pending F-13 (DEFERRED)

**F-13 (single shared pKa source) is DEFERRED** (CLAUDE.md §4a). BBB Score, CNS MPO, and SFI must all draw
their pKa from ONE shared source, which has not been decided. Until it is, this adapter uses a documented
**PLACEHOLDER base pKa** (`PLACEHOLDER_PKA = 9.0` in `run.py`), a generic basic-amine stand-in - **not** a
decided value. It is **injectable**: pass `--pka <float>` to override per run, and once F-13 lands (OPERA
`pKa_pred` or one chosen predictor) that source feeds `--pka`. The chosen pKa and its source are stamped
into every record's `provenance` / `raw` so no reader mistakes the placeholder for a decision.

`TODO(F-13)`: replace `PLACEHOLDER_PKA` with the single shared pKa source across BBB Score / CNS MPO / SFI.

## Uniform CLI

```
python run.py --input <path> --output <path> [--gpu N] [--pka FLOAT]
```

`--gpu` is accepted and **ignored** (`requires_gpu=False`); it exists only so the dispatcher can build one
command for every model. `--pka` is the injectable F-13 hook (above).

## Provenance

- **Upstream:** the SFI concept (Bhal SK et al., Mol Pharm 2007, GSK) as popularized by Pat Walters'
  "Solubility Forecast Index" post (the reference Gilson shared). Implemented here in pure RDKit
  (`Chem.Crippen.MolLogP` for cLogP, `rdMolDescriptors.CalcNumAromaticRings` for the ring count) plus the
  Henderson-Hasselbalch cLogD step - no vendored third-party repo, so there is no `vendor/` folder. Exact
  RDKit version is recorded per run in `provenance.rdkit_version` and pinned by `pixi.lock`.
- **Citation:** Bhal SK, Kassam K, Peirson IG, Pearl GM. "The Rule of Five Revisited: Applying Log D in
  Place of Log P in Drug-Likeness Filters." Mol Pharm 2007, 4(4):556-560. cLogP: Wildman & Crippen, J Chem
  Inf Comput Sci 1999, 39(5):868-873.
- **Access tag:** CODE-ALGO.
- **License:** BSD-3-Clause (RDKit).
- **Quirks:** LOWER = better (inverts vs generalist log S, reconciled at t41); cLogD != cLogP (F-12, pKa
  correction applied); pKa is the F-13 placeholder (injectable via `--pka`); `MolFromSmiles` returns `None`
  on unparseable input (handled as a per-record error, not a raise).

## Environment / lock

`pixi.toml` is intent (conda-forge: `python 3.11.*`, `rdkit`). `pixi.lock` is **solved on the box** (Linux
+ conda-forge) and committed; it carries a real `linux-64` section with package hashes. macOS cannot
resolve the per-model env, so `platforms = ["linux-64"]`.

## Smoke

```
pixi run --manifest-path pixi.toml python run.py \
  --input ../../../tests/fixtures/fto43.smi --output /tmp/sfi.out.json
```

yields a finite `SFI` + `cLogD_7.4` and an integer `n_aromatic_rings` for the FTO-43 fixture.
`tests/test_model_sfi.py` (`@pytest.mark.model`) drives this on the box and validates the output against
`core.schemas`, including the identity `SFI == cLogD_7.4 + n_aromatic_rings`.
