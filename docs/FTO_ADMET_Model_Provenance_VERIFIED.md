# FTO-ADMET — Model Provenance & Access Verification
 
**Reconciled (2 Jul 2026):** the finalized roster is now applied — **DeepHIT** and **Spielvogel dropped**,
**CardioDPi → CToxPred2**, **FAME 3 → FAME3R** — leaving **30 entries** (29 models + permeability
aggregate-only). The per-model records in §B already reach these verdicts; §A's master list and the batch
summary tables below are annotated to match (they were written before the follow-up pass). Note: this doc
is **correct** that SMARTCyp 3.0 is Python/RDKit — a later IO-spec pass wrongly "corrected" it to Java by
reading the legacy `cdk/smartcyp` repo; the skeleton §9 records the resolution.
 
**Status: COMPLETE — all 4 batches done (~31/31 model entries verified; 30 after the two drops).** Source-of-truth verification of
every model in the FTO-ADMET inventory against primary sources (GitHub repos, official docs, PyPI/conda,
original papers). Companion to `FTO_ADMET_Pipeline_Skeleton_SETTLED.md` (§7 inventory) and
`FTO_ADMET_Codebase_And_Environment_SETTLED.md` (§5 inventory). **No pipeline code is written here — recon only.**
 
**Coverage:** triage generalists · full hERG gate · metabolism + clearance · distribution + ppb · solubility ·
lipophilicity · permeability · structural alerts · synthesizability · toxicity · druglikeness. Every model has a
per-model record (§B); the consolidated discrepancy list, new-tool list, and build-watchlist are rolled up in
§E.
 
**Method note / honesty caveat.** Every access claim and dependency fact below is backed by a primary-source
URL that was actually fetched or returned in search. Where a dependency list was read from a repo's
authoritative file (`pyproject.toml` / `setup.py`), that file's URL is cited. Where I did *not* open the exact
dependency file (budget), the field says **UNVERIFIED — read at build time** rather than guessing a version.
Repo star/issue/commit counts are as of the fetch date (2 Jul 2026) and drift; re-check at build time.
 
---
 
## A. Master model list & two-file cross-check
 
**Result: the two settled files are consistent.** Every model in skeleton §7 appears in codebase §5 and vice
versa; no model is present in one file but absent from the other. Names differ only in casing/folder-slug
(`ADMET-AI` ↔ `admet_ai`, `CardioTox net` ↔ `cardiotox_net`, etc.). Two things worth stating explicitly so
they are not mistaken for discrepancies:
 
- **Two distinct RDKit rule modules, not a duplicate.** `PAINS/BRENK` (assay-interference / reactive groups,
  under the `structural_alerts` endpoint) and `toxicophores` (known toxic substructures, under the `toxicity`
  endpoint) are separate rule sets. Both files carry both. Correct.
- **Generalists are cross-cutting.** `admet_ai` and `admetlab3` live physically under `triage/` but their output
  fields are consumed by `solubility`, `permeability`, `toxicity` (bulk substitute), and as the hERG/tox
  pre-screen. Both files document this. Correct.
**Master list (~31 distinct model entries), by endpoint:**
 
| # | Endpoint | Model | Batch |
|---|---|---|---|
| 1 | triage | ADMET-AI | **1 ✔** |
| 2 | triage | ADMETlab 3.0 | **1 ✔** |
| 3 | triage | OpenADMET | **1 ✔** |
| 4 | hERG (gate) | BayeshERG | **1 ✔** |
| 5 | hERG (gate) | CardioTox net | **1 ✔** |
| ~~6~~ | hERG (gate) | DeepHIT → **DROPPED** (no repo; redundant w/ CardioTox net) | **1 ✔** |
| 7 | hERG (gate) | CardioDPi → **CToxPred2** (`issararab/CToxPred2`) | **1 ✔** |
| 8 | hERG (gate) | CardioGenAI | **1 ✔** |
| 9 | metabolism | SMARTCyp 3.0 | **2 ✔** |
| 10 | metabolism | FAME 3 → **FAME3R** (Python; replaces Java FAME 3) | **2 ✔** |
| 11 | clearance | Watanabe renal fe/CLr (DruMAP) `WEB` | **2 ✔** |
| 12 | clearance | PKSmart | **2 ✔** |
| 13 | clearance | PBPK (OSP / PK-Sim) | **2 ✔** |
| 14 | distribution | BBB Score | **3 ✔** |
| 15 | distribution | BOILED-Egg | **3 ✔** |
| 16 | distribution | CNS MPO | **3 ✔** |
| 17 | distribution | P-gp (efflux substrate) | **3 ✔** |
| ~~18~~ | distribution | Spielvogel efflux/BBB → **DROPPED** (dataset-only; no released model) | **3 ✔** |
| 19 | distribution | Watanabe P-gp brain (DruMAP) `WEB` | **3 ✔** |
| 20 | ppb | OCHEM PPB `API` | **3 ✔** |
| 21 | solubility | SFI | **4 ✔** |
| 22 | lipophilicity | RDKit Crippen | **4 ✔** |
| 23 | lipophilicity | OPERA | **4 ✔** |
| 24 | lipophilicity | SwissADME `WEB-SUBSTITUTABLE` | **4 ✔** |
| 25 | permeability | *(no own model — generalists + BOILED-Egg)* | **4 ✔** |
| 26 | structural_alerts | PAINS / BRENK | **4 ✔** |
| 27 | synthesizability | SAscore | **4 ✔** |
| 28 | synthesizability | RAscore | **4 ✔** |
| 29 | synthesizability | AiZynthFinder | **4 ✔** |
| 30 | toxicity | toxicophores (structural alerts) | **4 ✔** |
| 31 | toxicity | ProTox 3.0 `WEB` | **4 ✔** |
| 32 | druglikeness | Lipinski / Veber / QED | **4 ✔** |
 
---
 
## B. Per-model verified records — Batch 1
 
### Endpoint: TRIAGE (cross-cutting generalists)
 
---
 
#### 1. ADMET-AI  ✔ CONFIRMED (with a version-drift flag)
 
1. **Identity & existence.** Chemprop-based multi-endpoint ADMET predictor trained on 41 TDC datasets.
   Primary repo: `https://github.com/swansonk14/admet_ai` (exists, MIT). Paper: Swanson et al.,
   *Bioinformatics* 40(7):btae416 (2024), `https://doi.org/10.1093/bioinformatics/btae416`. Live web server:
   `https://admet.ai.greenstonebio.com`.
2. **Access method.** **CODE-PKG confirmed** — PyPI (`pip install admet-ai`) and installable from source. Also
   CLI (`admet_predict`) and web (`admet_web`). Tag in skeleton is correct.
3. **Invoke.** Python: `from admet_ai import ADMETModel; ADMETModel().predict(smiles)` → dict (single) or
   DataFrame (list). CLI: `admet_predict --data_path in.csv --save_path out.csv --smiles_column smiles`.
4. **Install.** `pip install admet-ai` (web extras: `admet-ai[web]`). `requires-python >=3.11`; classifiers
   list 3.11–3.14. GPU auto-used if present, CPU fine. Latest release **v2.0.1 "Fixing models on Linux/CUDA"
   (22 Feb 2026)** — directly relevant to Rosenbluth's Linux+CUDA box. Source:
   `https://github.com/swansonk14/admet_ai`.
5. **Full dependency list (authoritative, v2).** From `pyproject.toml`
   (`https://github.com/swansonk14/admet_ai/blob/main/pyproject.toml`): `chemprop>=2.2.2`, `lightning`,
   `numpy`, `pandas`, `rdkit>=2025.9.5`, `seaborn`, `torch>=2.8.0`, `tqdm>=4.66.3`,
   `typed-argument-parser>=1.11.0`; web extra: `flask`, `gunicorn>=22.0.0`. A pinned `requirements_frozen.txt`
   is also provided in-repo for exact reproduction. **Age risk: none — this is a very current stack**
   (torch ≥2.8, rdkit ≥2025.9). The *v1* line, by contrast, pinned `chemprop==1.6.1` (setup.py of the v1 tag).
6. **Repo health.** ~315–321 stars, ~81 forks, 231 commits, 9 releases, 1 open issue, MIT, default branch
   `main`, not archived, latest release Feb 2026. **Verdict: HEALTHY.**
7. **Verdict & flags → KEEP.** ⚠️ **Material discrepancy vs. the skeleton.** The skeleton describes ADMET-AI as
   *"Chemprop-RDKit D-MPNN … 41 ADMET + 8 RDKit physchem; percentile-vs-approved-drugs context."* That is
   **ADMET-AI v1**. The repo now ships **v2 (Chemprop v2, no RDKit fingerprints)**; the maintainers state the
   models were retrained from scratch and *"predictions of v2 will not exactly match v1."* The paper and the
   live web server are still v1. **Decision needed:** to reproduce the skeleton's documented behavior (and the
   TDC-leaderboard "best average rank" claim), pin **v1.4.0** at commit
   `9c8430862b2afd997ff1d314b30bda4418fa9b33`; to use the current/faster stack, adopt v2 and update the
   skeleton's description + any downstream percentile logic. Either is defensible, but it must be a conscious
   choice and recorded in the model's provenance README.
8. **Citations.** Repo, pyproject.toml, releases, `docs/reproduce.md`, Bioinformatics paper, greenstonebio
   web server — all under `github.com/swansonk14/admet_ai` and the DOI above.
---
 
#### 2. ADMETlab 3.0  ✔ CONFIRMED (access tag correct; add a stability caveat)
 
1. **Identity & existence.** Comprehensive online ADMET platform, 119 endpoints, multi-task DMPNN + molecular
   descriptors, evidential-deep-learning uncertainty. Paper: Fu et al., *Nucleic Acids Research* 52(W1):W422–
   W431 (2024), `https://doi.org/10.1093/nar/gkae236`. Site: `https://admetlab3.scbdd.com` (free, no
   registration).
3. **Access method.** **CODE-API confirmed** — the 3.0 release explicitly added an API for off-website batch
   prediction returning all 119 properties + confidence labels; DMPNN or DMPNN-Des selectable. Skeleton tag is
   correct. Source: NAR paper (Fig. 4 shows a Python API example) and site help/API section.
4. **Invoke.** HTTP POST of SMILES to the site's batch API; returns per-endpoint values + decision-state
   dots + uncertainty. **Exact endpoint path & request/response JSON: UNVERIFIED here — read from the site's
   API tutorial at build time.** A third-party wrapper (`ToxMCP/admetlab-mcp`) documents it hitting `/api/admet`
   with fallback to `/api/single/admet`, batching ≤1000 SMILES, ≤5 rps — useful as a reference implementation,
   not authoritative.
5. **Install.** No local install (hosted service; the API is an HTTP client). Organ-tox heads confirmed present
   and matching the skeleton: nephro, neuro, oto, hemato, genotox, hERG, RPMI-8226 immuno, A549/HEK293 cyto.
6. **Repo/service health.** Actively used platform (2.0 cited ~1000×; site >1.7M visits per the 3.0 paper).
   **Verdict: HEALTHY as a service — but see caveat.**
