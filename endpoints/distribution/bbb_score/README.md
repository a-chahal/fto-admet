# bbb_score - BBB Score (distribution / BBB / CNS)

A **CODE-ALGO rule** (no weights, no GPU): the BBB Score (Gupta et al., J. Med. Chem. 2019), a
multiparameter passive brain-entry score. It follows the t10/t13 folder/adapter shape (uniform `run.py`
CLI, box-solved `pixi.lock`, `OutputRecord`-shaped JSON) and computes five RDKit descriptors plus an
injectable pKa.

## Role: the passive brain-entry lens (HIGHER = more penetrant)

```
BBB_Score = P(Aro_R) + P(HA) + 1.5*P(MWHBN) + 2*P(TPSA) + 0.5*P(pKa)     -> single float on 0..6
```

Each `P(x)` is a paper desirability transform (max-normalised to a peak of 1) of one descriptor. With
weights `1, 1, 1.5, 2, 0.5` the score spans **0 to 6**, and **a HIGHER BBB_Score means more likely
passive BBB penetrant** (Gupta 2019, AUC 0.86, vs CNS MPO 0.61 / MPO_V2 0.67).

### Passive filter only, NOT a gate (landmine)

This is a **passive-permeation filter, not a brain-exposure prediction**. The real CNS answer is the
experimental unbound brain-to-plasma ratio Kp,uu; BBB penetration is **desirable, not a gate**. Do not
promote or reject a molecule on this score alone. The t42 distribution aggregator votes it alongside the
other passive-penetration signals (CNS MPO, BOILED-Egg BBB, BBB_Martins), which sit on incompatible
scales (F-4: 0-6 desirability vs probability vs boolean) and are reconciled ordinally, never averaged.

## The five descriptors (all RDKit `rdMolDescriptors`)

| Term | Descriptor | Transform (valid range -> P) |
|------|-----------|------------------------------|
| `Aro_R` | `CalcNumAromaticRings` | stepwise: {0:0.336367, 1:0.816016, 2:1, 3:0.691115, 4:0.199399, >4:0} |
| `HA` | `CalcNumHeavyAtoms` | cubic on `5 < HA <= 45`, else 0 |
| `MWHBN` | `(nHBA + nHBD) / sqrt(MW)` | cubic on `0.05 < MWHBN <= 0.45`, else 0 |
| `TPSA` | `CalcTPSA` (Ertl) | linear on `0 < TPSA <= 120`, else 0 |
| `pKa` | injected most-basic pKa (F-13) | quartic on `3 < pKa <= 11`, else 0 |

where `nHBA = CalcNumHBA`, `nHBD = CalcNumHBD`, and `MW = CalcExactMolWt`. The exact polynomial
coefficients are transcribed from Gupta 2019 / the `gkxiao/BBB-score` port and live in `run.py`; the
implementation mirrors the port's rounding (MW and MWHBN to 2 decimals) so it reproduces the reference
scores exactly.

## Output contract (the JSON keys the dispatcher validates)

`run.py` runs in this model's isolated env and cannot import `core`, so it writes plain JSON matching
`core.schemas.OutputRecord`. One input record -> one output object; a JSON array or `.smi` in -> a JSON
array out. Each record:

```json
{
  "model": "bbb_score",
  "endpoint_values": { "BBB_Score": 4.43 },
  "uncertainty": null,
  "raw": {
    "smiles": "...", "mol_id": "...", "pka": 9.89, "pka_source": "...",
    "BBB_Score": 4.43, "MW": 151.06, "nHBA": 2, "nHBD": 2, "HBN": 4, "MWHBN": 0.33,
    "HA": 11, "n_aromatic_rings": 1, "TPSA": 49.33,
    "P_ARO_R": 0.816016, "P_HA": 0.68, "P_MWHBN": 0.98, "P_TPSA": 0.61, "P_PKA": 0.63
  },
  "provenance": { "model": "bbb_score", "method": "...", "rdkit_version": "...", "pka": 9.89, "pka_source": "...", "citation": "...", "license": "..." }
}
```

- **`BBB_Score`** - the BBB Score. **Units:** dimensionless, fixed **0-6** scale. **Direction: HIGHER =
  more likely passive BBB penetrant.**
- The component descriptors and `P_*` desirability terms are carried in `raw` for audit (the aggregator
  reads only `BBB_Score`; `raw` makes the score reconstructible).
