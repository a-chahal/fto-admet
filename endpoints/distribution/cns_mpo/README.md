# cns_mpo - CNS MPO (distribution / BBB / CNS)

A **CODE-ALGO rule** (no weights, no GPU): the CNS MPO (Central Nervous System Multiparameter
Optimization; Wager et al., ACS Chem. Neurosci. 2010, updated 2016), a six-property physicochemical
desirability score for CNS drug-likeness. It follows the t10/t13/t14 folder/adapter shape (uniform
`run.py` CLI, box-solved `pixi.lock`, `OutputRecord`-shaped JSON) and computes five RDKit descriptors
plus an injectable pKa.

## Role: a rough CNS desirability lens (HIGHER = more CNS-desirable)

```
CNS_MPO = D(MW) + D(cLogP) + D(cLogD) + D(HBD) + D(pKa) + D(TPSA)     -> single float on 0..6
```

Each `D(x)` is a Wager desirability transform mapping one descriptor to `[0, 1]`, with **equal weight**,
so the six-term sum spans **0 to 6**, and **a HIGHER CNS_MPO means more CNS-desirable** (Wager 2010:
compounds with MPO >= 4 are enriched among marketed CNS drugs).

### Rough filter only, NOT a gate (landmine)

CNS MPO is a **rough filter**. It is weak on the harder set: **AUC 0.53 on the PET-tracer set** (barely
above chance), and even for BBB penetration the BBB Score (t14) is the stronger discriminator (AUC 0.86
vs CNS MPO ~0.61). So this score is **not a gate**: do not promote or reject a molecule on it alone. The
t42 distribution aggregator votes it alongside the other passive-penetration signals (BBB Score,
BOILED-Egg BBB, BBB_Martins), which sit on **incompatible scales** (F-4: 0-6 desirability vs probability
vs boolean) and are reconciled **ordinally, never averaged**.

## The six desirability transforms (Wager 2010 inflection points)

Five properties are **monotonic decreasing** (smaller = more CNS-desirable); TPSA is **hump-shaped**
(a mid-range polar-surface window is best). These are the published Wager 2010 inflections that every
reference port uses:

| Term | Descriptor (RDKit) | Transform: score 1.0 -> score 0.0 |
|------|--------------------|-----------------------------------|
| `D(MW)` | `Descriptors.MolWt` (average MW) | 1.0 at MW <= 360, linear to 0 at MW >= 500 |
| `D(cLogP)` | `Crippen.MolLogP` (Wildman-Crippen) | 1.0 at cLogP <= 3.0, linear to 0 at cLogP >= 5.0 |
| `D(cLogD)` | cLogD(7.4), see below | 1.0 at cLogD <= 2.0, linear to 0 at cLogD >= 4.0 |
| `D(HBD)` | `CalcNumHBD` | 1.0 at HBD <= 0.5, linear to 0 at HBD >= 3.5 |
| `D(pKa)` | injected most-basic pKa (F-13) | 1.0 at pKa <= 8.0, linear to 0 at pKa >= 10.0 |
| `D(TPSA)` | `CalcTPSA` (Ertl) | **hump**: 0 at TPSA <= 20, up to 1.0 at 40, plateau 1.0 to 90, down to 0 at TPSA >= 120 |

The transform coefficients are transcribed from Wager 2010 / the `Adam-maz/CNS_MPO_calculator` reference
port and live in `run.py` (`desirability_decreasing`, `desirability_tpsa`), so the formula is auditable
and not a black-box dependency.

### cLogD, not cLogP, for the `D(cLogD)` term (F-12)

`D(cLogP)` uses raw Crippen cLogP; `D(cLogD)` uses **cLogD(7.4)**, derived from the same Crippen cLogP
corrected for ionization with the injected pKa via Henderson-Hasselbalch (base):
`cLogD = cLogP - log10(1 + 10^(pKa - 7.4))`. For the di-basic FTO series logP != logD at pH 7.4, so the
pKa correction is **not skipped** - the same correction t13 (SFI) applies.

## Output contract (the JSON keys the dispatcher validates)

`run.py` runs in this model's isolated env and cannot import `core`, so it writes plain JSON matching
`core.schemas.OutputRecord`. One input record -> one output object; a JSON array or `.smi` in -> a JSON
array out. Each record:

```json
{
  "model": "cns_mpo",
  "endpoint_values": { "CNS_MPO": 4.83 },
  "uncertainty": null,
  "raw": {
    "smiles": "...", "mol_id": "...", "pka": 9.0, "pka_source": "...", "ph": 7.4,
    "CNS_MPO": 4.83, "MW": 151.16, "cLogP_crippen": 1.35, "cLogD_7.4": 1.35, "nHBD": 2, "TPSA": 49.33,
    "D_MW": 1.0, "D_cLogP": 1.0, "D_cLogD": 1.0, "D_HBD": 0.83, "D_pKa": 0.5, "D_TPSA": 1.0
  },
  "provenance": { "model": "cns_mpo", "method": "...", "rdkit_version": "...", "pka": 9.0, "pka_source": "...", "citation": "...", "license": "..." }
}
```