7. **Verdict & flags → KEEP as CODE-API.** ⚠️ **Caveat: upstream stability.** The `admetlab-mcp` wrapper's
   README reports the official site "currently reports instability; expect occasional 5xx/404." Because this is
   an external dependency in the bulk loop, wrap calls with retry/backoff + a fallback endpoint list, cache raw
   responses to the ledger, and **pin/record which model (DMPNN vs DMPNN-Des) is used** for reproducibility.
   No API key is required today (site is open), but the wrapper reserves a header for future auth — watch for
   that.
8. **Citations.** NAR paper (Oxford + HKBU mirror), `admetlab3.scbdd.com`, `github.com/ToxMCP/admetlab-mcp`.
---
 
#### 3. OpenADMET  ✔ CONFIRMED — but it is a **framework + baseline models**, not a turnkey predictor
 
1. **Identity & existence.** Open-science consortium (OMSF, UCSF, Octant Inc, MSKCC; funded by ARPA-H, Gates
   Foundation, Schrödinger, Astera). GitHub org: `https://github.com/OpenADMET`. The code package the skeleton
   means is **`OpenADMET/openadmet-models`** (`https://github.com/OpenADMET/openadmet-models`, MIT), with
   supporting `openadmet-toolkit`, the `anvil` training infra, `openadmet-demos`, docs at
   `https://docs.openadmet.org`.
2. **Access method.** **CODE-PKG confirmed** (conda/mamba env + pip install from source). Skeleton's "CODE-PKG
   (HF/GitHub) — reference, esp. CYP" is correct in spirit but should be sharpened (see flags).
3. **Invoke.** It is a *modeling framework*: curate data → train models (LightGBM / Chemprop / ensembles /
   active learning) via YAML "anvil" recipes → run inference. Released baseline models (CYP inhibition &
   reaction phenotyping: CYP3A4, CYP2J2, plus CYP1A2/2D6/2C9/PXR/AhR multitask) can be run for inference. There
   is no single `predict(smiles)` turnkey entry point equivalent to ADMET-AI.
4. **Install.** `mamba env create -f devtools/conda-envs/openadmet-models.yaml` (GPU variant:
   `openadmet-models-gpu.yaml`), then install the library. Source: `github.com/OpenADMET/openadmet-models`.
5. **Full dependency list.** **UNVERIFIED here — read `devtools/conda-envs/openadmet-models.yaml` at build
   time** (not opened this pass). Known stack from docs/demos: RDKit, Chemprop, scikit-learn/LightGBM, plus
   `anvil` and `intake` for the recipe/data layer.
6. **Repo health.** Active org, multiple repos with recent commit activity; inaugural public model release
   Dec 2025. **Verdict: HEALTHY but EARLY-STAGE.**
7. **Verdict & flags → KEEP as reference, not authority.** ✔ **The skeleton's "reference not authority /
   cluster-split R²≈0.1" framing is directly confirmed by the maintainers' own inaugural-release write-up:**
   random-split R²~0.6 vs **cluster-split R²~0.1**, i.e. poor generalization to out-of-distribution chemical
   space — exactly the failure mode that matters for the OOD oxetane chemotype. Sharpen the skeleton entry:
   OpenADMET = *training framework + young baseline CYP models*, best used (a) as a CYP metabolism reference and
   (b) potentially to **train an in-series model via anvil once measured T-series data exists** (ties to the
   §12 data ask). **Verify at build time** whether pre-trained weights are downloadable from the HuggingFace
   `openadmet` org or must be retrained.
8. **Citations.** `github.com/OpenADMET`, `github.com/OpenADMET/openadmet-models`, `docs.openadmet.org`,
   inaugural release post `https://openadmet.ghost.io/openadmets-inaugural-model-release/`, Octant CYP data
   blog `https://openadmet.github.io/Octant_CYP_blog_post/`.
---
 
### Endpoint: hERG / CARDIOTOXICITY — PRIMARY GO/NO-GO GATE
 
---
 
#### 4. BayeshERG  ✔ CONFIRMED (env-age risk)
 
1. **Identity & existence.** Bayesian graph neural network for hERG blocker probability + calibrated
   uncertainty. Repo: `https://github.com/GIST-CSBL/BayeshERG` (official). Paper: Kim et al., *Briefings in
   Bioinformatics* 23(4):bbac211 (2022), `https://doi.org/10.1093/bib/bbac211`.
2. **Access method.** **CODE-PKG confirmed** — repo ships the PyTorch implementation + trained weights and a
   conda `environment.yml`. Skeleton tag correct.
3. **Invoke (VERIFIED from README).** `python main.py -i input.csv -o out_name -c {cpu|gpu} -t <sampling_time>`
   (input CSV needs a `smiles` column; `-t` = number of MC-dropout samples, default 30). Output appends **three**
   columns: `score`, **`alea`** (aleatoric) and **`epis`** (epistemic) uncertainty — i.e. it separates the two
   uncertainty types, which is *better* than "MC-dropout uncertainty" implies and useful for the split-case
   adjudicator. Also emits per-molecule attention `.svg` images.
4. **Install.** `conda env create --name BayeshERG --file=environment.yml`. **Python 3.6 + `dgl` + `pytorch` +
   `rdkit`.**
5. **Full dependency list.** Core = dgl, pytorch, rdkit (README). Exact pins still in `environment.yml`
   (py3.6-era → old dgl/torch); a literal build-time read, but the decision-relevant fact (legacy py3.6 stack)
   is confirmed.
6. **Repo health (VERIFIED).** 92 commits, **last modified 2022-11-18**, 16 stars, 7 forks, **no releases
   published**, Python 100%. ⚠️ **License is DUAL:** source code is **MIT**, but the **trained model weights**
   (and any hERG hits found with them) are **CC-BY-NC-4.0 — academic/individual use only, no commercial use.**
   Since you must use the shipped weights to run it, treat the usable artifact as non-commercial (fine for an
   academic UCSD program; record it in provenance). **Verdict: STALE-BUT-USABLE (legacy env; NC weights).**
7. **Verdict & flags → KEEP (isolated legacy env).** ⚠️ **Two flags.** (a) **Dependency-age risk:** the
   Python-3.6 + DGL + old-PyTorch stack is a known-painful combo on a modern (575.x) CUDA driver; it likely
   needs a pinned legacy env and may end up **CPU-only** or on an old CUDA build. This is exactly why the
   per-model isolation mandate matters. (b) **Uncertainty-quality caveat:** independent 2024 work (AttenhERG,
   *J. Cheminformatics* 16:143) states BayeshERG's uncertainty estimation and accuracy "require considerable
   improvement." Since the aggregator leans on BayeshERG's uncertainty to break hERG ties, treat a
   high-uncertainty disagreement as "measure it," not as a resolved call. **Fallback:** an Ersilia port exists
   (`ersilia-os/eos4tcc`) that may be easier to run than the legacy env — evaluate if the native install fights
   the CUDA driver.
8. **Citations.** `github.com/GIST-CSBL/BayeshERG`, BiB paper (Oxford/PubMed), BioModels MODEL2408060001,
   AttenhERG paper `https://doi.org/10.1186/s13321-024-00940-y`.
---
 
#### 5. CardioTox net  ✔ CONFIRMED (clean package; TF-age risk)
 
1. **Identity & existence.** Deep-learning meta-feature ensemble for hERG blocker classification. Repo:
   `https://github.com/Abdulk084/CardioTox` (official). Paper: Karim et al., *J. Cheminformatics* 13:60 (2021),
   `https://doi.org/10.1186/s13321-021-00541-z`.
2. **Access method.** **CODE-PKG confirmed** — importable `cardiotox` package with a clean API. Skeleton tag
   correct; this is the healthiest, most drop-in hERG model in the gate.
3. **Invoke.** `import cardiotox; m = cardiotox.load_ensemble(); m.predict(smiles_or_list)`. Individual base
   models also exposed (`DescModel`, `SVModel`, `FVModel`, `FingerprintModel`); each self-preprocesses.
4. **Install.** From repo. **OS Ubuntu 20.04, Python 3.7.7** per the paper's software section.
5. **Full dependency list.** **UNVERIFIED exact pins — read the repo's `requirements.txt`/`environment.yml` at
   build time.** Given the 3.7.7 era and DNN base models, expect an **old TensorFlow/Keras** pin → isolated env
   required; flag TF version explicitly when read.
6. **Repo health.** Stable/complete research repo (2021). **Verdict: STALE-BUT-USABLE (clean API offsets age).**
7. **Verdict & flags → KEEP (core ensemble member).** No blocking issues; the meta-feature ensemble (physchem +
   fingerprints + SMILES/fingerprint embeddings) matches the skeleton's ENSEMBLE role. This is the model that
   makes **DeepHIT redundant** — see #6.
8. **Citations.** `github.com/Abdulk084/CardioTox`, J. Cheminf. paper (Springer/PMC8365955).
---
 
#### 6. DeepHIT  `VERIFY` → **RESOLVED: DROP (no primary code repo; redundant with CardioTox net)**
 
1. **Identity & existence.** Three-model deep framework (descriptor DNN + fingerprint DNN + graph GCN), tuned
   for sensitivity/NPV (fewer false negatives) + an in-silico chemical-transformation module. Paper is real and
   solid: Ryu et al., *Bioinformatics* 36(10):3049–3055 (2020),
   `https://doi.org/10.1093/bioinformatics/btaa075`.
2. **Access method.** ⚠️ **No primary code repository located.** "[Code]" links in aggregator lists
   (`benb111/awesome-small-molecule-ml`) do not resolve to an authoritative author repo; searches surface only
   (a) an unrelated *Dynamic-DeepHit* survival-analysis repo (`chl8856/Dynamic-DeepHit` — different tool,
   different authors) and (b) `ncats/herg-ml`, a *different* consensus model that merely benchmarks against
   DeepHIT. DeepHIT was distributed by the KRICT group as a **web server**, not a package.
6. **Repo health.** **Verdict: MISSING (code repo).**
7. **Verdict & flags → DROP (do not build an adapter).** The skeleton already flags DeepHIT as VERIFY and
   "redundant with CardioTox net." Confirmed on both counts: no installable primary repo, and CardioTox net's
   own paper benchmarks DeepHIT and reports it "struggles with aggregation" and underperforms on MCC/ACC/PPV/SPE
   (strong on NPV/SEN only). CardioTox net fills the identical sensitivity-tuned-ensemble role with a clean pip
   package. **Recommendation: remove from the funnel** (or, if a sensitivity-max second opinion is ever wanted,
   use the KRICT web server on the shortlist only). *Honesty caveat:* absence of a repo in search is not
   absolute proof none exists; if DeepHIT is deemed important, confirm with the authors — but given redundancy,
   the effort is not worth it.
8. **Citations.** Bioinformatics paper (Oxford/PubMed/Semantic Scholar), `github.com/ncats/herg-ml`,
   `github.com/benb111/awesome-small-molecule-ml`.
---
 