- **`uncertainty`** is `null`: the rule is deterministic given the injected pKa.
- **Invalid or empty SMILES** -> a valid record with `endpoint_values.BBB_Score = null` and the reason in
  `raw` (`raw.error`). The adapter does not crash, so one bad molecule never sinks a bulk batch.

## pKa is the shared placeholder pending F-13 (DEFERRED)

**F-13 (single shared pKa source) is DEFERRED** (CLAUDE.md §4a). BBB Score, CNS MPO, and SFI must all draw
their pKa from ONE shared source, which has not been decided. Until it is, this adapter uses the **same
documented PLACEHOLDER base pKa as t13 (SFI) / t15 (CNS MPO)** (`PLACEHOLDER_PKA = 9.0` in `run.py`), a
generic basic-amine stand-in - **not** a decided value, and deliberately **not diverged per model**. It is
**injectable**: pass `--pka <float>` to override per run, and once F-13 lands (OPERA `pKa_pred` or one
chosen predictor) that source feeds `--pka`. The chosen pKa and its source are stamped into every record's
`provenance` / `raw` so no reader mistakes the placeholder for a decision.

`TODO(F-13)`: replace `PLACEHOLDER_PKA` with the single shared pKa source across BBB Score / CNS MPO / SFI.

## Uniform CLI

```
python run.py --input <path> --output <path> [--gpu N] [--pka FLOAT]
```

`--gpu` is accepted and **ignored** (`requires_gpu=False`); it exists only so the dispatcher can build one
command for every model. `--pka` is the injectable F-13 hook (above).

## Provenance

- **Upstream:** the BBB Score formula (Gupta, Lee, Barden, Weaver, J. Med. Chem. 2019). Reimplemented here
  in pure RDKit (`rdMolDescriptors`) directly from the paper and unit-tested against the reference RDKit
  port `github.com/gkxiao/BBB-score` (also `github.com/sailfish009/BBB_calculator`), so the formula is
  auditable and not a black-box dependency - no vendored third-party repo, so there is no `vendor/`
  folder. Exact RDKit version is recorded per run in `provenance.rdkit_version` and pinned by `pixi.lock`.
- **Citation:** Gupta M, Lee HJ, Barden CJ, Weaver DF. "The Blood-Brain Barrier (BBB) Score." J Med Chem
  2019, 62(21):9824-9836. DOI 10.1021/acs.jmedchem.9b01220.
- **Access tag:** CODE-ALGO.
- **License:** BSD-3-Clause (RDKit).
- **Quirks:** HIGHER = more penetrant (0-6 scale); passive filter only, NOT a brain-exposure prediction
  and NOT a gate (real answer = experimental Kp,uu; reconciled with the other passive scores at t42); pKa
  is the F-13 shared placeholder (injectable via `--pka`, do not diverge from t13/t15); `MolFromSmiles`
  returns `None` on unparseable input (handled as a per-record error, not a raise).

## Reference agreement (unit test)

`tests/test_model_bbb_score.py` (`@pytest.mark.model`) runs on the box and, besides the FTO-43 smoke,
drives two molecules with published `gkxiao/BBB-score` scores through the adapter and asserts agreement
within tolerance:

| Molecule | SMILES | pKa | Reference BBB_Score |
|----------|--------|-----|---------------------|
| acetaminophen | `CC(=O)Nc1ccc(O)cc1` | 9.89 | 4.43 |
| cinnarizine | `N1(CCN(C\C=C\c2ccccc2)CC1)C(c3ccccc3)c4ccccc4` | 8.1 | 5.01 |

## Environment / lock

`pixi.toml` is intent (conda-forge: `python 3.11.*`, `rdkit`). `pixi.lock` is **solved on the box** (Linux
+ conda-forge) and committed; it carries a real `linux-64` section with package hashes. macOS cannot
resolve the per-model env, so `platforms = ["linux-64"]`.

## Smoke

```
pixi run --manifest-path pixi.toml python run.py \
  --input ../../../tests/fixtures/fto43.smi --output /tmp/bbb_score.out.json
```

yields a finite `BBB_Score` in [0, 6] for the FTO-43 fixture. `tests/test_model_bbb_score.py` drives this
on the box, validates the output against `core.schemas`, and checks the reference-molecule agreement.
