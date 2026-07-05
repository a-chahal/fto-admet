# admet_ai - ADMET-AI v2 cross-cutting generalist (triage home; feeds 10 endpoints)

The busiest cross-cutting model in the pipeline. It physically lives under `triage/`, but its registry
`endpoints` set spans **ten** endpoints - triage, herg, metabolism, clearance, ppb, solubility,
lipophilicity, permeability, distribution, toxicity - so its single run feeds ten aggregators. The adapter
therefore emits **every** head and lets each aggregator pick the fields it needs (model -> endpoint is a
graph; aggregators query the registry by endpoint, never by folder: CLAUDE.md §2).

Access tag: **CODE-PKG** (PyPI `admet-ai`, MIT). Upstream: `github.com/swansonk14/admet_ai`.

## v2, NOT v1 (read this first)

This adapter is pinned to **ADMET-AI v2** (Chemprop v2 D-MPNN, retrained from scratch, no RDKit
fingerprints). The maintainers state v2 predictions **will not exactly match v1**. The published paper
(Swanson et al., *Bioinformatics* 40(7):btae416, 2024) and the live web server
(`admet.ai.greenstonebio.com`) are still **v1**. So any cross-check against the paper/web server will
differ, and that is expected, not a bug. We use v2 because it is the current, maintained stack and
release **v2.0.1 "Fixing models on Linux/CUDA" (22 Feb 2026)** targets exactly the Rosenbluth box.

## F-17 reliability exclusions (hard rule)

ADMET-AI v2's own reported metrics (from `admet_ai/resources/data/admet.csv`, verified 2 Jul 2026) show two
regression heads are **worse than predicting the mean**:

| head | reported R^2 | disposition |
| --- | --- | --- |
| `VDss_Lombardo` | **-1.21** | **EXCLUDED from `endpoint_values` entirely** (F-17) |
| `Half_Life_Obach` | **-2.39** | **EXCLUDED from `endpoint_values` entirely** (F-17) |

Both are kept **verbatim in `raw.columns`** and additionally surfaced under `raw.excluded_r2_negative`,
tagged, so they are auditable but **nothing downstream can consume them** (CLAUDE.md §4). The distribution
and PK aggregators must never see an ADMET-AI VDss or half-life.

Both clearance heads are weak (R^2 ~ 0.26 / 0.28) and are therefore emitted but flagged
**low-weight / qualitative** in `raw.head_flags`. They are kept **decomposed** (F-3): never combine
ADMET-AI's `Clearance_Hepatocyte_AZ` (uL/min/10^6 cells) or `Clearance_Microsome_AZ` (uL/min/mg)
numerically with PKSmart CL (mL/min/kg), OPERA `Clint`, or DruMAP CLint - different units and matrices.

Classification heads are **strong** where it matters (HIA 0.99, Pgp 0.95, CYP inhibition 0.89-0.94, BBB
0.90, hERG 0.84) and are emitted normally as probabilities in [0, 1].

## Uncertainty is INDIRECT (so `uncertainty = None`)