#### 7. CardioDPi  `VERIFY` → **RESOLVED: web/shortlist secondary, or substitute CToxPred2 in code**
 
1. **Identity & existence.** Explainable multichannel model (hERG, CaV1.2, NaV1.5), feedforward NN + molecular
   fingerprints, structural-alert explainability; trained on ~15,840 compounds. Paper is real: Zhang et al.,
   *J. Hazardous Materials* 474:134724 (2024), `https://doi.org/10.1016/j.jhazmat.2024.134724`.
2. **Access method.** ⚠️ **No primary code repo confirmed — appears web-server-distributed** (the paper
   describes an "easy-to-use CardioDPi system"). Matches the skeleton's "likely web server; secondary check
   only."
6. **Repo health.** **Verdict: WEB-ONLY (code repo unconfirmed).**
7. **Verdict & flags → KEEP as web/shortlist secondary, OR substitute.** Since CardioDPi is a non-blocking
   secondary explainability layer (not in the bulk loop, per skeleton), leaving it as a manual web check on the
   shortlist is fine. **New finding (better option for in-code use):** `https://github.com/issararab/CToxPred2`
   (Arab et al., *JCIM* 2023, `https://doi.org/10.1021/acs.jcim.3c01301`) is a maintained, clonable,
   user-friendly tool covering the **same three channels** (hERG, NaV1.5, CaV1.2) *with* uncertainty framing and
   a prediction notebook — a superior in-code substitute if you want an automatable multichannel secondary.
   `CUPID` (XAI, same 3 channels) is a further option. **Recommendation:** if the multichannel secondary needs
   to be in-code, adopt **CToxPred2** and retire CardioDPi; otherwise keep CardioDPi web-on-shortlist.
8. **Citations.** J. Hazard. Mater. paper (ScienceDirect), `github.com/issararab/CToxPred2`, CUPID (ResearchGate
   390280441).
---
 
#### 8. CardioGenAI  ✔ CONFIRMED (validates the binding/selectivity gate)
 
1. **Identity & existence.** Generative + discriminative framework to re-engineer hERG-active compounds for
   reduced hERG (and NaV1.5/CaV1.2) liability while preserving pharmacological activity. Repo:
   `https://github.com/gregory-kyro/CardioGenAI` (official, open-source). Paper: Kyro et al., *J.
   Cheminformatics* 17 (2025), `https://doi.org/10.1186/s13321-025-00976-8` (preprint arXiv:2403.07632).
2. **Access method.** **CODE-PKG confirmed** (clone + import). Skeleton tag correct.
3. **Invoke.** `from src.Optimization_Framework import optimize_cardiotoxic_drug;
   optimize_cardiotoxic_drug(input_smiles, herg_activity, nav_activity, cav_activity, n_generations, device)`.
   Generates candidates conditioned on scaffold + physchem, then filters with hERG/NaV1.5/CaV1.2 discriminative
   models. `device` arg → GPU-capable.
4. **Install.** From repo. **Dependency pins UNVERIFIED — read at build time** (transformer + GNN stack;
   ~5M-datapoint training set for the generative model).
6. **Repo health.** Recent (2024–2025), open-source, published in J. Cheminf. **Verdict: HEALTHY (assume;
   confirm commit/issues at build time).**
7. **Verdict & flags → KEEP as POINTER, GATED — confirmed correct.** ✔ CardioGenAI's discriminative models
   cover hERG/NaV1.5/CaV1.2 **but have no notion of FTO binding or FTO-vs-ALKBH5 selectivity** — it preserves
   only *generic* scaffold/physchem similarity. This directly **validates the skeleton's requirement** that
   CardioGenAI output be filtered against Kunhuan's binding + selectivity arm before any redesigned analog is
   taken seriously. Bonus: its standalone hERG/NaV/CaV **discriminative** predictors "can serve independently in
   virtual screening" — they could optionally join the gate ensemble as extra votes.
8. **Citations.** `github.com/gregory-kyro/CardioGenAI`, J. Cheminf. paper (Springer/PMC11881490),
   arXiv:2403.07632.
---
 
## C. Summary table — Batch 1
 
| Model | Confirmed access | Install one-liner | Health | Action |
|---|---|---|---|---|
| ADMET-AI | CODE-PKG (PyPI) ✔ | `pip install admet-ai` | HEALTHY | KEEP — **pinned v2** (excl. VDss/t½ heads) |
| ADMETlab 3.0 | CODE-API ✔ | HTTP client (no install) | HEALTHY (svc) | KEEP — retry/backoff + cache; stability caveat |
| OpenADMET | CODE-PKG (conda) ✔ | `mamba env create -f …/openadmet-models.yaml` | HEALTHY / early | KEEP as reference; confirm HF weights |
| BayeshERG | CODE-PKG (conda) ✔ | conda env from `environment.yml` | STALE-USABLE | KEEP — legacy env; Ersilia `eos4tcc` fallback |
| CardioTox net | CODE-PKG ✔ | clone + `import cardiotox` | STALE-USABLE | KEEP — core ensemble member |
| DeepHIT | none found ✖ | — | MISSING (repo) | **DROP** — redundant w/ CardioTox net |
| ~~CardioDPi~~ → **CToxPred2** | CODE-PKG ✔ (`issararab/CToxPred2`) | clone + notebook/GUI | HEALTHY | **REPLACES CardioDPi** — in-code, 3 channels, ships uncertainty |
| CardioGenAI | CODE-PKG ✔ | clone repo | HEALTHY | KEEP — POINTER, gate on binding+selectivity |
 
---
 
## D. Flags & actions — Batch 1
 
**VERIFY resolutions (both requested explicitly):**
- **DeepHIT → DROP.** No primary installable repo; web-server-only historically; redundant with (and
  benchmarked below) CardioTox net. Remove from funnel.
- **CardioDPi → web/shortlist secondary, or substitute CToxPred2.** Non-blocking secondary; no confirmed repo.
  `issararab/CToxPred2` is a maintained in-code alternative covering the same three channels with uncertainty.
**Discrepancies vs. the settled docs:**
- **ADMET-AI v1 vs v2 (material).** Skeleton describes v1 (Chemprop-RDKit, 41 ADMET + 8 physchem, DrugBank
  percentiles); the installable repo is now v2 (Chemprop v2, no RDKit fingerprints, retrained → different
  predictions). **Action:** decide + pin (v1 commit `9c8430862b2afd997ff1d314b30bda4418fa9b33` for
  paper-faithful behavior, or adopt v2 and update the skeleton).
- **ADMET-AI file drift (minor).** The repo moved from `setup.py` (v1) to `pyproject.toml` + `requirements_frozen.txt`
  (v2); a stale `setup.py` URL still appears in search but 404s live. Read `pyproject.toml` as authoritative.
- **OpenADMET framing (minor sharpening).** It's a *training framework + young baseline models*, not a turnkey
  predictor; the "reference not authority" call is validated by its own cluster-split R²≈0.1. Confirm whether
  pre-trained weights are on HuggingFace or must be retrained.
- **ADMETlab 3.0 API stability (operational).** Real API, but upstream reportedly unstable; needs
  retry/backoff, fallback endpoints, response caching, and model-choice pinning.
**New candidate tools surfaced (not in either settled doc — for Aaran/Gilson to consider):**
- `issararab/CToxPred2` — in-code multichannel (hERG/NaV1.5/CaV1.2) with uncertainty (CardioDPi substitute).
- `ersilia-os/eos4tcc` — Ersilia-packaged BayeshERG port (possible easier install than the legacy env).
- `ncats/herg-ml` — NCATS consensus hERG model + curated data (potential extra gate vote / benchmark set).
**Dependency-age watchlist (isolated envs mandatory):** BayeshERG (py3.6 + DGL + old torch) and CardioTox net
(py3.7.7 + likely old TF) are the two legacy stacks in the gate; plan for possible CPU-only or old-CUDA builds
and read their exact pins first. ADMET-AI/CardioGenAI/OpenADMET are modern.
 
---
 
## B (cont.). Per-model verified records — Batch 2
 
### Endpoint: METABOLISM — site of metabolism (RETAINED, sole-provider)
 
---
 
#### 9. SMARTCyp 3.0  ✔ CONFIRMED — ⚠️ **ACCESS TAG WRONG in both settled docs (it is Python, not Java)**
 
1. **Identity & existence.** First-principles site-of-metabolism predictor: DFT-derived activation energies +
   SMARTS reactivity rules; ranks the atom a CYP is most likely to attack (3A4, with 2C9/2D6 via isoform
   corrections). Paper (3.0): Olsen, Montefiori, Tran, Jørgensen, *Bioinformatics* 35(17):3174–3175 (2019),
   `https://doi.org/10.1093/bioinformatics/btz037`. Original (1.0): Rydberg, Gloriam, Olsen, *Bioinformatics*
   26(23):2988 (2010). Server + source: `smartcyp.sund.ku.dk` / `www.farma.ku.dk/smartcyp`.
2. **Access method.** ⚠️ **CORRECTION.** Skeleton §7 and codebase §5 both tag SMARTCyp 3.0 as
   **CODE-STANDALONE (Java CLI)**. Primary source contradicts this: **only SMARTCyp 1.x/2.x were Java + CDK;
   SMARTCyp 3.0 was rewritten in Python 3 using RDKit** (web server on Flask). Correct tag → **CODE-PKG /
   CODE-STANDALONE (Python + RDKit)**. This is a *simplification*: SMARTCyp 3.0 needs **no JVM** and can live in
   an ordinary RDKit env. (The only metabolism model that needs Java is the *original* FAME 3 — and its verified
   Python substitute **FAME3R** (#10) removes even that, so metabolism can be fully Java-free.)
3. **Invoke.** Python/RDKit program; SMILES/SDF in → per-atom ranking table (soft-spot ranking) out.
4. **Install (VERIFIED channel).** **No official PyPI package** for SMARTCyp 3.0. Two real options: (a) download
   the Python-3/RDKit source from **`smartcyp.sund.ku.dk`**; or (b) use the third-party wrapper
   **`MD-Studio/MDStudio_SMARTCyp`** — pip-installable locally, ships the SMARTCyp software, and exposes it as a
   **REST microservice** (also a Docker image), which fits the pipeline's uniform-adapter pattern cleanly. (The
   `cdk/smartcyp` repo is the *legacy Java/CDK* line, LGPL — confirms the Java=old-version split; do not use it
   for 3.0.)
5. **Full dependency list.** Core: RDKit (per the 3.0 paper). Exact pins **UNVERIFIED — read from the 3.0
   source at build time.** Low risk (RDKit-only, rule/energy-based — no ML training, no heavy DL stack).
6. **Repo health.** Method is static/first-principles; server maintained by U. Copenhagen. **Verdict:
   STALE-BUT-USABLE (stable by design).**
7. **Verdict & flags → KEEP; correct the access tag to Python/RDKit.** Confirms skeleton's "rule-based
   precomputed reactivity, no training" and its RETAINED-on-sole-provider status (answers *where* the soft spot
   is, complementing generalist "is it stable"). **Action:** update both settled docs' access tag; drop the
   Java-runtime assumption from SMARTCyp's env plan.