- **`CNS_MPO`** - the CNS MPO score. **Units:** dimensionless, fixed **0-6** scale. **Direction: HIGHER =
  more CNS-desirable.**
- The six raw descriptors and the six `D_*` desirability terms (each in `[0, 1]`) are carried in `raw` for
  audit; the reported `CNS_MPO` is exactly their sum, so the score is reconstructible.
- **`uncertainty`** is `null`: the rule is deterministic given the injected pKa.
- **Invalid or empty SMILES** -> a valid record with `endpoint_values.CNS_MPO = null` and the reason in
  `raw` (`raw.error`). The adapter does not crash, so one bad molecule never sinks a bulk batch.

## pKa is the shared placeholder pending F-13 (DEFERRED)

**F-13 (single shared pKa source) is DEFERRED** (CLAUDE.md §4a). BBB Score, CNS MPO, and SFI must all draw
their pKa from ONE shared source, which has not been decided - the three rules are **internally comparable
only if the pKa is identical**. Until F-13 lands, this adapter uses the **same documented PLACEHOLDER base
pKa as t13 (SFI) / t14 (BBB Score)** (`PLACEHOLDER_PKA = 9.0` in `run.py`), a generic basic-amine stand-in -
**not** a decided value, and deliberately **not diverged per model**. The pKa feeds **both** the `D(pKa)`
term and the cLogD correction. It is **injectable**: pass `--pka <float>` to override per run, and once F-13
lands (OPERA `pKa_pred` or one chosen predictor) that source feeds `--pka`. The chosen pKa and its source
are stamped into every record's `provenance` / `raw`, so no reader mistakes the placeholder for a decision.

`TODO(F-13)`: replace `PLACEHOLDER_PKA` with the single shared pKa source across BBB Score / CNS MPO / SFI.

## Uniform CLI

```
python run.py --input <path> --output <path> [--gpu N] [--pka FLOAT]
```

`--gpu` is accepted and **ignored** (`requires_gpu=False`); it exists only so the dispatcher can build one
command for every model. `--pka` is the injectable F-13 hook (above).

## Provenance

- **Upstream:** the CNS MPO scoring function (Wager, Hou, Verhoest, Villalobos). Reimplemented here in pure
  RDKit (`Descriptors`, `Crippen`, `rdMolDescriptors`) directly from the paper, with the reference port
  `github.com/Adam-maz/CNS_MPO_calculator` (also RDKit-based) as the cross-check - so the formula is
  auditable and not a black-box dependency; no vendored third-party repo, so there is no `vendor/` folder.
  Exact RDKit version is recorded per run in `provenance.rdkit_version` and pinned by `pixi.lock`.
- **Citation:** Wager TT, Hou X, Verhoest PR, Villalobos A. "Moving beyond Rules: The Development of a
  Central Nervous System Multiparameter Optimization (CNS MPO) Approach To Enable Alignment of Druglike
  Properties." ACS Chem Neurosci 2010, 1(6):435-449, DOI 10.1021/cn100008c; update ACS Chem Neurosci 2016,
  7(6):767-775, DOI 10.1021/acschemneuro.6b00029.
- **Access tag:** CODE-ALGO.
- **License:** BSD-3-Clause (RDKit).
- **Quirks:** HIGHER = more CNS-desirable (0-6 scale); a **rough filter only, NOT a gate** (AUC 0.53 on the
  PET-tracer set; weaker than BBB Score for BBB penetration; reconciled ordinally with the other passive
  scores at t42); TPSA is hump-shaped (do not invert the ramp); `D(cLogD)` applies the F-12 pKa correction
  while `D(cLogP)` does not; pKa is the F-13 shared placeholder feeding both `D(pKa)` and cLogD (injectable
  via `--pka`, do not diverge from t13/t14); `MolFromSmiles` returns `None` on unparseable input (handled
  as a per-record error, not a raise).

## Consistency check (unit test)

`tests/test_model_cns_mpo.py` (`@pytest.mark.model`) runs on the box and, besides the FTO-43 smoke,
asserts the **six-component sum consistency**: for several molecules the reported `CNS_MPO` equals
`D_MW + D_cLogP + D_cLogD + D_HBD + D_pKa + D_TPSA`, each in `[0, 1]`, and the score stays in `[0, 6]`.
(There is no external reference-score comparison: the Wager paper used ACD ClogP/ClogD, not RDKit Crippen,
so published whole-drug CNS MPO scores are not reproducible descriptor-for-descriptor here; the honest
check is internal sum-consistency plus the paper's published inflection points transcribed in `run.py`.)

## Environment / lock

`pixi.toml` is intent (conda-forge: `python 3.11.*`, `rdkit`). `pixi.lock` is **solved on the box** (Linux
+ conda-forge) and committed; it carries a real `linux-64` section with package hashes. macOS cannot
resolve the per-model env, so `platforms = ["linux-64"]`.

## Smoke

```
pixi run --manifest-path pixi.toml python run.py \
  --input ../../../tests/fixtures/fto43.smi --output /tmp/cns_mpo.out.json
```

yields a finite `CNS_MPO` in [0, 6] for the FTO-43 fixture. `tests/test_model_cns_mpo.py` drives this on
the box, validates the output against `core.schemas`, and checks the six-component sum consistency.