ADMET-AI v2 has **no native per-prediction uncertainty field** (IO_SPEC §1 #1). Its uncertainty signal is
**INDIRECT**: cross-model spread, computed later at aggregation. So every record carries
`uncertainty = None` - there is nothing DIRECT to place in the reserved `Uncertainty` envelope (contrast
PKSmart, which emits a native fold-error). The per-head reliability tags (excluded / low-weight) describe a
*head's* trustworthiness, not a *molecule's* uncertainty, so they live in `raw.head_flags` /
`raw.excluded_r2_negative`, keeping `uncertainty` faithfully `None`.

## Output contract (the JSON keys the dispatcher validates)

`run.py` runs in this model's isolated env and cannot import `core`, so it writes plain JSON matching
`core.schemas.OutputRecord`. One input record -> one output object; a JSON array or `.smi` in -> a JSON
array out. Each record:

```json
{
  "model": "admet_ai",
  "endpoint_values": {
    "molecular_weight": 346.85, "logP": 2.9, "QED": 0.71, "tpsa": 54.1,
    "hERG": 0.12, "BBB_Martins": 0.83, "Pgp_Broccatelli": 0.44, "CYP3A4_Veith": 0.30,
    "HIA_Hou": 0.98, "Solubility_AqSolDB": -3.4, "Lipophilicity_AstraZeneca": 2.1,
    "PPBR_AZ": 88.0, "Clearance_Hepatocyte_AZ": 21.0, "Clearance_Microsome_AZ": 17.0,
    "LD50_Zhu": 2.4, "NR-AR": 0.02, "...": "every usable head"
  },
  "uncertainty": null,
  "raw": {
    "smiles": "...", "mol_id": "...",
    "columns": { "...": "verbatim complete output: all heads + physchem + 3 alert counts + every <property>_drugbank_approved_percentile" },
    "excluded_r2_negative": { "VDss_Lombardo": 1.2, "Half_Life_Obach": 5.0, "VDss_Lombardo_drugbank_approved_percentile": 40.0, "...": "..." },
    "head_flags": { "Clearance_Hepatocyte_AZ": "low_weight_qualitative ...", "LD50_Zhu": "log(1/(mol/kg)); UP = MORE toxic ...", "...": "..." }
  },
  "provenance": { "model": "admet_ai", "admet_ai_version": "...", "version_note": "v2 ...", "device": "cpu", "citation": "...", "license": "MIT ..." }
}
```

### `endpoint_values` - promoted, usable heads only

Every prediction head **except** the two F-17-excluded regression heads and **except** the
`_drugbank_approved_percentile` context companions (those stay in `raw.columns`). Keys are ADMET-AI's own
canonical column names so aggregators can pick by name. Units are baked per IO_SPEC §1 #1:

| head (example) | quantity | unit / range | direction |
| --- | --- | --- | --- |
| classification heads (`hERG`, `BBB_Martins`, `Pgp_Broccatelli`, CYP*, `HIA_Hou`, `AMES`, `DILI`, 12 Tox21 ...) | P(named positive class) | [0, 1] | UP = more of that property |
| `molecular_weight` / `tpsa` / `logP` / `QED` / `Lipinski` / `stereo_centers` / H-bond donors/acceptors | RDKit physchem | g/mol, A^2, log, 0-1, counts | per property |
| `PAINS_alert` / `BRENK_alert` / `NIH_alert` | structural-alert counts | int | UP = more alerts |
| `Caco2_Wang` | Caco-2 permeability | log Papp (cm/s) | UP = more permeable |
| `Lipophilicity_AstraZeneca` | logD7.4 | log-ratio | UP = more lipophilic |
| `Solubility_AqSolDB` | aqueous solubility | log mol/L | UP = more soluble |
| `PPBR_AZ` | plasma-protein binding | **% bound** | UP = more bound (for ppb, normalize /100) |
| `Clearance_Hepatocyte_AZ` | hepatocyte CLint | **uL/min/10^6 cells** (low-weight) | UP = faster |
| `Clearance_Microsome_AZ` | microsomal CLint | **uL/min/mg** (low-weight) | UP = faster |
| `LD50_Zhu` | acute oral LD50 | **log(1/(mol/kg))** | **UP = MORE toxic**; NOT comparable to ProTox mg/kg (F-5) |
| `HydrationFreeEnergy_FreeSolv` | hydration free energy | kcal/mol | (physchem) |

`VDss_Lombardo` and `Half_Life_Obach` are **absent** from this dict by design (F-17).

### `raw`

- `columns` - the verbatim, complete ADMET-AI output for the molecule (nothing dropped): every head, the 8
  physchem props, the 3 alert counts, and each `<property>_drugbank_approved_percentile` companion
  (0-100 percentile vs approved drugs).
- `excluded_r2_negative` - `VDss_Lombardo` / `Half_Life_Obach` (+ their percentile companions), quarantined.
- `head_flags` - advisory per-head metadata for aggregators (low-weight clearance, LD50 direction/units,
  PPBR percent-vs-fraction), so a downstream consumer never has to re-touch this adapter.

## Input, standardization (F-16 DEFERRED), and the FTO di-cation

The adapter feeds ADMET-AI the **single canonical SMILES `core` hands it, unmodified**. ADMET-AI does its
own internal RDKit parse/canonicalization but documents **no desalting/protonation step**. F-16 (the FTO
di-cation standardization: protonation / tautomer / desalting) is **DEFERRED** (CLAUDE.md §4a): we do
**not** silently pick a protonation state here. The pipeline must feed a **neutralized parent** upstream;
this divergence is flagged, not resolved, in this adapter.

**Build-time confirmation on the FTO input:** the smoke ran against the `tests/fixtures/fto43.smi` fixture,
which is currently the documented **placeholder** SMILES (the real canonical structure for CID 164886650 is
a pending live lookup, per `tests/conftest.py`). The adapter parses and predicts the full head set on it;
once the real neutralized FTO-43 parent replaces the placeholder, no code changes here.

## Environment

- `pixi.toml` intent: `python 3.12` + PyPI `admet-ai >= 2.0.1`; admet-ai's own pyproject pulls the exact
  companion stack (chemprop >= 2.2.2, torch >= 2.8, lightning, rdkit >= 2025.9.5, numpy, pandas, seaborn,
  tqdm, typed-argument-parser). Model weights ship **inside the admet-ai wheel** - no run-time download.
- `pixi.lock` is **solved on the box** (linux-64 + CUDA); macOS cannot resolve the CUDA torch wheels, so
  `platforms = ["linux-64"]` only. The lock's `linux-64` section carries real package hashes (the gate
  checks this to catch a fabricated/laptop-solved lock).
- GPU is **optional** (`requires_gpu = False`). Default run is CPU (`CUDA_VISIBLE_DEVICES=""`); pass
  `--gpu N` to pin CUDA device N (set before torch imports). The uniform CLI is
  `python run.py --input <path> --output <path> [--gpu N]`.

## Provenance

- **Upstream:** `github.com/swansonk14/admet_ai` (MIT; HEALTHY: ~320 stars, 231 commits, 9 releases, not
  archived; latest release v2.0.1, 22 Feb 2026).
- **Version pin:** v2 (Chemprop v2, retrained). `admet_ai_version` is read live from the installed package
  and stamped into every record's `provenance` (never hardcoded).
- **Citation:** Swanson K, Walther P, Leitz J, Mukherjee S, Wu JC, Shivnaraine RV, Zou J. ADMET-AI: a
  machine learning ADMET platform. *Bioinformatics* 40(7):btae416 (2024).
  doi:10.1093/bioinformatics/btae416.
- **License:** MIT (code). Access tag CODE-PKG.
- **Quirks:** v2 != v1 (predictions differ from paper/web server); no native per-prediction uncertainty
  (INDIRECT signal, `uncertainty = None`); VDss + half-life heads unusable (F-17, excluded); clearance heads
  low-weight (kept decomposed, F-3); `LD50_Zhu` is log(1/(mol/kg)), UP = more toxic, not comparable to
  ProTox mg/kg (F-5); `PPBR_AZ` is % bound (÷100 for a fraction).