8. **Citations.** Bioinformatics 3.0 paper (Oxford/PubMed 30657882), 1.0 paper (PubMed 20947523),
   `smartcyp.sund.ku.dk`.
---
 
#### 10. FAME 3  ✔ CONFIRMED (Java tag correct; two flags)
 
1. **Identity & existence.** Extra-trees (random-forest-family) atom classifier for phase 1 & phase 2 SoM,
   trained on MetaQSAR (>2100 substrates, >6300 experimental SoMs) with a FAMEscore applicability-domain
   measure. Paper: Šícho, Stork, Mazzolari, de Bruyn Kops, Pedretti, Testa, Vistoli, Svozil, Kirchmair, *JCIM*
   59(8):3400–3412 (2019), `https://doi.org/10.1021/acs.jcim.9b00376`. Web: `nerdd.zbh.uni-hamburg.de`.
2. **Access method.** **CODE-STANDALONE (Java) — CONFIRMED.** Self-contained Java package (CDK + WEKA), CLI +
   web-page + CSV output. Skeleton tag is correct here (contrast SMARTCyp).
3. **Invoke.** Java CLI on SMILES/SDF → per-atom SoM ranking + FAMEscore; also embeddable via the VEGA ZZ
   plug-in. Wrap the jar behind the pipeline's uniform `run.py`.
4. **Install.** Download the self-contained Java package from the Hamburg group (nerdd / zbh); requires a **JVM**
   (confirm Java version against the distribution). This is the one metabolism model that needs Java in its env.
5. **Full dependency list.** Bundled Java deps: CDK + WEKA (self-contained). Exact Java/lib versions
   **UNVERIFIED — read from the distribution at build time.**
6. **Repo health.** Stable research distribution (2019); Hamburg NERDD service active. **Verdict:
   STALE-BUT-USABLE.**
7. **Verdict & flags → PREFER FAME3R over the Java FAME 3.** ⚠️ **(a) License:** the original Java FAME 3 is
   *free for academic/noncommercial* only — not OSI-open. ✔ **(b) FAME3R substitute — VERIFIED and strongly
   recommended:** `https://github.com/molinfo-vienna/FAME3R` is **Python 100%, MIT-licensed, published on both
   PyPI (`pip install fame3r`) and conda-forge (`conda install -c conda-forge fame3r`)**, with CI, tests, docs,
   239 commits, 7 tagged releases, `pyproject.toml` + `uv.lock`. It is a maintained RF re-design of the FAME 3
   SoM model. Adopting it **eliminates the Java+WEKA stack *and* the non-commercial license.**
   **Consequence (updates §E.4):** with SMARTCyp 3.0 (Python/RDKit) + **FAME3R (Python/pip/conda-forge)**, the
   **entire metabolism endpoint is Java-free — no JVM needed anywhere in metabolism.** Keep the Java FAME 3 only
   as a cross-check/benchmark if desired.
8. **Citations.** JCIM paper (ACS/figshare), OpenRiskNet FAME 3 service page, VEGA ZZ FAME plug-in manual,
   `github.com/molinfo-vienna/FAME3R` (repo verified: MIT, PyPI + conda-forge).
---
 
### Endpoint: CLEARANCE — weakest endpoint; decomposed, never a single number
 
---
 
#### 11. Watanabe renal fe/CLr (via DruMAP)  ✔ CONFIRMED — WEB-ONLY (no API/package found)
 
1. **Identity & existence.** In-silico human renal excretion/clearance system: fraction excreted unchanged in
   urine (fe, binary classifier) + renal clearance CLr, using fraction-unbound-in-plasma (fu,p) as a descriptor.
   Model paper: Watanabe et al., 2019 (renal excretion & clearance from structure incorporating fu,p). Hosted on
   **DruMAP**: Kawashima et al., *J. Med. Chem.* 66(14):9697–9709 (2023),
   `https://doi.org/10.1021/acs.jmedchem.3c00481` (NIBIOHN / Mizuguchi group).
2. **Access method.** **WEB-ONLY — CONFIRMED.** DruMAP is a web application; no public API or downloadable
   package was found. Corroborating signal that the models are *not* openly redistributable: the DruMAP models
   have been licensed into Fujitsu's commercial **SCIQUICK** platform. Skeleton's WEB-ONLY / shortlist-manual
   decision stands.
3. **Invoke (manual SOP).** Open the DruMAP web app (NIBIOHN; confirm current URL at build time) → submit the
   shortlist SMILES → read the **fe** class and **CLr** value; also capture **fu,p** (DruMAP predicts it and it
   feeds the renal model). Transcribe results into the run ledger by hand.
4. **Install.** None (web).
5. **Dependencies.** N/A (hosted). Note: DruMAP is a *multi-parameter* platform — the same site also hosts
   CLint (liver microsome), Fa, fu,brain, and **Kp,uu,brain** + the **P-gp brain-efflux** model (#19, Batch 3),
   so one DruMAP shortlist session can service several endpoints at once.
6. **Repo/service health.** Actively maintained gov-institute platform (2023 paper). **Verdict: HEALTHY as a
   service; WEB-ONLY.**
7. **Verdict & flags → KEEP web-on-shortlist; rebuild not worth it.** Confirms skeleton. The renal-vs-hepatic
   fork is resolved experimentally, not by this model; use DruMAP fe/CLr as a triage read only. If an in-code
   renal flag is ever needed, the skeleton's "lightweight in-house fe classifier" remains the fallback (the
   Watanabe fe model is a modest binary classifier, bal. acc ≈0.74).
8. **Citations.** DruMAP J. Med. Chem. paper (ACS/PMC10388294), NIBIOHN/ArCHER project page, Watanabe 2019
   renal model (referenced therein).
---
 
#### 12. PKSmart  ✔ CONFIRMED (citation update; Mordred build flag)
 
1. **Identity & existence.** Open-source model predicting human i.v. PK (VDss, CL, t½, fu, MRT) from structure,
   **with a fold-error estimate**. Repo: `https://github.com/srijitseal/PKSmart` (Seal / Bender group). Web:
   `https://broad.io/PKSmart`. Paper — **now peer-reviewed**: Seal et al., *J. Cheminformatics* 17 (2025),
   `https://doi.org/10.1186/s13321-025-01066-5` (was bioRxiv 2024.02.02.578658 — **update the skeleton's
   citation**).
2. **Access method.** **CODE-PKG — CONFIRMED** (all code downloadable for local use; also a web tool). Tag
   correct.
3. **Invoke.** Structure in → VDss/CL/t½/fu/MRT + **fold-error / prediction range** (DIRECT uncertainty,
   similarity-to-training-space dependent). Two-stage RF: predict animal PK (rat/dog/monkey) → feed as features
   to human RF. Confirms skeleton's "two-stage RF (animal→human)."
4. **Install.** Python; clone repo. Exact pins **UNVERIFIED — read `requirements.txt`/env at build time.**
5. **Full dependency list.** Core features: **Morgan fingerprints (RDKit) + Mordred descriptors + scikit-learn
   Random Forest.** ⚠️ **Build flag:** upstream **Mordred is unmaintained** on modern Python — use the
   maintained **`mordredcommunity`** fork, and pin RDKit/scikit-learn to versions compatible with the released
   model pickles (RF pickles are sklearn-version-sensitive → pin sklearn to avoid unpickling breakage).
6. **Repo health.** Published 2025, code released. **Verdict: HEALTHY (confirm commit/issues at build time).**
7. **Verdict & flags → KEEP.** ✔ **Skeleton's weak-CL characterization is validated from primary source:**
   clearance GMFE = **2.43**, R² = **0.31** (repeated nested CV; external test a bit better at GMFE 1.98,
   R² 0.45). So "coarse binning + relative within-series ranking only" for CL is correct — do **not** use the
   absolute CL number as actionable. Fold-error must be surfaced, not hidden.
8. **Citations.** J. Cheminf. 2025 paper (Springer/PMC12466039), bioRxiv preprint, `github.com/srijitseal/PKSmart`.
---
 
#### 13. PBPK (Open Systems Pharmacology — PK-Sim / MoBi)  ✔ CONFIRMED — ⚠️ **R/.NET, not Python**
 
1. **Identity & existence.** Whole-body PBPK simulation engine (an integrator, not a trained predictor). Org:
   `https://github.com/Open-Systems-Pharmacology` — **PK-Sim** (whole-body PBPK) + **MoBi** (systems-biology /
   full customization), formerly-commercial tools now open-source. Community paper: Lippert et al., *CPT Pharm.
   Syst. Pharmacol.* (2019), PMC6930856.
2. **Access method.** **CODE — CONFIRMED, but qualified.** GPLv2, all source public, free incl. commercial.
   Scripting is via the **`ospsuite` R package** (load/manipulate/simulate PKML models, evaluate Cmax/AUC) —
   *not* a Python package. Skeleton's "open scriptable engines, e.g. OSP/PK-Sim" is correct; sharpen it to note
   the supported scripting path is **R**, and a Python interface is comparatively immature (confirm at build
   time).
3. **Invoke.** Build/parameterize a PBPK model in PK-Sim (GUI) or from PKML; drive simulations via `ospsuite`
   (R). On the shortlist only — this is the concentration-time integrator that consumes the other endpoints'
   outputs (CL, fu, permeability), not a bulk-loop predictor.
4. **Install.** ⚠️ **Heaviest non-Python dependency in the pipeline:** requires **R 4.x + .NET 8 + Visual C++
   redistributable**, Windows or **Linux/Ubuntu** (Rosenbluth-compatible). `ospsuite` is **not on CRAN**
   (binaries) → install from GitHub/archive. Install the OSP Suite binaries from
   `setup.open-systems-pharmacology.org`.
5. **Dependencies.** R 4.x, .NET 8, OSP Suite binaries (PK-Sim/MoBi), `ospsuite` + companion R packages.
6. **Repo health.** Very active org (~399 repos, ongoing releases). **Verdict: HEALTHY.**
7. **Verdict & flags → KEEP as POINTER (out of bulk loop).** Confirms skeleton. **Env-plan flag:** this is the
   one endpoint that breaks the "Python everywhere" model — isolate it as an R/.NET tool driven out-of-band
   (its own non-pixi/conda environment, or a documented manual PK-Sim workflow), with results transcribed to the
   ledger like the web-only tools. Given the CNS indication + possible intratumoral delivery, PBPK is a
   late-stage shortlist tool, not an early triage need.
8. **Citations.** `github.com/Open-Systems-Pharmacology` (Suite, PK-Sim), OSP FAQ (open-systems-pharmacology.org),
   ospsuite GlobalSensitivity paper (Wiley psp4.13256), community paper (PMC6930856).
---
 
## C (cont.). Summary table — Batch 2
 
