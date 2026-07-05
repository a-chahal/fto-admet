# lipinski_veber_qed - drug-likeness context (druglikeness)

A **CODE-PKG rule** (no weights, no GPU): three classic drug-likeness summaries computed from **RDKit
descriptors + `rdkit.Chem.QED`**. It follows the t10/t16/t17/t18 folder/adapter shape (uniform `run.py`
CLI, box-solved `pixi.lock`, `OutputRecord`-shaped JSON).

## Context / POINTER only - NOT a gate (the landmine)

This model is run for the **lab's sanity check** (docs IO_SPEC §30, task t19). The druglikeness
aggregator (t50) reports these three values as **flags**, never a kill: a Lipinski violation or a Veber
fail is a note, not a disqualification. Many marketed drugs violate the Rule of 5. This adapter emits
only the raw flags (plus the six underlying descriptors in `raw`); **no promotion / kill logic lives
here**, and none should be added.

## The three fields and their directions (docs §30)

| Field | Type | Meaning | Direction |
| --- | --- | --- | --- |
| `Lipinski_violations` | int 0-4 | count of Ro5 rules **violated**: MW > 500, HBD > 5, HBA > 10, logP > 5 | **fewer = more drug-like** |
| `Veber_pass` | bool | `RotatableBonds <= 10` **and** `TPSA <= 140` | **pass = more drug-like** |
| `QED` | float 0-1 | quantitative estimate of drug-likeness (Bickerton 2012) | **↑ = more drug-like** |

`Lipinski_violations` is reported as the **violation count** (the "int 0-4" sense in docs §30), so `0`
means all four Ro5 conditions are satisfied and `4` means none are. The exact thresholds are named
constants in `run.py` (`RO5_MW_MAX` etc.) and echoed into every record's `raw.Lipinski_thresholds` /
`raw.Veber_thresholds` so a downstream reader never re-derives the cutoffs or their sense.

## Descriptors used (docs §30 input contract)

RDKit only: `Descriptors.MolWt` (MW), `Descriptors.NumHDonors` (HBD), `Descriptors.NumHAcceptors` (HBA),
`Descriptors.NumRotatableBonds` (RotB), `Descriptors.TPSA` (TPSA), `Crippen.MolLogP` (logP), and
`rdkit.Chem.QED.qed(mol)` (QED). The exact RDKit version is recorded per run in
`provenance.rdkit_version` and pinned by `pixi.lock`.

**Crippen logP, not logD (flag F-12):** the lipophilicity term in the Ro5 test is the Wildman-Crippen
`MolLogP` (the same lens as `rdkit_crippen`, t10). It is logP, **not** logD; the di-basic FTO logD
conversion needs a shared pKa and is done downstream with the shared pKa source, never silently here.

## Output contract (the JSON keys the dispatcher validates)

`run.py` runs in this model's isolated env and cannot import `core`, so it writes plain JSON matching
`core.schemas.OutputRecord`. One input record -> one output object; a JSON array or `.smi` in -> a JSON
array out. Each record:

```json
{
  "model": "lipinski_veber_qed",
  "endpoint_values": { "Lipinski_violations": 0, "Veber_pass": true, "QED": 0.55 },
  "uncertainty": null,
  "raw": {
    "smiles": "...", "mol_id": "...",
    "descriptors": { "MW": 180.16, "HBD": 1, "HBA": 3, "RotB": 2, "TPSA": 63.6, "logP": 1.31 },
    "Lipinski_thresholds": { "MW": 500.0, "HBD": 5, "HBA": 10, "logP": 5.0 },
    "Veber_thresholds": { "RotB": 10, "TPSA": 140.0 },
    "context_only": true
  },
  "provenance": { "model": "lipinski_veber_qed", "method": "...", "rdkit_version": "...", "citation": "...", "license": "..." }
}
```

- **`Lipinski_violations`** (int 0-4) - count of Ro5 rules violated; fewer = more drug-like.
- **`Veber_pass`** (bool) - `RotB <= 10` and `TPSA <= 140`.
- **`QED`** (float 0-1) - `rdkit.Chem.QED.qed(mol)`; higher = more drug-like.
- The **six underlying descriptors** land in `raw.descriptors` (non-scalar-policy, so out of
  `endpoint_values`, per the schema note) so each flag is auditable / reconstructible.
- **`uncertainty`** is `null`: the rule is deterministic.
- **Invalid or empty SMILES** -> a valid record with all three values `null` and the reason in
  `raw.error`. The adapter does not crash, so one bad molecule never sinks a bulk batch.

## Uniform CLI

```
python run.py --input <path> --output <path> [--gpu N]
```

`--gpu` is accepted and **ignored** (`requires_gpu=False`); it exists only so the dispatcher can build one
command for every model. These are pure CPU descriptors.

## Provenance

- **Upstream:** RDKit's built-in descriptors (`Descriptors` / `Lipinski` / `Crippen`) and `rdkit.Chem.QED`.
  No vendored third-party runtime is imported, so there is no `vendor/` folder; the RDKit version is
  recorded per run in `provenance.rdkit_version` and pinned by `pixi.lock`.
- **Citation:** Lipinski CA et al. Adv Drug Deliv Rev 2001, 46(1-3):3-26 (Rule of 5); Veber DF et al.
  J Med Chem 2002, 45(12):2615-2623 (rotatable bonds / TPSA); Bickerton GR et al. Nat Chem 2012,
  4(2):90-98 (QED).
- **Access tag:** CODE-PKG.
- **License:** BSD-3-Clause (RDKit).
- **Quirks:** `Lipinski_violations` is the violation *count* (0-4), not the pass bool - fewer = more
  drug-like. logP is Wildman-Crippen `MolLogP`, not logD (F-12). This is a **context / POINTER** model:
  never a gate. `MolFromSmiles` returns `None` on unparseable input (handled as a per-record error, not a
  raise).

## Consistency check (unit test)

`tests/test_model_lipinski_veber_qed.py` (`@pytest.mark.model`) runs on the box and, besides the FTO-43
smoke, pins: (1) **types + ranges** - `Lipinski_violations` int 0-4, `Veber_pass` bool, `QED` in [0, 1],
with the six descriptors present in `raw`; (2) a **known drug-like molecule** (aspirin -> 0 violations,
Veber pass, QED in (0, 1)), proving the descriptors + QED actually compute; (3) a **known Ro5 violator**
(a long lipophilic alkane -> >= 1 violation, low QED), proving the violation logic responds to the
descriptors.

## Environment / lock

`pixi.toml` is intent (conda-forge: `python 3.11.*`, `rdkit`). `pixi.lock` is **solved on the box** (Linux
+ conda-forge) and committed; it carries a real `linux-64` section with package hashes. macOS cannot
resolve the per-model env, so `platforms = ["linux-64"]`.

## Smoke

```
pixi run --manifest-path pixi.toml python run.py \
  --input ../../../tests/fixtures/fto43.smi --output /tmp/lipinski_veber_qed.out.json
```

yields the three fields (`Lipinski_violations` / `Veber_pass` / `QED`) plus the six underlying
descriptors for the FTO-43 fixture. `tests/test_model_lipinski_veber_qed.py` drives this on the box,
validates the output against `core.schemas`, and pins the type/range + known drug-like / violator cases.