| Model | Confirmed access | Install one-liner | Health | Action |
|---|---|---|---|---|
| SMARTCyp 3.0 | **CODE-PKG (Python/RDKit)** — *not Java* | Python+RDKit (confirm channel) | STALE-USABLE | KEEP — **fix access tag** |
| ~~FAME 3~~ → **FAME3R** | CODE-PKG ✔ (Python, MIT) | `pip install fame3r` / conda-forge | HEALTHY | **ADOPT FAME3R** (removes Java + the non-commercial license); keep Java FAME 3 only as an optional benchmark |
| Watanabe renal (DruMAP) | WEB-ONLY ✔ | none (web) | HEALTHY (svc) | KEEP web-on-shortlist |
| PKSmart | CODE-PKG ✔ | clone `srijitseal/PKSmart` | HEALTHY | KEEP — use `mordredcommunity`; pin sklearn |
| PBPK (OSP) | CODE (R/.NET) ✔ | R 4.x + .NET 8 + OSP binaries | HEALTHY | KEEP — POINTER; isolate as R/.NET |
 
---
 
## D (cont.). Flags & actions — Batch 2
 
**Discrepancies vs. the settled docs:**
- **SMARTCyp 3.0 access tag is wrong (material).** Both docs say Java; 3.0 is **Python + RDKit** (only 1.x/2.x
  were Java+CDK). **Action:** correct the tag in skeleton §7 and codebase §5; remove the Java-runtime assumption
  — SMARTCyp can share an RDKit env. Net effect (with FAME3R adopted, below): **metabolism is fully JVM-free.**
- **PKSmart citation update (minor).** Now peer-reviewed in *J. Cheminformatics* (2025), DOI
  10.1186/s13321-025-01066-5; update the skeleton's bioRxiv reference. Its weak-CL numbers (GMFE 2.43 / R² 0.31)
  are confirmed, validating the "relative-ranking-only" posture for clearance.
- **PBPK runtime (env-plan).** OSP is R + .NET 8, not Python; it's the one endpoint outside the Python/pixi
  model. Plan an isolated R/.NET environment or a documented manual PK-Sim SOP.
**Build/runtime watchlist:**
- FAME 3 → **noncommercial license** (record in provenance; academic use OK) + Java runtime; consider **FAME3R**
  substitute to modernize.
- PKSmart → **Mordred** dependency (use `mordredcommunity`) + sklearn-version-pinned RF pickles.
- PBPK → R 4.x + .NET 8 + OSP binaries (heaviest non-Python dep).
**New candidate tools surfaced (not in either settled doc):**
- `molinfo-vienna/FAME3R` — modern re-design of FAME 3's RF SoM model; **ADOPTED as the FAME 3 substitute**
  (Python, MIT, PyPI/conda-forge) — makes metabolism Java-free.
- **DruMAP is a multi-endpoint platform** — one shortlist session also yields CLint, Fa, fu,brain, Kp,uu,brain,
  and P-gp brain-efflux (relevant to metabolism, absorption, and distribution/#19), not just renal.
**Metabolism/clearance takeaways for the pipeline:**
- Metabolism endpoint runtime: **SMARTCyp 3.0 = Python/RDKit, and FAME 3 (Java) is replaced by FAME3R
  (Python).** With FAME3R adopted, the endpoint is **fully JVM-free** — no `openjdk` in either model env.
  (Legacy Java FAME 3 kept only as an optional benchmark.)
- Clearance stays **decomposed**: PKSmart (aggregate CL, fold-error, ranking-only) + Watanabe renal (web,
  shortlist) + hepatic-via-metabolism (SMARTCyp/FAME + generalist stability) + PBPK (shortlist integrator). No
  single predicted clearance number — confirmed appropriate given PKSmart's CL R²=0.31.
---
 
## B (cont.). Per-model verified records — Batch 3
 
### Endpoint: DISTRIBUTION / BBB / CNS ("predict passive, flag efflux, measure the rest")
 
---
 
#### 14. BBB Score  ✔ CONFIRMED (rule; RDKit ports exist)
 
1. **Identity & existence.** Multiparameter passive brain-entry score. Formula paper: Gupta, Lee, Barden,
   Weaver, *J. Med. Chem.* 62(21):9824–9836 (2019), `https://doi.org/10.1021/acs.jmedchem.9b01220`
   (AUC 0.86, vs MPO 0.61 / MPO_V2 0.67).
2. **Access method.** **CODE-ALGO — CONFIRMED.** Deterministic formula over computed properties
   (#aromatic rings, heavy atoms, a MWHBN term, pKa, TPSA). Skeleton tag correct.
3. **Invoke.** Two independent RDKit reimplementations exist and reproduce Gupta's score:
   `https://github.com/gkxiao/BBB-score` and `https://github.com/sailfish009/BBB_calculator`. Vendor one (or
   re-implement from the paper) behind the uniform adapter.
4. **Install.** RDKit only (+ a pKa value; can use an in-house/predicted pKa). No service.
5. **Dependencies.** RDKit. Exact versions of the ported scripts UNVERIFIED — read at build time (trivial).
6. **Repo health.** Small single-purpose scripts; **STALE-BUT-USABLE (deterministic).**
7. **Verdict & flags → KEEP as rule.** Passive filter only (skeleton's "rough filter, not brain-exposure
   prediction" stands). Prefer re-implementing from the paper + unit-testing against the two ports, so the
   formula is auditable and not a black-box dependency.
8. **Citations.** JMC 2019 paper (ACS), `github.com/gkxiao/BBB-score`, `github.com/sailfish009/BBB_calculator`.
---
 
#### 15. BOILED-Egg  ✔ CONFIRMED (rule; **not fetched this pass — see caveat**)
 
1. **Identity & existence.** Passive gut-absorption + brain-penetration model from a fixed WLOGP-vs-TPSA
   geometric rule (two ellipses). Paper: Daina & Zoete, *ChemMedChem* 11(11):1117–1121 (2016), DOI
   `10.1002/cmdc.201600182`. (Cited from established literature; **the paper was not opened this pass** — confirm
   the exact ellipse coefficients from the 2016 paper at build time.)
2. **Access method.** **CODE-ALGO — CONFIRMED in principle.** Algorithmic (not ML): compute WLOGP + TPSA, test
   which ellipse the point falls in. Also available via the SwissADME web tool (#24). Skeleton tag correct.
3. **Invoke.** RDKit gives TPSA directly; WLOGP is reproducible (Wildman–Crippen contribution logP). Implement
   the ellipse test from the paper. Shared with the **permeability** endpoint.
4. **Install.** RDKit only.
5. **Dependencies.** RDKit. Ellipse constants from the 2016 paper — **transcribe and cite at build time.**
6. **Repo health.** Deterministic rule; **STALE-BUT-USABLE.**
7. **Verdict & flags → KEEP as rule (shared with permeability).** One implementation serves both
   distribution (BBB) and permeability (HIA) endpoints; register it once and let both aggregators consume it.
8. **Citations.** Daina & Zoete, ChemMedChem 2016 (to fetch/pin at build time); SwissADME (#24) as the web
   reference implementation.
---
 
#### 16. CNS MPO  ✔ CONFIRMED (rule; needs a pKa input)
 
1. **Identity & existence.** CNS multiparameter optimization desirability score (0–6) over six physchem
   properties. Paper: Wager, Hou, Verhoest, Villalobos, *ACS Chem. Neurosci.* 1(6):435–449 (2010),
   `https://doi.org/10.1021/cn100008c` (+ 2016 desirability update, `10.1021/acschemneuro.6b00029`).
2. **Access method.** **CODE-ALGO — CONFIRMED.** Six desirability transforms (monotonic on MW, cLogP, cLogD,
   HBD, most-basic pKa; hump-shaped on TPSA) summed to 0–6. Skeleton tag correct.
3. **Invoke.** Python/RDKit implementation: `https://github.com/Adam-maz/CNS_MPO_calculator` (classes
   `CNS_MPO_single_molecule()` / `CNS_MPO_csv_to_df()`; requires SMILES **and pKa**). Or re-implement directly
   in RDKit (cLogP via Crippen, TPSA via Ertl).
4. **Install.** RDKit. ⚠️ **Requires a pKa value** → depends on an external pKa predictor (the same pKa input
   BBB Score needs). Standardize one pKa source across BBB Score + CNS MPO for internal consistency.
5. **Dependencies.** RDKit (+ pKa source). Versions of the port UNVERIFIED — trivial.
6. **Repo health.** Small deterministic tool; **STALE-BUT-USABLE.**
7. **Verdict & flags → KEEP as rule.** Note Spielvogel's benchmark found CNS MPO weak on the PET-tracer set
   (AUC 0.53) — consistent with the skeleton's "rough filter only" posture; do not over-trust it for this
   cationic-amine chemotype.
8. **Citations.** Wager 2010/2016 (ACS Chem. Neurosci.), `github.com/Adam-maz/CNS_MPO_calculator`.
---
 
#### 17. P-gp (efflux substrate)  ✔ CONFIRMED (via generalists / TDC)
 
1. **Identity & existence.** Efflux-substrate flag. Standard public dataset: TDC **Pgp_Broccatelli**
   (Broccatelli et al. 2011). No single canonical "P-gp model" — it is a head inside the generalists.
2. **Access method.** **CODE — CONFIRMED via already-verified tools.** ADMET-AI and ADMETlab 3.0 (both Batch 1)
   expose P-gp substrate/inhibitor predictions; TDC provides the Pgp_Broccatelli benchmark to train a dedicated
   model if wanted. Skeleton tag ("generalists / TDC Pgp") correct.
3. **Invoke.** Read the P-gp field from the generalist outputs (no separate service). Optional: train a TDC
   Pgp_Broccatelli model for a dedicated head.
4. **Install.** None beyond the generalists; optionally `PyTDC` for the dataset.
5. **Dependencies.** Inherited from generalists / `PyTDC`.
6. **Repo health.** Inherits generalists' health (HEALTHY). Dataset is small/narrow.
7. **Verdict & flags → KEEP as generalist-derived flag (narrow domain).** Skeleton's "narrow ML on small
   transport data" caveat stands; usable only inside its training domain. Not a gate.
8. **Citations.** TDC Pgp_Broccatelli (tdcommons.ai), ADMET-AI / ADMETlab records above.
---
 
#### 18. Spielvogel efflux/BBB  ✔ CONFIRMED (open-source per authors; **repo URL to locate**)
 
1. **Identity & existence.** RF model integrating a novel 3D-PSA + 23 other parameters for BBB penetration and
   efflux-vs-CNS classification, trained on 154 radiolabeled molecules (PET tracers) + drugs. Paper (CORRECTED —
   full text read): Spielvogel et al., "Enhancing Blood–Brain Barrier Penetration Prediction…," ***J. Chem. Inf.
   Model.* 2025, 65(6):2773–2784**, `https://doi.org/10.1021/acs.jcim.4c02212`, PMID 40036481 (PMC11938273).
   *(My earlier "Mol. Pharmaceutics" attribution was wrong — corrected here.)*
2. **Access method.** ⚠️ **NO CODE REPOSITORY / NO RELEASED MODEL — corrected from "repo URL UNVERIFIED."** The
   paper's Data Availability Statement releases only the **dataset** (154 molecules + 24 features + BBB labels)
   at **`https://osf.io/cvhe9`** (CC-BY). "Open source" in the title/abstract refers to the *ML libraries used*,
   **not** a distributed model or code repo — the statement literally says to read the "Machine learning" and
   "Statistical analysis" sections "for the names of individual software packages." There is nothing to
   `pip install` or clone. **The skeleton's "CODE-PKG (open-source)" tag is therefore wrong for this model.**
3. **Invoke (reproduce-from-scratch only).** ML stack IS open: **Python 3.9.5 + scikit-learn, XGBoost, SHAP,
   imbalanced-learn (SMOTE), InterpretML, UMAP, mRMR, NumPy/Pandas/SciPy**. BUT the **feature generation used
   commercial software**: CNS MPO + BBB score + pKa via **ChemAxon MarvinSketch / Chemicalize**; tPSA + logP via
   **ChemDraw**; PSA(ACD) via **ACD/Labs**. And the flagship **3D-PSA requires per-molecule quantum-chemical
   geometry optimization** (B3LYP/6-31G(d) + D3; LanL2DZ for iodine) in **Avogadro 1.2.0 + PyMOL2** — genuinely
   QM-expensive, not a descriptor call.
4–5. **Install/deps.** No package. To use it you would re-implement the pipeline from the OSF data + methods,
   which requires the commercial chemistry tools above + a QM geometry step — a substantial build, not a drop-in.
6. **Repo health.** **Verdict: NO DISTRIBUTED ARTIFACT (dataset-only).** Data license CC-BY (usable).
7. **Verdict & flags → DOWNGRADE: do not integrate as a pipeline model; use as reference/benchmark, or take the
   published surrogate.** ✔ Metrics confirmed exactly (binary BBB AUC 0.88; multiclass 0.82; n=154; narrow).
   BUT two decisive findings from the full text: (a) **efflux-substrate identification alone is weak — AUC 0.57**
   (95% CI 0.52–0.61); the multiclass 0.82 is buoyed by the CNS±classes, and efflux is precisely the liability
   that matters for this cationic series. (b) SHAP ranks the **BBB score (already model #14) as the single most
   important feature**, with 3D PSA and tPSA next; the authors' own **surrogate decision tree** uses only *tPSA,
   3D PSA, HPLC logP(pH7.4), and BBB score*. **Recommendation:** drop Spielvogel from the automated pipeline;
   its signal is largely captured by BBB Score (#14) + a PSA term, and the real CNS answer remains experimental
   **Kp,uu**. If wanted, implement the lightweight published surrogate (4 features) rather than the full
   QM+commercial-tool pipeline; keep the OSF dataset as a benchmark.
8. **Citations.** JCIM 2025 full text (PMC11938273, DOI 10.1021/acs.jcim.4c02212), OSF dataset
   (osf.io/cvhe9), JNM 2025 abstract (jnm.snmjournals.org/content/66/supplement_1/251263).
---
 
#### 19. Watanabe P-gp brain (via DruMAP)  ✔ CONFIRMED — WEB-ONLY (same platform as #11)
 
1. **Identity & existence.** In-silico brain-capillary P-gp efflux-potential model. Paper: Watanabe et al.,
   "Development of an In Silico Prediction Model for P-glycoprotein Efflux Potential in Brain Capillary
   Endothelial Cells toward the Prediction of Brain Penetration," *J. Med. Chem.* (2021). Hosted on **DruMAP**
   (see #11).
2. **Access method.** **WEB-ONLY — CONFIRMED** (DruMAP web app; no API/package; models otherwise only in
   commercial SCIQUICK). Skeleton tag correct.
3. **Invoke (manual SOP).** Same DruMAP shortlist session as the renal model (#11): submit SMILES → read the
   brain P-gp efflux-potential output; transcribe to the ledger. **Batch #11 + #19 (+ CLint, Fa, fu,brain,
   Kp,uu,brain) in one DruMAP pass.**
4. **Install.** None (web).
5. **Dependencies.** N/A.
6. **Repo/service health.** HEALTHY as a service; WEB-ONLY.
7. **Verdict & flags → KEEP web-on-shortlist.** Passive/efflux score only; not a gate. Real CNS answer =
   experimental Kp,uu (skeleton posture stands).
8. **Citations.** Watanabe 2021 J. Med. Chem. (referenced in DruMAP/ArCHER), DruMAP paper (#11).
---
 
### Endpoint: PLASMA PROTEIN BINDING
 
---
 
#### 20. OCHEM PPB  ✔ CONFIRMED — CODE-API, **standing to-do resolved**
 
1. **Identity & existence.** Fraction-bound PPB prediction via a strong, prospectively-validated public
   consensus model. Model page: `https://ochem.eu/article/29`. Paper: Han, Xia, Xia, Tetko, Wu,
   *Eur. J. Pharm. Sci.* 204:106946 (2025), `https://doi.org/10.1016/j.ejps.2024.106946` (consensus; R²≈0.90
   train / 0.91 test; retrospectively validated on 63 poly-fluorinated + prospectively on 25 diverse compounds).
2. **Access method.** **CODE-API — CONFIRMED from OCHEM's own docs** (`docs.ochem.eu`). The skeleton's
   correction ("not web-only; has a REST API") is right. Documented REST call:
   `https://ochem.eu/modelservice/getPrediction.do?modelId=MODEL_ID&mol=MOLECULE` — SMILES or SDF, **batch via
   `$$$$` separator**, **asynchronous** (submit → returns a task ID → poll every 5–10 s until the result is
   ready).
3. **Invoke.** Two-step async client: POST/GET `getPrediction.do` with the pinned `modelId` → poll the task
   endpoint until the prediction returns. Batch molecules with `$$$$`.
4. **Install.** HTTP client only (no local install). On-prem "OCHEM Lite/Flex" is an option if a self-hosted
   instance is ever wanted.
5. **Dependencies.** HTTP client (requests). ⚠️ **Action to close the skeleton's to-do:** `article/29` is the
   *publication* page; the REST call needs the **numeric `modelId`** of the published model — read it off that
   model's OCHEM page at build time and pin it in the provenance README (+ cache raw responses; note the async
   polling contract).
6. **Repo/service health.** OCHEM is a long-standing, maintained platform (Tetko group). **Verdict: HEALTHY as
   a service.**
7. **Verdict & flags → KEEP as CODE-API; pin `ochem.eu/article/29` model.** Confirms skeleton's PPB decision.
   Not a gate (modulator); single tool acceptable. Since it's an external async service, wrap with retry/backoff
   + caching like ADMETlab.
8. **Citations.** OCHEM REST docs (`docs.ochem.eu/x/vwFr.html`), model page `ochem.eu/article/29`, EJPS 2025
   paper (ScienceDirect/PubMed 39490636).
---
 
## C (cont.). Summary table — Batch 3
 
| Model | Confirmed access | Install one-liner | Health | Action |
|---|---|---|---|---|
| BBB Score | CODE-ALGO ✔ | RDKit (+pKa) | STALE-USABLE | KEEP — re-implement from paper, test vs ports |
| BOILED-Egg | CODE-ALGO ✔ (not fetched) | RDKit | STALE-USABLE | KEEP — pin ellipse consts; shared w/ permeability |
| CNS MPO | CODE-ALGO ✔ | RDKit (+pKa) | STALE-USABLE | KEEP — standardize pKa source |
| P-gp | via generalists / TDC ✔ | (generalists) / `PyTDC` | HEALTHY | KEEP — narrow flag |
| ~~Spielvogel~~ | **no code/model (dataset-only)** | — | N/A | **DROP** — see §B #18 / §E.8 (efflux AUC 0.57; QM+commercial-tool build; signal ≈ BBB Score) |
| Watanabe P-gp brain | WEB-ONLY ✔ | none (web) | HEALTHY (svc) | KEEP web-on-shortlist (batch w/ #11) |
| OCHEM PPB | CODE-API ✔ | HTTP client | HEALTHY (svc) | KEEP — **pin modelId of `article/29`** |
 
---
 
## D (cont.). Flags & actions — Batch 3
 
**Standing to-do resolved:**
- **OCHEM PPB REST + model ID.** REST confirmed from OCHEM docs (`getPrediction.do?modelId=…&mol=…`, async,
  `$$$$` batch). Pin the **`ochem.eu/article/29`** consensus model (Han et al. 2025, R²≈0.90/0.91); read its
  numeric `modelId` off the model page and record it. This closes the skeleton's §7-PPB "pin the public model
  ID" action down to one lookup.
**Confirmations vs. the settled docs:**
- Spielvogel metrics (AUC 0.88 / 0.82, n=154 PET tracers, narrow) confirmed exactly.
- BBB Score / CNS MPO / BOILED-Egg confirmed as deterministic CODE-ALGO rules; authoritative formula papers
  cited; RDKit implementations located for BBB Score and CNS MPO.
- Watanabe P-gp brain confirmed WEB-ONLY on DruMAP (same platform/session as the renal model #11).
**Build/runtime watchlist:**
- **Spielvogel** → locate the open-source repo + license (not found in search); its **3D-PSA needs Avogadro
  geometry optimization** (heavier than RDKit). Mark RISKY until the URL/license are confirmed.
- **BBB Score + CNS MPO** both need a **pKa input** → choose one pKa predictor and use it consistently across
  both (and anywhere pKa feeds a rule), or results won't be internally comparable.
- **BOILED-Egg** ellipse constants must be transcribed from Daina & Zoete 2016 (not fetched this pass).
- **OCHEM PPB** is an async external service → retry/backoff + response caching, like ADMETlab.
**Reuse / graph notes:**
- **BOILED-Egg** is registered once but consumed by both `distribution` (BBB) and `permeability` (HIA).
- **DruMAP** services #11 + #19 (+ CLint, Fa, fu,brain, Kp,uu,brain) in a single shortlist session — one manual
  SOP covers several endpoints.
**Distribution posture (confirmed):** passive scores (BBB Score, BOILED-Egg, CNS MPO) are rough filters;
transport models (P-gp, Watanabe P-gp brain; Spielvogel dropped) are narrow-domain flags. For this cationic-amine CNS
series the real distribution answer remains **experimental Kp,uu** — the in-silico layer is triage only, exactly
as the skeleton states. BBB is desirable, not a gate.
 
---
 
## B (cont.). Per-model verified records — Batch 4
 
### Endpoint: SOLUBILITY
 
---
 
#### 21. SFI (Solubility Forecast Index)  ✔ CONFIRMED (rule/formula)
 
1. **Identity & existence.** Heuristic solubility index, **SFI = cLogD(7.4) + (number of aromatic rings)** —
   lower is better (Bhal/GSK; popularized in Pat Walters' SFI blog post, the reference Gilson shared).
2. **Access.** **CODE-ALGO — CONFIRMED.** Deterministic formula.
3. **Invoke.** Aromatic-ring count = `rdkit.Chem.rdMolDescriptors.CalcNumAromaticRings(mol)`; **cLogD(7.4)** is
   the non-trivial input — RDKit has no native logD, so derive from cLogP + pKa (Henderson–Hasselbalch) or take
   logD from OPERA (#23). Then sum.
4–6. **Install/deps/health.** RDKit (+ a logD/pKa source); STALE-BUT-USABLE (formula).
7. **Verdict → KEEP as rule.** ✔ Likely a **strength** of the low-aromatic oxetane series (skeleton).
   Uncertainty = SFI-vs-generalist discrepancy. Anchor cLogD to the measured series logD ≈ 1.
8. **Citations.** Pat Walters SFI blog (Practical Cheminformatics); Bhal et al. SFI concept.
---
 
### Endpoint: LIPOPHILICITY (anchor to measured series logD ≈ 1)
 
---
 
#### 22. RDKit Crippen  ✔ CONFIRMED (RDKit callable)
 
1–2. Wildman–Crippen atom-contribution logP/MR (1999). **CODE-PKG (RDKit) — CONFIRMED.**
3. **Invoke.** `rdkit.Chem.Crippen.MolLogP(mol)` / `MolMR(mol)`. **This is exactly SwissADME's WLOGP lens.**
4–6. RDKit only; HEALTHY.
7. **Verdict → KEEP.** Confirms skeleton.
8. **Citations.** RDKit `Chem.Crippen` docs; Wildman & Crippen 1999.
 
---
 
#### 23. OPERA  ✔ CONFIRMED — CODE-STANDALONE with AD flag (⚠️ MATLAB-runtime dependency)
 
1. **Identity & existence.** Open-source/open-data QSAR suite (>20 endpoints) with **applicability-domain +
   accuracy/confidence output**. Repos: `https://github.com/kmansouri/OPERA` and official mirror
   `https://github.com/NIEHS/OPERA` (releases). Mansouri et al. (NIH/NIEHS/EPA).
2. **Access.** **CODE-STANDALONE — CONFIRMED.** CLI + GUI, Windows and **Linux** (Rosenbluth-OK). AD output =
   the DIRECT-uncertainty role. Skeleton tag correct.
3. **Invoke.** `./run_OPERA.sh <MCR_path> -d in.csv -o preds.txt -e LogP LogD -v 1`. Endpoints include **LogP,
   LogD, pKa, FuB, Clint, Caco2/logPapp** → multi-endpoint. Returns AD + confidence ranges + experimental values.
4. **Install.** ⚠️ **Compiled MATLAB → free MATLAB Compiler Runtime (MCR, e.g. v912)**; internal descriptors via
   **PaDEL + CDK (Java)**. Heavy but self-contained, Linux-capable. Installer from NIEHS/OPERA releases.
5–6. MCR + PaDEL/CDK; no Python deps. Actively maintained. **HEALTHY.**
7. **Verdict → KEEP.** ✔ Confirms skeleton ("ML + AD flag"). **Env flag:** isolate the MCR+Java runtime like
   PBPK. Multi-endpoint → cross-checks logD/pKa (SFI/BBB/CNS MPO), fu (OCHEM PPB), Clint (metabolism).
8. **Citations.** `github.com/kmansouri/OPERA`, `github.com/NIEHS/OPERA` (README/help.txt/releases), EPA Science
   Inventory, Mansouri J. Cheminform. 2018 (DOI 10.1186/s13321-018-0263-1).
---
 
#### 24. SwissADME  ✔ CONFIRMED — WEB-SUBSTITUTABLE; **proprietary-vs-reproducible resolved**
 
1. **Identity.** Free web tool; consensus logP = mean of 5 methods (iLOGP, XLOGP3, WLOGP, MLOGP, SILICOS-IT).
   Paper: Daina, Michielin, Zoete, *Sci. Rep.* 7:42717 (2017), `https://doi.org/10.1038/srep42717`. `swissadme.ch`.
2. **Access.** **WEB-SUBSTITUTABLE — CONFIRMED** (web-only, no API). Skeleton tag correct.
3. **Reconstruction (resolved).** From the primary paper: **WLOGP** = SwissADME's Wildman–Crippen impl →
   **= RDKit Crippen (#22), reproducible**; **MLOGP** = Moriguchi formula → reproducible; **XLOGP3** = external
   CLI program v3.2.2 (CCBG/SIOC) → obtainable; **iLOGP** = SwissADME-internal GB/SA (Daina 2014) →
   **proprietary, not reproducible**; **SILICOS-IT** = output of the **defunct FILTER-IT** program → **not
   reproducible**. ⇒ **Skeleton confirmed exactly: reconstruct 3/5 (WLOGP/MLOGP/XLOGP3), lose iLOGP + SILICOS-IT.**
   In-code consensus = mean of the 3 reproducible lenses (optionally + OPERA logP); web form only if the exact
   5-way consensus is ever needed on the shortlist.
4–6. RDKit (+ optional XLOGP3 binary); web service HEALTHY.
7. **Verdict → KEEP.** Spread = flag; convergence = trust; scatter → lean on measured logD ≈ 1.
8. **Citations.** SwissADME Sci. Rep. 2017 (nature.com/articles/srep42717); iLOGP (Daina 2014, JCIM);
   FILTER-IT/Silicos-IT note in the SwissADME paper.
---
 
### Endpoint: PERMEABILITY
 
---
 
#### 25. Permeability (no own model)  ✔ CONFIRMED (aggregate-only)
 
No dedicated model — consumes generalist **Caco-2 / HIA / %F** (ADMET-AI, ADMETlab) + **BOILED-Egg** (#15).
Confirms both settled docs. May be partly moot given possible intratumoral/osmotic-pump delivery; `%F` is weak
(treat with suspicion). **KEEP as aggregate.**
 
---
 
### Endpoint: STRUCTURAL ALERTS
 
---
 
#### 26. PAINS / BRENK  ✔ CONFIRMED (RDKit callable)
 
PAINS (Baell & Holloway 2010) + BRENK (Brenk et al. 2008). **CODE-PKG (RDKit) — CONFIRMED.** Invoke via
`rdkit.Chem.FilterCatalog` (`FilterCatalogs.PAINS` A/B/C, `BRENK`). **KEEP as soft filter** (look-closer, not
auto-kill; over-flags) — matters because the FTO assay is fluorescence-based. Confirms skeleton.
 
---
 
### Endpoint: SYNTHESIZABILITY (escalating rigor ladder)
 
---
 
#### 27. SAscore  ✔ CONFIRMED (RDKit Contrib)
 
Ertl & Schuffenhauer, *J. Cheminform.* 1:8 (2009). **CODE-PKG (RDKit Contrib) — CONFIRMED.** Invoke
`sascorer.calculateScore(mol)` from `$RDBASE/Contrib/SA_Score/sascorer.py` — **not core**; vendor `sascorer.py`
+ `fpscores.pkl.gz` and add to path. **KEEP (triage rung).** Confirms skeleton.
---
 
#### 28. RAscore  ✔ CONFIRMED (second-opinion classifier)
 
1. **Identity.** Binary retrosynthetic-accessibility classifier (route findable by AiZynthFinder: 1/0), trained
   on 200k ChEMBL, ~4500× faster than CASP. Repo: `https://github.com/reymond-group/RAscore`. Thakkar et al.,
   *Chem. Sci.* 12:3339 (2021), `https://doi.org/10.1039/D0SC05401A`.
2. **Access.** **CODE-PKG — CONFIRMED.**
3–6. From repo; **pins UNVERIFIED — 2021-era TF/sklearn → pin versions to load the shipped model, isolated env,
   health-check first.** STALE-BUT-USABLE.
7. **Verdict → KEEP (second rung).** ChEMBL/bioactive training space fits this series.
8. **Citations.** `github.com/reymond-group/RAscore`, Chem. Sci. 2021 (RSC D0SC05401A / PMC8179384).
---
 
#### 29. AiZynthFinder  ✔ CONFIRMED (real route search)
 
1. **Identity.** Open-source CASP: MCTS retrosynthesis + NN template policy to purchasable precursors. Repo:
   `https://github.com/MolecularAI/aizynthfinder` (AstraZeneca MolecularAI, MIT). Genheden et al., *J.
   Cheminform.* 12:70 (2020), `https://doi.org/10.1186/s13321-020-00472-1`.
2. **Access.** **CODE-PKG — CONFIRMED** (`pip install aizynthfinder`; actively maintained).
3–6. Configure policy model + **stock set** (ZINC/Enamine/ACD); RDKit + TF/PyTorch policy. **HEALTHY** (CI/tests).
7. **Verdict → KEEP (top rung, shortlist).** Confirmatory; series almost certainly makeable. Confirms skeleton.
8. **Citations.** `github.com/MolecularAI/aizynthfinder`, J. Cheminform. 2020 (DOI 10.1186/s13321-020-00472-1).
---
 
### Endpoint: TOXICITY
 
---
 
#### 30. Toxicophores (structural alerts)  ✔ CONFIRMED (RDKit callable; pick a source)
 
Known toxic substructures. **CODE-PKG (RDKit) — CONFIRMED** via `rdkit.Chem.FilterCatalog` (BRENK/NIH/ChEMBL
alert catalogs). ⚠️ Minor: "toxicophores" is **not one canonical RDKit catalog** — choose/document the source
(BRENK default, optionally a ToxAlerts SMARTS export). Distinct from #26 by *intent* (toxicity vs
assay-interference). **KEEP as rule.**
 
---
 
#### 31. ProTox 3.0  ✔ CONFIRMED — WEB-ONLY (no API)
 
1. **Identity.** 61-endpoint toxicity webserver (acute LD50 + class; organ tox; mutagenicity, carcinogenicity,
   cytotoxicity, immunotoxicity; Tox21 pathways; **15 tox off-targets; 14 MIE targets; 6 metabolism targets**;
   eco/nutritional/clinical). Banerjee et al., *Nucleic Acids Research* 52(W1):W513–W520 (2024),
   `https://doi.org/10.1093/nar/gkae303`. `tox.charite.de` (free, no login).
2. **Access.** **WEB-ONLY — CONFIRMED** (form-based; no API/package). Skeleton tag correct.
3. **Invoke (manual SOP).** Submit shortlist SMILES → **select "ALL models"** (default = acute tox + targets
   only) → read per-endpoint predictions + confidence + radar/network plots → transcribe to ledger.
4–6. None (web); HEALTHY as a service.
7. **Verdict → KEEP web-on-shortlist; bulk-substituted (TIERED).** **No automatable substitute** for:
   respiratory toxicity, ecotoxicity, nutritional toxicity, the **15 tox off-targets**, the **14 MIE targets**,
   most of the **6 metabolism targets** — ProTox-web is the only source for these. Coverage/throughput
   substitution, not quality-equivalence. Confirms skeleton.
8. **Citations.** ProTox 3.0 NAR 2024 (Oxford/PMC11223834), `tox.charite.de`.
---
 
### Endpoint: DRUGLIKENESS (context, not gates)
 
---
 
#### 32. Lipinski / Veber / QED  ✔ CONFIRMED (RDKit callables)
 
Oral drug-likeness thresholds + QED (Bickerton et al., *Nat. Chem.* 2012). **CODE-PKG (RDKit) — CONFIRMED.**
Invoke via `rdkit.Chem.Descriptors`/`rdkit.Chem.Lipinski` (MW/HBD/HBA/RotB/TPSA) and `rdkit.Chem.QED.qed(mol)`.
**KEEP as context (POINTER)** — run by the lab, not gates. Confirms skeleton.
 
---
 
## C (cont.). Summary table — Batch 4
 
| Model | Confirmed access | Install one-liner | Health | Action |
|---|---|---|---|---|
| SFI | CODE-ALGO ✔ | RDKit (+ logD source) | STALE-USABLE | KEEP — standardize logD/pKa source |
| RDKit Crippen | CODE-PKG (RDKit) ✔ | RDKit | HEALTHY | KEEP — = SwissADME WLOGP lens |
| OPERA | CODE-STANDALONE ✔ | NIEHS/OPERA release + **MCR** | HEALTHY | KEEP — isolate (MATLAB runtime + Java) |
| SwissADME | WEB-SUBSTITUTABLE ✔ | reconstruct 3/5 in RDKit | HEALTHY (svc) | KEEP — lose iLOGP + SILICOS-IT |
| Permeability | aggregate-only ✔ | (generalists + BOILED-Egg) | — | KEEP — no own model |
| PAINS/BRENK | CODE-PKG (RDKit) ✔ | RDKit FilterCatalog | HEALTHY | KEEP — soft filter |
| SAscore | CODE-PKG (RDKit Contrib) ✔ | vendor `sascorer.py` | HEALTHY | KEEP — triage rung |
| RAscore | CODE-PKG ✔ | clone `reymond-group/RAscore` | STALE-USABLE | KEEP — verify TF/sklearn pins |
| AiZynthFinder | CODE-PKG ✔ | `pip install aizynthfinder` + stock | HEALTHY | KEEP — shortlist route search |
| Toxicophores | CODE-PKG (RDKit) ✔ | RDKit FilterCatalog (BRENK) | HEALTHY | KEEP — pick alert source |
| ProTox 3.0 | WEB-ONLY ✔ | none (web) | HEALTHY (svc) | KEEP web-on-shortlist (select ALL) |
| Lipinski/Veber/QED | CODE-PKG (RDKit) ✔ | RDKit `QED`/`Descriptors` | HEALTHY | KEEP — context |
 
---
 
## D (cont.). Flags & actions — Batch 4
 
**Question resolved (SwissADME):** WLOGP (=RDKit Crippen), MLOGP (formula), XLOGP3 (external CLI) are
reproducible; iLOGP (SwissADME GB/SA) and SILICOS-IT (defunct FILTER-IT) are not → in-code consensus averages
the 3 reproducible lenses (optionally + OPERA logP). Skeleton confirmed.
 
**Build/runtime watchlist:** OPERA → MCR (MATLAB runtime) + PaDEL/CDK (Java), isolate like PBPK; RAscore →
2021-era TF/sklearn pins; SAscore → RDKit **Contrib** (vendor `sascorer.py` + `fpscores.pkl.gz`); SFI/BBB
Score/CNS MPO → standardize ONE cLogD/pKa source across them; Toxicophores → pick/document the alert catalog.
 
---
 
## E. VERIFICATION COMPLETE — consolidated rollup
 
All ~31 model entries verified against primary sources across the four batches. Every access claim and
dependency fact is backed by a cited URL in §B; facts I could not confirm from a primary source are marked
**UNVERIFIED — read at build time** rather than guessed.
 
### E.1 — Access-tag CORRECTIONS to the settled docs (must edit skeleton §7 + codebase §5)
 
1. **SMARTCyp 3.0 is Python/RDKit, NOT Java (material).** Both docs tag it CODE-STANDALONE (Java); v3.0 was
   rewritten in Python 3 + RDKit (only 1.x/2.x were Java+CDK). Net effect: with FAME 3 replaced by **FAME3R
   (Python)**, **no metabolism model needs a JVM — the endpoint is fully Java-free.** *(Reconciliation note: a
   later IO-spec pass mistakenly re-tagged SMARTCyp as Java after reading the legacy `cdk/smartcyp` repo; that is
   retracted — this correction is the right one, confirmed against the SMARTCyp 3.0 paper + KU page.)*
2. **ADMET-AI v1 vs v2 (material) — DECIDED: v2.** Docs describe v1 (Chemprop-RDKit, DrugBank percentiles);
   `pip install` now gives v2 (Chemprop v2, retrained, *different predictions*). Pinned to v2, with VDss/half-life
   heads excluded (§E, F-17). *(If a paper-faithful v1 run is ever needed, v1 is commit
   `9c8430862b2afd997ff1d314b30bda4418fa9b33`.)*
3. **PKSmart citation** now peer-reviewed (*J. Cheminf.* 2025, DOI 10.1186/s13321-025-01066-5) — update the
   bioRxiv reference. (Weak-CL numbers GMFE 2.43 / R² 0.31 confirmed → ranking-only posture correct.)
4. **OCHEM PPB** REST confirmed (`getPrediction.do?modelId=…&mol=…`, async, `$$$$` batch); **pin the
   `ochem.eu/article/29` consensus model** (Han et al. 2025) — read its numeric `modelId` at build time. Closes
   the skeleton's standing to-do.
5. **SwissADME** reconstruction resolved to the method level (reproduce WLOGP/MLOGP/XLOGP3; lose iLOGP +
   SILICOS-IT) — confirms the doc.
### E.2 — VERIFY resolutions & drops
 
- **DeepHIT → DROP** (no primary code repo; web-server-only; redundant with CardioTox net).
- **CardioDPi → web/shortlist secondary, or substitute `issararab/CToxPred2`** (in-code, same 3 channels, has
  uncertainty).
### E.3 — Web-only tools (manual SOP on shortlist; never in bulk loop)
 
Watanabe renal (DruMAP), Watanabe P-gp brain (DruMAP), ProTox 3.0, SwissADME (for the exact 5-way consensus).
**DruMAP services renal + P-gp-brain + CLint + Fa + fu,brain + Kp,uu,brain in ONE session** — batch them.
 
### E.4 — Non-Python / heavy runtimes (isolate; break the "Python everywhere" model)
 
- **FAME 3** — Java (CDK+WEKA) **only if you keep the original**; the verified substitute **FAME3R** (Python,
  MIT, `pip install fame3r` / conda-forge) removes it → **metabolism becomes fully Java-free** (SMARTCyp 3.0
  Python + FAME3R Python). Recommend adopting FAME3R; keep Java FAME 3 as an optional benchmark only.
- **OPERA** — compiled MATLAB (**MCR**) + Java (PaDEL/CDK). Genuinely heavy; isolate.
- **PBPK / OSP** — R 4.x + **.NET 8** + OSP binaries.
- Legacy Python envs (isolate; possibly CPU-only / old CUDA): **BayeshERG** (py3.6 + DGL; **weights are
  CC-BY-NC**), **CardioTox net** (py3.7.7 + old TF), **RAscore** (2021 TF/sklearn).
- **Spielvogel** is NOT a runtime item — it's **dataset-only** (no code/model); if reproduced, its 3D-PSA needs
  QM geometry optimization + commercial chemistry tools. Recommendation is to **drop it** (see §B #18).
### E.5 — New candidate tools surfaced (not in either settled doc)
 
`issararab/CToxPred2` (CardioDPi substitute) · `ersilia-os/eos4tcc` (BayeshERG port) · `ncats/herg-ml`
(consensus hERG + data) · `molinfo-vienna/FAME3R` (FAME 3 re-design). OPERA and DruMAP are both **multi-endpoint**
platforms usable as cross-checks beyond their primary endpoint.
 
### E.6 — Cross-cutting build actions
 
- Standardize **ONE cLogD/pKa source** (OPERA logD or a single pKa predictor) across SFI, BBB Score, CNS MPO;
  anchor to measured logD ≈ 1.
- Wrap external async services (**ADMETlab 3.0**, **OCHEM PPB**) with retry/backoff + response caching + pinned
  model choice.
- **PKSmart** → use `mordredcommunity` (not upstream Mordred) + sklearn-version-pinned pickles.
- **RAscore** dependency age — health-check the 2021 TF/sklearn pins before building the adapter (still a
  build-time read). **Spielvogel** is resolved (dataset-only; recommend drop — see §B #18).
### E.7 — What was NOT in scope (still open; from the skeleton's §11)
 
This recon verified *existence, access, and dependencies* only. The validation/decision layer —
applicability-domain rule, conformal calibration, prospective validation on measured T-series points, the
written decision policy, null/ceiling benchmarks, versioning — remains open and sits on top of this inventory.
 
### E.8 — Deferred items closed in the follow-up pass (verification addendum)
 
A second pass went back and closed the higher-value "read at build time" deferrals:
 
- **Spielvogel (#18) — RESOLVED, materially.** Full text read: DOI corrected to **10.1021/acs.jcim.4c02212**
  (JCIM 2025; my earlier "Mol. Pharm." was wrong). **No code repo / no released model** — dataset only at
  osf.io/cvhe9; feature-gen used **commercial tools** (ChemAxon, ChemDraw, ACD) + **QM 3D-PSA**; **efflux class
  AUC only 0.57**; BBB Score (#14) is its top feature. **→ drop from the automated pipeline** (was "RISKY, find
  repo"; now definitively not a drop-in).
- **FAME3R (#10) — RESOLVED.** Verified **Python, MIT, on PyPI + conda-forge**, maintained (CI/tests, 7
  releases). **→ metabolism can be fully Java-free.**
- **BayeshERG (#4) — RESOLVED.** Last commit 2022-11-18; **dual license (MIT code / CC-BY-NC-4.0 weights)**;
  CLI verified; outputs **separate aleatoric + epistemic** uncertainty.
- **SMARTCyp (#9) — RESOLVED.** **No official PyPI**; use ku.dk source or the **MDStudio_SMARTCyp** wrapper
  (pip/Docker/REST). `cdk/smartcyp` = legacy Java line.
- **OCHEM PPB modelId (#20) — STILL A GENUINE MANUAL STEP.** The REST mechanism and the model to pin
  (`ochem.eu/article/29`) are confirmed, but the numeric `modelId` lives behind the OCHEM model-service UI
  (login/navigation) and can't be reliably scraped — it's a ~30-second lookup on the live platform. Not a
  gap in reasoning, just an action that must happen on ochem.eu.
- Genuinely-build-time-only (exact patch pins that don't change any decision): CardioTox net TF version,
  CardioGenAI/RAscore exact pins, OpenADMET conda-env yaml, PKSmart requirements (decision-relevant facts —
  old TF, Mordred→mordredcommunity, 2021 stack, conda — already recorded).
---
 
*Verification complete: ~31/31 model entries, plus a follow-up pass that closed the high-value deferrals
(§E.8). Method: primary sources only, fetched not inferred; unverifiable facts marked rather than guessed;
every discrepancy flagged against the two settled docs. This file is a recon deliverable — no pipeline code was
written. Next step is implementation (Claude Code), beginning with the access-tag corrections in E.1 and the
build-order walking skeleton.*
 
