FTO-ADMET — Per-Model Input/Output Contract Specification
Status: RECON DELIVERABLE (I/O contracts). Specifications only — no code. Companion to the three
settled/verified files. This is the second recon pass: it extracts the exact input and output
contract of every model in the finalized FTO-ADMET set so that core/schemas.py, each ModelSpec,
and the per-endpoint aggregate.py files can be written. It does not produce pydantic classes or
adapters.
Reconciled (2 Jul 2026): the one substantive conflict with the other project docs — this pass's
mid-pass claim that "SMARTCyp is Java" — has been retracted: SMARTCyp 3.0 is Python 3 + RDKit (that
claim read the legacy cdk/smartcyp Java repo; primary sources confirm the 3.0 rewrite). The metabolism
env therefore needs no openjdk. Two intra-doc slips were also fixed to match §1/§3: the §2 map now
shows CToxPred2 as a 0/1 vote (not a probability) and FAME3R with no 0.3 threshold; the FAME3R
folder is fame3r/.
Method / honesty caveat. Every field below is backed by a primary source that was fetched this
pass (repo README, function signature, an example output file, API/site doc, or the model's own
formula paper). Facts that could not be read from a primary source — especially exact column-name
casing, units, and direction — are marked UNVERIFIED — read at build time rather than guessed. A
wrong unit or direction silently corrupts every aggregation, so those are flagged, not assumed. Repo
state is as of the 2 Jul 2026 fetch and drifts; re-read at build time.
Second verification pass (2 Jul 2026 — this update). Items originally marked UNVERIFIED — read at build
time were in fact reachable without running the model — their contracts are shipped in the repos as
example CSVs, hardcoded header strings, predict_proba usage, or reference-wrapper code (cloned/PyPI/web,
none of which hit the GitHub-API rate limit). Thirteen contracts were resolved and are marked VERIFIED
(2 Jul 2026) with the exact file cited: CToxPred2, CardioGenAI, PKSmart, FAME3R, SMARTCyp, OpenADMET,
AiZynthFinder, ADMET-AI v2 units, OPERA, ADMETlab's uncertainty mechanism and its full request/transport
contract, CardioTox net, and BOILED-Egg. One correction stands: CardioTox net's repo does exist
(a mid-pass note that it was unavailable was wrong — that was a rate-limited API query, not a dead repo).
⚠ RETRACTED (2 Jul 2026 reconciliation): an earlier version of this pass also "corrected" SMARTCyp to
Java (#5). That retraction was itself wrong — it read the legacy cdk/smartcyp Java repo. Primary
sources (the SMARTCyp 3.0 applications note; the KU group page) confirm SMARTCyp 3.0 is Python 3 + RDKit
(only 1.x/2.x were Java/CDK). So SMARTCyp 3.0 is Python, no JVM, and the CSV header captured below is from
the legacy Java line — treat it as a template to re-verify against real 3.0 output, not as the 3.0 contract.
What still genuinely needs a live/authenticated session: the
literal 119 ADMETlab CSV column names (one live /api/admetCSV call), OCHEM PPB modelId (F-7),
DruMAP (F-14) and ProTox (F-15) per-molecule web runs. See the consolidated changelog in §4.
Finalized set applied (per the recon prompt's Step 0), so this pass does NOT gather I/O for:

Dropped: DeepHIT, Spielvogel.
Substituted: CardioDPi → CToxPred2 (issararab/CToxPred2); FAME 3 (Java) → FAME3R (Python).
Pinned: ADMET-AI → v2 (installable pip line; retrained, predictions differ from the v1 paper/web server).

Legend used in the field tables

Type: float, int, bool, str, enum, prob[0–1], class-label, table(per-atom).
Direction: what higher means for a predictive field (↑tox / ↑permeable / ↑soluble / ↑stable / …),
or explicitly LOWER = worse/better where the scale is inverted. The hERG/tox aggregators weight
toward the hazardous direction and cannot do so without this.


§1 — Per-model I/O records (grouped by endpoint)
Endpoint: TRIAGE (cross-cutting generalists)
1. ADMET-AI (v2)  — endpoints/triage/admet_ai/
A. Input contract

Accepted: SMILES. Python API ADMETModel().predict(smiles) → dict (single SMILES) or
pandas.DataFrame (list). CLI admet_predict --data_path in.csv --save_path out.csv --smiles_column smiles.
Batch: yes, unbounded locally. CSV needs the SMILES column named by --smiles_column (default smiles).
Prep: internal RDKit parsing/canonicalization; v2 uses Chemprop v2 (no RDKit-fingerprint features).
No explicit desalting/protonation step documented → standardize upstream (the pipeline should feed a
single canonical, neutralized parent; confirm behavior on the FTO salt/di-cation at build time).
Source: repo README + docs/reproduce.md (github.com/swansonk14/admet_ai).

B. Output contract (priority). Exact columns read from the repo's example output file — the DrugBank
reference CSV header, admet_ai/resources/data/drugbank_approved.csv (main branch, fetched this pass).
One column per predicted property; at predict time each property also gets a companion
<property>_drugbank_approved_percentile column (0–100 percentile vs approved drugs — greenstonebio site).
Physicochemical (8, computed by RDKit): molecular_weight (g/mol), logP (Crippen, log), hydrogen_bond_acceptors (int count), hydrogen_bond_donors (int count), Lipinski (int; number of Ro5 conditions satisfied — confirm sense at build time), QED (0–1, ↑ = more drug-like), stereo_centers (int), tpsa (Å²).
Structural-alert counts (3): PAINS_alert, BRENK_alert, NIH_alert — int counts, ↑ = more alerts.
ADMET classification heads (prob[0–1] = P(named positive class); ↑ = more of that property):
AMES (P mutagenic), BBB_Martins (P BBB-penetrant), Bioavailability_Ma (P orally bioavailable),
CYP1A2_Veith CYP2C19_Veith CYP2C9_Veith CYP2D6_Veith CYP3A4_Veith (P CYP inhibitor),
CYP2C9_Substrate_CarbonMangels CYP2D6_Substrate_CarbonMangels CYP3A4_Substrate_CarbonMangels
(P CYP substrate), Carcinogens_Lagunin (P carcinogen), ClinTox (P clinical-tox / trial failure),
DILI (P drug-induced liver injury), HIA_Hou (P human intestinal absorption), PAMPA_NCATS
(P permeable), Pgp_Broccatelli (P P-gp substrate/inhibitor), Skin_Reaction (P reactive), hERG
(P hERG blocker; ↑ = more cardiotoxic), and the 12 Tox21 pathway heads NR-AR, NR-AR-LBD, NR-AhR,
NR-Aromatase, NR-ER, NR-ER-LBD, NR-PPAR-gamma, SR-ARE, SR-ATAD5, SR-HSE, SR-MMP, SR-p53
(P pathway active).
ADMET regression heads (units from the TDC single-prediction datasets):
ColumnQuantityUnitDirection (↑ means)Caco2_WangCaco-2 permeability (log Papp)cm/s (log)↑ more permeableLipophilicity_AstraZenecalogD7.4log-ratio↑ more lipophilicSolubility_AqSolDBaqueous solubility (log S)log mol/L↑ more solublePPBR_AZplasma-protein-binding rate% bound↑ more bound (less free)VDss_Lombardovolume of distribution (ss)L/kg↑ more tissue distributionHalf_Life_Obachhalf-lifehr↑ longer t½Clearance_Hepatocyte_AZhepatocyte CLintuL/min/10^6 cells↑ faster clearanceClearance_Microsome_AZmicrosomal CLintuL/min/mg↑ faster clearanceLD50_Zhuacute oral LD50log(1/(mol/kg)) (↑ = more toxic)see flag F-5HydrationFreeEnergy_FreeSolvhydration free energykcal/mol(physchem)

VERIFIED (2 Jul 2026): all units, task_type, and the model's own reported metric for every ADMET-AI v2
head read directly from admet_ai/resources/data/admet.csv (columns category,id,name,size,task_type,units, minimum,maximum,species,AUPRC,AUROC,R^2,MAE,url). The three previously-"confirm" values are now fixed:
Clearance_Hepatocyte_AZ = uL/min/10⁶ cells, Clearance_Microsome_AZ = uL/min/mg (my earlier
"mL/min/g" was the wrong canonical string — dimensionally equal but record the TDC unit), LD50_Zhu =
log(1/(mol/kg)) so higher = more toxic and it is not comparable to ProTox LD50 (mg/kg). PPBR_AZ
unit = %. hERG is a classification head (P-block, AUROC 0.84).
⚠ RELIABILITY FLAG (new, F-17): the same file reports the v2 models' own accuracy. Two regression heads
are worse than predicting the mean: VDss_Lombardo R² = −1.21 and Half_Life_Obach R² = −2.39.
Both clearance heads are weak (R² ≈ 0.26 / 0.28, MAE ≈ 33 / 27). The aggregator should not let
ADMET-AI contribute to VDss or half-life at all, and should treat its clearance as low-weight/qualitative.
Classification heads are strong where it matters (HIA 0.99, Pgp 0.95, CYP inhibition 0.89–0.94, BBB 0.90).
Delivery shape: dict (single) / DataFrame (list); CLI writes a CSV with the columns above +
_drugbank_approved_percentile companions. No native per-prediction uncertainty field → uncertainty is
INDIRECT (cross-model spread), as the skeleton states.
v2 discrepancy flag: these are v2 heads; the paper/live web server are v1 and predictions differ.
Source: repo CSV header (fetched), greenstonebio site, TDC dataset paper.

2. ADMETlab 3.0  — endpoints/triage/admetlab3/ (CODE-API)
A. Input contract

Accepted: SMILES, POSTed to the site's batch API; ≤1000 SMILES/request, ≤5 rps (per the
ToxMCP/admetlab-mcp reference wrapper — reference, not authoritative). A "Molecule Wash" API function
standardizes/──charges/handles tautomers first (NAR paper).
Prep: washing available server-side; still standardize upstream for reproducibility.

B. Output contract

Asynchronous: the ADMET endpoint returns a taskId + batch aggregation; results are then fetched
as a CSV by taskId (headers + content). CSV carries 119 endpoints, each with: predicted
value/probability, an empirical decision-state (coloured-dot category), an uncertainty-estimation
score, and alert-substructure highlights (NAR paper).
VERIFIED (2 Jul 2026), uncertainty mechanism: for classification heads ADMETlab 3.0 converts the raw
uncertainty score into a confidence label using a per-endpoint Youden's-index threshold — uncertainty
above the max-Youden point → low confidence, below → high confidence (NAR 2024 paper, Table 1 +
text). So the DIRECT uncertainty signal exists but is delivered as a binary high/low-confidence flag per
endpoint, not a continuous evidential variance — the aggregator should consume the flag, not assume a
calibrated σ. Architecture is DMPNN-Des (multi-task DMPNN + RDKit 2D descriptors).
Organ-tox heads confirmed present (skeleton match): nephro, neuro, oto, hemato, genotox, hERG,
RPMI-8226 immuno, A549/HEK293 cyto.
Request/transport contract — VERIFIED (2 Jul 2026) from the reference wrapper ToxMCP/admetlab-mcp
(client/admet_client.py, settings.py). Base https://admetlab3.scbdd.com. Flow:

(optional) wash: POST /api/washmol with body {"SMILES": [...]}.
predict: POST /api/admet (fallback POST /api/single/admet) with body
{"SMILES": [...], "feature": <bool>, "uncertain": <bool>} → returns JSON containing a taskId
(async). uncertain is an opt-in request flag — set it true to get the uncertainty output.
fetch results: POST /api/admetCSV with body {"taskId": <id>} → returns the CSV (headers +
rows, one molecule per row). Optional header X-API-KEY. Also POST /api/molsvg for structure images.


Still build-time (narrowed): only the literal 119 endpoint column names inside the CSV remain
unread — the wrapper passes the CSV through without enumerating them, so capture the header from one live
/api/admetCSV call at build time. Everything around it (paths, payload keys, async taskId pattern,
uncertainty toggle) is now fixed.
Direction: per-endpoint; classification heads = P(named property).
Source: NAR 2024 paper (academic.oup.com/nar/article/52/W1/W422); github.com/ToxMCP/admetlab-mcp (fetched).

3. OpenADMET  — endpoints/triage/openadmet/ (reference, not authority)
A. Input contract

Accepted: SMILES. It is a framework, not a turnkey predict(smiles). Released baseline models can be
run for inference: CYP inhibition & reaction phenotyping — CYP3A4, CYP2J2, plus a multitask
CYP1A2/2D6/2C9/PXR/AhR model.
Prep: RDKit-based; per the anvil recipe layer.

B. Output contract — VERIFIED (2 Jul 2026) from openadmet/models/inference/inference.py:

The inference pipeline appends columns to the input DataFrame / output_csv using a fixed naming
scheme, one pair per model task: OADMET_PRED_{tag}_{taskname} (prediction) and
OADMET_STD_{tag}_{taskname} (per-prediction standard deviation → native uncertainty, DIRECT), where
{tag} is the model's metadata tag. Classification tasks route through predict_proba (so the PRED value is
a probability); regression tasks emit the value. Optional active-learning acquisition columns
OADMET_{ACQFXN}_{tag}_{taskname} may also appear. It refuses to overwrite an existing PRED/STD column.
Weights provenance: pretrained baselines are pulled from S3 (_download_s3_dir in
comparison/posthoc.py) — not HuggingFace and not retrain-only, correcting the earlier open question.
Note for the pipeline: OpenADMET is one of the few sources that ships a real per-prediction σ; even in
its "reference only" role it is a useful uncertainty contributor. Use posture unchanged: CYP-metabolism
reference, not fed to gates (cluster-split R² is low).
Source: github.com/OpenADMET/openadmet-models (inference/inference.py, comparison/posthoc.py).


Endpoint: hERG / CARDIOTOXICITY — PRIMARY GO/NO-GO GATE
4. BayeshERG  — endpoints/herg/bayesherg/  ✔ output verified from README
A. Input contract

Accepted: .csv with a smiles column (optional ID column). CLI:
python main.py -i input.csv -o out_name -c {cpu|gpu} -t <sampling_time:int, default 30>
(-t = number of MC-dropout samples).
Prep: valid SMILES; internal RDKit graph featurization. Standardize/neutralize upstream (di-cation risk).

B. Output contract

Appends three columns to the input CSV, written to prediction_results/<out_name>.csv:
FieldTypeMeaningDirectionscoreprob[0–1]hERG blocker probability↑ = more likely blocker (↑cardiotox)aleafloat ≥0aleatoric uncertainty↑ = noisier/irreducibleepisfloat ≥0epistemic uncertainty↑ = more out-of-domain

Also writes per-molecule attention .svg images (attention_results/<out_name>/).
This separated aleatoric+epistemic split is what the split-case adjudicator consumes.
Source: repo README github.com/GIST-CSBL/BayeshERG (fetched).

5. CardioTox net  — endpoints/herg/cardiotox_net/
A. Input contract

Accepted: SMILES string or list. import cardiotox; m = cardiotox.load_ensemble(); m.predict(smile).
Individual base models importable: DescModel, SVModel, FVModel, FingerprintModel; each
self-preprocesses (preprocess_smile([smi]) → predict_preprocessed(...)).
Applicability limit (flag): "only suitable for SMILES with max number of 1's in Morgan fingerprint ≤ 93."
Prep: internal per-model preprocessing.

B. Output contract — VERIFIED (2 Jul 2026) from source (cardiotox/model.py + README, repo
github.com/Abdulk084/CardioTox, which does exist — an earlier note in this doc that it was
unavailable was wrong; the 404 was a rate-limited GitHub API query, not the repo).

m = cardiotox.load_ensemble(); m.predict(smiles, probabilities=False). smiles is a string or list;
the return is a NumPy array of hERG-blocker probabilities in (0, 1), one per input SMILES (↑ = more
likely blocker). It is a bare array, not a DataFrame — there is no named field to key on; the adapter
aligns it positionally to the input list.
With probabilities=True the output is expanded to two columns [P(non-blocker), P(blocker)]
(probabilities() helper, for LIME) — take column 1 for the gate.
Base models DescModel/SVModel/FVModel/FingerprintModel each expose predict() /
predict_preprocessed() with the same signature; the ensemble averages them.
No native uncertainty field → INDIRECT (ensemble-vs-ensemble agreement). Applicability limit stands
(Morgan-fingerprint on-bits ≤ 93).
Source: github.com/Abdulk084/CardioTox cardiotox/model.py, README (fetched 2 Jul 2026);
Karim et al., J. Cheminform. 2021 (10.1186/s13321-021-00541-z); BioModels MODEL2407180003.

6. CToxPred2  — endpoints/herg/ctoxpred2/ (substitute for CardioDPi)
A. Input contract

Accepted: SMILES via GUI (app.py) or the notebook notebooks/make_predictions.ipynb; results
exportable as CSV to a user folder. conda env ctoxpred2 (py3.9); models must be decompressed under
CToxPred2/models.
Model choice (a GUI/setting toggle): DNN (supervised + MC-dropout → uncertainty/confidence at
inference) or RF (semi-supervised; ensemble-based confidence).

B. Output contract

Per-molecule predictions for three channels — hERG, NaV1.5, CaV1.2 — each a blocker/non-blocker
call plus a confidence estimate (MC-dropout for DNN; ensemble spread for RF).
VERIFIED (2 Jul 2026) — exact exported CSV columns (from notebooks/make_predictions.ipynb +
components/menu.py), in order:
InChI, SMILES, MW, AlogP, HBA, HBD, MPSA, ROTB, AROMS, ALERTS, hERG, hERG_confidence, Nav1.5, Nav1.5_confidence, Cav1.2, Cav1.2_confidence.
⚠ Two parsing gotchas confirmed in source: (1) each channel call (hERG/Nav1.5/Cav1.2) is a binary
0/1 int via argmax, not a continuous probability — 1 = blocker; (2) each *_confidence is written
as a percentage string formatted "{:.1%}" (e.g. "87.3%"), so the adapter must strip % and divide
by 100. The gate wants a probability, so CToxPred2 contributes a vote (0/1) weighted by confidence, not
a P(block) — reflect this in §2 rather than averaging it into the probability pool.
Role: automatable multichannel secondary (replaces the web-only CardioDPi); hERG channel can feed the
gate, NaV1.5/CaV1.2 are context.
Source: repo README github.com/issararab/CToxPred2 (fetched), JCIM 2023/2024.

7. CardioGenAI  — endpoints/herg/cardiogenai/ (POINTER, gated; + optional discriminative votes)
A. Input contract — two entry points (repo _run.ipynb):

Generative: optimize_cardiotoxic_drug(input_smiles, herg_activity, nav_activity, cav_activity, n_generations, device).
input_smiles: str; each *_activity: 'blockers'/'non-blockers' or a (low, high) tuple of a
pIC50 range; n_generations: int (default 100); device: 'gpu'|'cpu'.
Discriminative: predict_cardiac_ion_channel_activity(input_data, prediction_type, predict_hERG, predict_Nav, predict_Cav, device).
input_data: str | list[str] | path-to-.h5; prediction_type: 'regression'|'classification' (default
'regression'); predict_*: bool.

B. Output contract

Generative → an ensemble of up to n_generations candidate SMILES conditioned on the input
scaffold + physchem and filtered by the three channels, ranked by cosine similarity of processed RDKit
descriptor vectors to the input. Output = candidate SMILES (+ similarity ranking). GATED: must be
filtered against Kunhuan's FTO-binding + FTO-vs-ALKBH5 selectivity before use.
Discriminative → per selected channel (hERG/NaV1.5/CaV1.2): pIC50 (regression; ↑ = more potent
blocker = ↑tox) or blocker/non-blocker class (classification; threshold pIC50 ≥ 5.0 = the
non-blocker cutoff, VERIFIED from the README + Optimization_Framework.py).
VERIFIED (2 Jul 2026): the discriminative results are keyed with literal labels containing a space —
"hERG pIC50", "NaV1.5 pIC50", "CaV1.2 pIC50" (see src/Optimization_Framework.py, input_data_entry[...]).
The adapter must quote these exactly. Direction: pIC50 ↑ = stronger block; map pIC50→P(block) before it
joins the gate average (see §2 / F-1).
Optional: the discriminative hERG head can join the gate ensemble as an extra vote (harmonize pIC50→P(block), see §2).
Source: repo README github.com/gregory-kyro/CardioGenAI (fetched).


Endpoint: METABOLISM — site of metabolism (RETAINED, sole-provider)
8. SMARTCyp 3.0  — endpoints/metabolism/smartcyp/ (Python 3 + RDKit — no JVM)
⚠ CORRECTION RETRACTED (2 Jul 2026 reconciliation): a mid-pass note in this doc claimed "SMARTCyp is
Java, not Python," reached by cloning the cdk/smartcyp repo (15 .java, 0 .py). That was the error:
cdk/smartcyp is the legacy Java/CDK line (versions 1.x/2.x). Primary sources — the SMARTCyp 3.0
applications note (Olsen et al., Bioinformatics 2019) and the KU group's own page — state plainly that
whereas the original SMARTCyp was Java+CDK, SMARTCyp 3.0 was rewritten in Python 3 using RDKit (Flask web
server). Build consequence: the smartcyp/ env is a plain RDKit env — no openjdk. Install the 3.0
Python source from smartcyp.sund.ku.dk, or the MDStudio_SMARTCyp wrapper (whether that wrapper is pure
Python or shells to a helper is a build-time confirmation; it does not change that 3.0 itself is Python).
Since FAME 3 was also replaced by the Python FAME3R, the entire metabolism endpoint is JVM-free.
A. Input contract

Accepted: SMILES / SDF, via the SMARTCyp 3.0 Python program (RDKit-based; from the KU 3.0 source) or the
MDStudio_SMARTCyp wrapper (Docker/REST). Batch supported (multiple structures/file). No java call.
Prep: no 3D needed (2D method; 2DSASA estimated from topology). Neutral parent recommended.

B. Output contract — a per-atom ranking table (CSV), covering the general 3A4 model plus isoform
columns for 2D6 and 2C9. The exact header string below was read from WriteResultsAsCSV.java in the
legacy cdk/smartcyp (v2.5.0-SNAPSHOT / CDK 2.2) — i.e. the Java line. It is a strong template but
NOT confirmed to be the Python 3.0 output verbatim; re-verify column names/casing against a real SMARTCyp 3.0
run at build time (the 3.0 RDKit rewrite reports the same quantities but may differ in exact headers):
Molecule,Atom,Ranking,Score,Energy,Relative Span,2D6ranking,2D6score,Span2End,N+Dist,2Cranking,2Cscore,COODist,2DSASA
Column (literal)MeaningDirectionMolecule, Atommolecule name, atom symbol+index (e.g. C.7)identifiersRankinggeneral (3A4) soft-spot rank (1 = most likely SoM)1 = top siteScoreS = E − 8·log(A) (+ empirical corrections), kJ/mol scaleLOWER = more likely metabolizedEnergyfragment activation energy (kJ/mol)LOWER = more reactiveRelative Span, Span2Endtopological span descriptors—2D6ranking / 2D6score, 2Cranking / 2CscoreCYP2D6 and CYP2C9 isoform rank/scoreLOWER score = SoMN+Dist, COODistdistance to protonated amine / carboxylate (isoform corrections)—2DSASAestimated 2D solvent-accessible surface—

Direction is inverted: the primary SoM is the atom with the lowest Score / Ranking = 1. Co-rank
atoms across models by ordinal Ranking, never by averaging Score with FAME3R's probability (F-2).
Caveat on version: the header above is the legacy CDK/Java port (cdk/smartcyp v2.5); the shipping
tool for this pipeline is SMARTCyp 3.0 (Python/RDKit), which reports the same core quantities but whose
exact header casing/extra columns must be confirmed against its own output at build time. Do not infer a
Java dependency from this header — 3.0 is Python.
The +N-oxidation penalty on tertiary alkylamine N still applies (down-ranks N-oxidation on the
pyrrolidine N of FTO-43); it is folded into Score, not a separate column.
FTO-43 relevance: the pyrrolidine tertiary amine N receives the +100 kJ/mol N-oxidation penalty →
SMARTCyp will down-rank N-oxidation there; interpret accordingly.
Source: cdk/smartcyp WriteResultsAsCSV.java + pom.xml (fetched — this is the legacy Java line, used
only as a column template); semantic field descriptions from smartcyp.sund.ku.dk/interpret_smartcyp,
/background_smartcyp. Outstanding at build time: confirm the SMARTCyp 3.0 (Python/RDKit) output
header against a real run — that is the authoritative contract, not this CDK-port header.

9. FAME3R  — endpoints/metabolism/fame3r/ (Python substitute for Java FAME 3)
A. Input contract

Accepted: SMILES / SDF. Python API + CLI (pip install fame3r / conda-forge); also NERDD REST/GUI.
Prep: FAME fingerprints (circular, atom-based, radius 5) + 14 electronic/topological descriptors —
computed internally.

B. Output contract — VERIFIED (2 Jul 2026) from the package (molinfo-vienna/FAME3R,
src/fame3r/score.py + docs/.../PythonAPI.ipynb). FAME3R is packaged as scikit-learn components, not a
turnkey CSV writer, so there is no fixed output header — the adapter builds the DataFrame:

Per-atom SoM prediction: sklearn pipeline make_pipeline(FAME3RVectorizer(input="smiles", radius=5), RandomForestClassifier(...)); the SoM signal is model.predict_proba(...)[:, 1] = probability the atom
is a site of metabolism (0–1, ↑ = more likely SoM). Atoms are supplied as atom-marked SMILES
(atom_to_marked_smiles(atom)), so the adapter must attach RDKit atom indices itself — there is no shipped
atom_id column.
Applicability-domain / reliability: a separate estimator FAME3RScoreEstimator(n_neighbors=3) whose
output feature is named FAME3RScore = mean Tanimoto similarity to the k nearest reference atoms
(higher = more in-domain/reliable).
CORRECTION: the earlier "binary threshold 0.3" was the original Java FAME 3 decision threshold;
FAME3R the package emits a raw probability and does not hard-code 0.3 — pick/justify a threshold yourself
(or co-rank ordinally with SMARTCyp per F-2). There is no separate "Shannon-entropy reliability" column in
the package; reliability = FAME3RScore.
Two questions, not three votes (skeleton): FAME3R/SMARTCyp answer where the soft spot is; the
generalist stability heads answer is it stable — agreement = confidence.
Source: FAME3R J. Cheminform. 2026 (10.1186/s13321-026-01161-1) / ChemRxiv 2025; repo molinfo-vienna/FAME3R; aweSOM/FAME3R methods (JCIM 10.1021/acs.jcim.5c00762).


Endpoint: CLEARANCE — weakest endpoint; DECOMPOSED (never one number)
10. Watanabe renal fe/CLr (via DruMAP)  — endpoints/clearance/watanabe_renal/ (WEB-ONLY, manual SOP)
A. Input contract (manual): SMILES entered at the DruMAP web app
(drumap.nibiohn.go.jp/prediction); select organism = human. No code path.
B. Output fields a manual run yields (transcribe into the ledger in this fixed shape):
FieldTypeUnit / classesDirectionfeclass / valuefraction excreted unchanged in urine (binary classifier)↑ = more renal (unchanged) routeCLrfloatrenal clearance (mL/min/kg — confirm unit at build time)↑ = faster renal clearancefu,pfloatfraction unbound in plasma (0–1; also a descriptor into the renal model)↑ = more free drug

DruMAP batches multiple endpoints in ONE session — capture #10 alongside #17 (P-gp brain), CLint,
Fa, fu,brain, Kp,uu,brain (see the DruMAP-session note in §3).
Renal-vs-hepatic fork is resolved by experiment, not this model — triage read only.
Source: DruMAP J. Med. Chem. 2023 (10.1021/acs.jmedchem.3c00481, fetched), Watanabe Sci. Rep. 2019 9:18782.

11. PKSmart  — endpoints/clearance/pksmart/ (CODE-PKG; DIRECT fold-error)
A. Input contract

Accepted: single SMILES (pksmart -s <SMILES>) or a file of newline-separated SMILES (pksmart -f <file>);
library: import pksmart; out = pksmart.predict_pk_params(smiles). pip install pksmart (py ≥3.10,<3.12).
Prep: Morgan fingerprints (RDKit) + Mordred descriptors (use mordredcommunity) — internal; pin sklearn to
the released pickle versions.

B. Output contract — human i.v. PK parameters + fold-error:
FieldQuantityUnitDirectionVDssvolume of distribution (ss)L/kg↑ = more tissue distributionCLtotal body clearancemL/min/kg↑ = faster clearance (the FTO liability; anchor ≈89.6)t½half-lifeh↑ = longerfufraction unbound in plasma0–1↑ = more freeMRTmean residence timeh↑ = longerfold-error / rangeper-parameter prediction interval×-foldDIRECT uncertainty; widens out-of-domain

Two-stage RF: predicts animal PK (VDss/CL/fu for rat/dog/monkey) → human RF.
VERIFIED (2 Jul 2026) — the human output column names (from the repo's own external-test CSVs,
srijitseal/PKSmart): human_CL_mL_min_kg, human_VDss_L_kg, human_fup, human_thalf,
human_MRT (keyed to smiles_r, the standardized SMILES). Note the units are baked into the column
names — CL is confirmed mL/min/kg (settles the F-3 unit for PKSmart). The animal intermediates use the
parallel scheme {dog,monkey,rat}_{CL_mL_min_kg,VDss_L_kg,fup}.
Still read at build time: whether predict_pk_params() returns the fold-error / prediction interval
in the same object or a companion — the example CSVs above are the point predictions; the fold-error is a
documented output but its field name wasn't in these files. CL is weak (R²=0.31, GMFE 2.43/2.46) → coarse
binning + relative within-series ranking only; surface the fold-error, never the bare CL number.
Source: PyPI pksmart v3.0.1 metadata (fetched) + repo example CSVs (srijitseal/PKSmart), J. Cheminform.
2025 (10.1186/s13321-025-01066-5).

12. PBPK (OSP / PK-Sim)  — endpoints/clearance/pbpk/ (POINTER, integrator; R/.NET)
A. Input contract

Not a per-molecule predictor. A PBPK model is built in PK-Sim (GUI or PKML) and parameterized with
other endpoints' outputs (CL, fu, permeability, logP). Driven via the ospsuite R package (R 4.x +
.NET 8 + OSP binaries). Shortlist only; out of the bulk loop.

B. Output contract

Simulation outputs, not a fixed prediction schema: concentration–time profiles C(t) and derived
exposure metrics (Cmax, AUC, etc.) evaluated in R. No standardized column set — the "output" is whatever
the modeler extracts; transcribe key metrics to the ledger like the web-only tools.
Source: github.com/Open-Systems-Pharmacology, ospsuite docs (per provenance §B#13).


Endpoint: DISTRIBUTION / BBB / CNS
13. BBB Score  — endpoints/distribution/bbb_score/ (CODE-ALGO rule)
A. Input contract: SMILES → RDKit descriptors (#aromatic rings, heavy atoms, an MWHBN term, TPSA)
plus a pKa value (external pKa predictor — standardize ONE pKa source across BBB Score + CNS MPO + SFI).
B. Output contract: BBB_Score — single float on 0–6; ↑ = more likely passive BBB penetrant
(Gupta 2019; AUC 0.86). Deterministic; reimplement from the paper and unit-test vs gkxiao/BBB-score.
Passive filter only — not brain-exposure prediction.

Source: Gupta et al. J. Med. Chem. 2019 (10.1021/acs.jmedchem.9b01220); RDKit ports.

14. BOILED-Egg  — endpoints/distribution/boiled_egg/ (CODE-ALGO rule; shared with permeability)
A. Input contract: SMILES → WLOGP (RDKit Crippen MolLogP) + TPSA (RDKit CalcTPSA).
B. Output contract: two booleans —
FieldTypeMeaningDirectionHIA (white region)boolpredicted passive GI absorptionTrue = absorbedBBB (yolk region)boolpredicted passive brain penetrationTrue = BBB permeant

VERIFIED (2 Jul 2026) — mechanism confirmed from a working open implementation, bfmilne/pyBOILEDegg
(PyBOILEDegg.py). The two regions are each a closed curve in (x = TPSA, y = WLOGP) space, and membership
is a point-in-polygon test (shapely: Point(tpsa, wlogp).within(gia_ellipse / bbb_ellipse)) — not an
inequality on a single axis. The repo ships the boundary as explicit vertex lists (gia_coords = white/HIA,
bbb_coords = yolk/BBB; ~50 points each), which are directly reusable; they trace the Daina & Zoete ellipses
(each defined analytically by foci (x₁,x₂),(y₁,y₂) + major axis d). Consistent with the paper, the BBB
yolk is the more restrictive inner region (≈ TPSA < 79 Å², WLOGP ≈ +0.4 to +6.0) and the HIA white
extends further in TPSA (to ≈ 142). Coordinate convention matters: TPSA on x, WLOGP on y — swapping them
silently inverts the call.
Implementation choice for the pipeline: either embed the pyBOILEDegg polygon vertices (fast, exact to that
impl) or reconstruct the analytic ellipses from the paper's foci+major-axis; both give the same two booleans.
One registered implementation serves both distribution (BBB) and permeability (HIA).
Source: Daina & Zoete ChemMedChem 2016 (10.1002/cmdc.201600182, open access); implementation
github.com/bfmilne/pyBOILEDegg (fetched 2 Jul 2026).

15. CNS MPO  — endpoints/distribution/cns_mpo/ (CODE-ALGO rule)
A. Input contract: SMILES + most-basic pKa → six physchem: MW, cLogP, cLogD, HBD, most-basic pKa, TPSA
(cLogP via Crippen, TPSA via Ertl). Same pKa source as BBB Score.
B. Output contract: CNS_MPO — float on 0–6 (sum of six desirability transforms; monotonic on
MW/cLogP/cLogD/HBD/pKa, hump-shaped on TPSA); ↑ = more CNS-desirable. Optionally the six component
desirability values (0–1 each). Rough filter only (weak on the PET-tracer set, AUC 0.53).

Source: Wager et al. ACS Chem. Neurosci. 2010/2016; port Adam-maz/CNS_MPO_calculator.

16. P-gp (efflux substrate)  — endpoints/distribution/pgp/ (via generalists)
A. Input contract: SMILES → read from the generalist outputs (no separate service); optional dedicated
TDC Pgp_Broccatelli head.
B. Output contract: Pgp_Broccatelli (from ADMET-AI) and/or the ADMETlab P-gp field — prob[0–1] of
P-gp substrate/inhibitor; ↑ = more efflux liability. Narrow domain — usable only in-domain; not a gate.

Source: TDC Pgp_Broccatelli; ADMET-AI/ADMETlab records above.

17. Watanabe P-gp brain (via DruMAP)  — endpoints/distribution/watanabe_pgp_brain/ (WEB-ONLY)
A. Input contract (manual): same DruMAP session as #10 (batch them).
B. Output fields a manual run yields:
FieldTypeUnit / classesDirectionP-gp brain effluxclassNER.class (net efflux ratio class, e.g. "Low")↑ efflux = ↓ brain penetrationKp,uu,brainfloatunbound brain-to-plasma ratio (rat)↑ = more brain penetration (≥0.5 ≈ penetrant)fu,brainfloatfraction unbound in brain homogenate↑ = more free in CNS

Passive/efflux score only; real CNS answer = experimental Kp,uu. BBB desirable, not a gate.
Source: Watanabe 2021 J. Med. Chem.; DruMAP (10.1021/acs.jmedchem.3c00481, fetched).


Endpoint: PLASMA PROTEIN BINDING
18. OCHEM PPB  — endpoints/ppb/ochem_ppb/ (CODE-API, async)
A. Input contract

Accepted: SMILES / SDF; batch via the $$$$ separator. REST (async):
https://ochem.eu/modelservice/getPrediction.do?modelId=<ID>&mol=<MOLECULE> — submit → returns a task ID →
poll every 5–10 s until ready (also rest.ochem.eu/predict). Pin modelId of the consensus model
at ochem.eu/article/29 (Han 2025) — the numeric id is a build-time lookup on the OCHEM model-service
UI (login/navigation; can't be reliably scraped).

B. Output contract

Returned quantity: plasma-protein binding = fraction/percent bound (consensus model; R²≈0.90/0.91).
↑ = more bound (less free). OCHEM predictions typically also carry an accuracy/error estimate and an
applicability-domain distance. Exact response JSON field names + result unit (fraction vs %)
UNVERIFIED — read from docs.ochem.eu and the pinned model page at build time.
Not a gate (modulator); single tool acceptable. Wrap with retry/backoff + response caching (async service).
Source: OCHEM REST docs (docs.ochem.eu), model page ochem.eu/article/29, EJPS 2025 (per provenance §B#20).


Endpoint: SOLUBILITY
19. SFI (Solubility Forecast Index)  — endpoints/solubility/sfi/ (CODE-ALGO rule)
A. Input contract: SMILES → #aromatic rings (rdkit.Chem.rdMolDescriptors.CalcNumAromaticRings) +
cLogD(7.4) (the non-trivial input: derive from cLogP + pKa via Henderson–Hasselbalch, or take logD from
OPERA #21; anchor to measured series logD ≈ 1).
B. Output contract: SFI = cLogD(7.4) + (#aromatic rings) — single float; LOWER = better
(more soluble). Uncertainty = SFI-vs-generalist (Solubility_AqSolDB) discrepancy.

Source: Bhal/GSK SFI concept; Pat Walters "Solubility Forecast Index" blog (the reference Gilson shared).


Endpoint: LIPOPHILICITY (anchor to measured series logD ≈ 1)
20. RDKit Crippen  — endpoints/lipophilicity/rdkit_crippen/ (CODE-PKG)
A. Input contract: RDKit mol (from SMILES). B. Output contract:
rdkit.Chem.Crippen.MolLogP(mol) → Wildman–Crippen logP (float, log units; ↑ = more lipophilic);
MolMR(mol) → molar refractivity (float). This is exactly SwissADME's WLOGP lens.

Source: RDKit Chem.Crippen; Wildman & Crippen 1999.

21. OPERA  — endpoints/lipophilicity/opera/ (CODE-STANDALONE + AD; MATLAB MCR + Java)
A. Input contract: CSV of SMILES; internal QSAR-ready standardization. CLI:
./run_OPERA.sh <MCR_path> -d in.csv -o preds.txt -e LogP LogD pKa ... -v 1. Multi-endpoint.
B. Output contract — VERIFIED (2 Jul 2026) from OPERA source (OPERA_Source_code/OPERA.m header
construction + output_options.txt). First column is MoleculeID; then for each requested endpoint X:
Column patternMeaning<X>_predpredicted value (endpoint units)AD_<X>applicability-domain flag (0/1, in/out of domain)AD_index_<X>continuous AD / similarity index (0–1)Conf_index_<X>confidence / accuracy-estimate index (0–1; ↑ = more reliable) — DIRECT uncertainty
Confirmed literally in source for the tox endpoints (e.g. AD_LD50, AD_index_LD50, Conf_index_LD50;
likewise ..._EPA/_GHS/_NT/_VT); the physchem endpoints follow the identical pattern (LogP_pred, AD_LogP,
AD_index_LogP, Conf_index_LogP, etc.). output_options.txt calls the four default fields Molecule ID,
pred, AD, AD_index (a.k.a. Sim_index), Conf_index. Optional flags add nearest-neighbour and descriptor
columns. Endpoint units: LogP (log Kow), LogD (log), pKa_a/pKa_b (acid/base), FuB (fraction),
Clint (µL/min/10⁶ cells), Caco2 (logPapp). Direction: LogP/LogD ↑ = more lipophilic.

Resolved: the _pred/AD_/AD_index_/Conf_index_ casing is now confirmed from source (previously
flagged as version-drift-uncertain). Note there is no _predRange column in this source version — the
interval is carried by AD_index/Conf_index, not a separate range column (earlier draft over-listed it).
Multi-endpoint reuse: OPERA logD/pKa can standardize SFI/BBB/CNS-MPO; FuB cross-checks OCHEM PPB; Clint cross-checks metabolism.
Source: github.com/NIEHS/OPERA README (fetched), Mansouri J. Cheminform. 2018.

22. SwissADME  — endpoints/lipophilicity/swissadme/ (WEB-SUBSTITUTABLE)
A. Input contract: SMILES (web swissadme.ch, no API) — or reconstruct in code.
B. Output contract (lipophilicity block; Daina 2017 Sci. Rep.): five method values + consensus, all
log units, ↑ = more lipophilic:
FieldReproducible in code?iLOGPNo (SwissADME-internal GB/SA — proprietary)XLOGP3Yes (external XLOGP3 CLI v3.2.2)WLOGPYes (= RDKit Crippen #20)MLOGPYes (Moriguchi formula)Silicos-IT Log PNo (defunct FILTER-IT)Consensus Log Po/wmean of the 5

In-code consensus = mean of the 3 reproducible lenses (WLOGP/MLOGP/XLOGP3), optionally + OPERA logD;
lose iLOGP + SILICOS-IT. The uncertainty signal is the spread across lenses — convergence = trust;
scatter → lean on measured logD ≈ 1. Web only if the exact 5-way consensus is needed on the shortlist.
Source: Daina, Michielin, Zoete Sci. Rep. 2017 (10.1038/srep42717) (per provenance §B#24).


Endpoint: PERMEABILITY (aggregate-only — no own model)
23. Permeability  — endpoints/permeability/ (consumes generalists + BOILED-Egg)

No dedicated model. Consumes: Caco2_Wang (cm/s log Papp, ↑ permeable), HIA_Hou (P absorbed),
PAMPA_NCATS (P permeable), Bioavailability_Ma / %F (P bioavailable — weak, treat with suspicion),
Pgp_Broccatelli (P efflux) from ADMET-AI/ADMETlab, plus BOILED-Egg HIA boolean (#14).
May be partly moot given possible intratumoral/osmotic-pump delivery. KEEP as aggregate.


Endpoint: STRUCTURAL ALERTS
24. PAINS / BRENK  — endpoints/structural_alerts/pains_brenk/ (CODE-PKG, RDKit)
A. Input contract: RDKit mol. rdkit.Chem.FilterCatalog with FilterCatalogParams.FilterCatalogs.PAINS
(A/B/C) and BRENK.
B. Output contract: per catalog — a match / no-match bool, a list of matched filter entries
(name/description), the matched-atom substructure, and a count of alerts. (ADMET-AI also emits
PAINS_alert / BRENK_alert / NIH_alert counts as a shortcut.) Direction: more alerts = more flagged
(soft filter, over-flags — look-closer, not auto-kill; matters because the FTO assay is fluorescence-based).

Source: RDKit FilterCatalog; Baell & Holloway 2010 (PAINS), Brenk et al. 2008 (BRENK).


Endpoint: SYNTHESIZABILITY (escalating rigor ladder)
25. SAscore  — endpoints/synthesizability/sascore/ (CODE-PKG, RDKit Contrib)
A. Input contract: RDKit mol; vendor sascorer.py + fpscores.pkl.gz from $RDBASE/Contrib/SA_Score.
B. Output contract: sascorer.calculateScore(mol) → float on 1–10; LOWER = easier to synthesize.

Source: Ertl & Schuffenhauer J. Cheminform. 2009; RDKit Contrib/SA_Score.

26. RAscore  — endpoints/synthesizability/rascore/ (CODE-PKG; 2nd opinion)
A. Input contract: SMILES (isolate a 2021-era TF/sklearn env; health-check pins first).
B. Output contract: prob[0–1] that a synthetic route is findable by AiZynthFinder (binary
retrosynthetic-accessibility classifier); ↑ = more likely synthesizable.

Source: reymond-group/RAscore; Thakkar et al. Chem. Sci. 2021 (10.1039/D0SC05401A).

27. AiZynthFinder  — endpoints/synthesizability/aizynthfinder/ (CODE-PKG; route search, shortlist)
A. Input contract: target SMILES + a configured stock set (ZINC/Enamine/ACD) + policy model
(pip install aizynthfinder; RDKit + TF/PyTorch policy).
B. Output contract — VERIFIED (2 Jul 2026) from aizynthfinder/analysis/tree_analysis.py (the dict
returned by AiZynthFinder.extract_statistics()). The per-target statistics keys are:
is_solved (bool — route to purchasable precursors found; note the key is is_solved, not solved,
which is the internal per-node key), number_of_nodes, number_of_routes, number_of_steps,
number_of_precursors, number_of_precursors_in_stock, and top_score (score of the top-ranked
route; the default scorer is "state score" 0–1, ↑ = better). Full route trees (reactions + precursor SMILES)
come from RouteCollection.dict_with_scores() / .to_dict(), keyed reaction_tree, route_metadata,
all_scores. Direction: is_solved=True = route found; higher top_score = better route.

For the shortlist adapter, the go/no-go field is is_solved; rank survivors by top_score and
number_of_steps.
Source: MolecularAI/aizynthfinder (analysis/tree_analysis.py, analysis/routes.py); Genheden et al.
J. Cheminform. 2020 (10.1186/s13321-020-00472-1).


Endpoint: TOXICITY
28. Toxicophores  — endpoints/toxicity/toxicophores/ (CODE-PKG, RDKit)
A. Input contract: RDKit mol; rdkit.Chem.FilterCatalog (BRENK/NIH/ChEMBL alert catalogs — pick and
document ONE source; BRENK default, optionally a ToxAlerts SMARTS export).
B. Output contract: per chosen catalog — match/no-match bool + matched alert names + count.
Distinct from #24 by intent (toxicity vs assay-interference), not mechanism. More alerts = more flagged.

Source: RDKit FilterCatalog.

29. ProTox 3.0  — endpoints/toxicity/protox/ (WEB-ONLY, manual SOP)
A. Input contract (manual): SMILES (or draw) at tox.charite.de; select "ALL models" (default is
acute tox + targets only).
B. Output fields a manual run yields (transcribe in this fixed shape):
FieldTypeUnit / classesDirectionLD50floatmg/kg (predicted median lethal dose)LOWER = more toxicToxicity classenum 1–6acute oral tox class1 = most toxic, 6 = leastPrediction accuracy%reported per acute-tox prediction↑ = more confidentPer-endpoint predictionsclass + prob"Active"/"Inactive" + probability[0–1]Active = toxic; prob→1 = more confidentToxicity targetsname + fit + similarityoff-target hits—
Per-endpoint table spans: organ toxicity (hepato/neuro/nephro/cardio/respiratory), toxicological
endpoints (carcinogenicity, mutagenicity, cytotoxicity, immunotoxicity, BBB, clinical, ecotox,
nutritional), the 12 Tox21 pathways, 14 MIE targets, 15 tox off-targets, and 6 metabolism
targets — the italicized/off-target items have no automatable bulk substitute (only ProTox provides them).

Direction summary: Active = predicted toxic; probability closer to 1 = higher confidence; LD50 lower and
class lower (1) = more dangerous.
Source: ProTox 3.0 NAR 2024 (10.1093/nar/gkae303, fetched).


Endpoint: DRUGLIKENESS (context, not gates)
30. Lipinski / Veber / QED  — endpoints/druglikeness/lipinski_veber_qed/ (CODE-PKG, RDKit)
A. Input contract: RDKit mol. rdkit.Chem.Descriptors/Lipinski (MW, HBD, HBA, RotB, TPSA, MolLogP) +
rdkit.Chem.QED.qed(mol).
B. Output contract:
FieldTypeMeaningDirectionLipinski Ro5 violationsint 0–4 (or bool pass)MW≤500, HBD≤5, HBA≤10, logP≤5fewer violations = more drug-likeVeberbool passRotB ≤10 and TPSA ≤140pass = more drug-likeQEDfloat 0–1quantitative estimate of drug-likeness↑ = more drug-like

Context/POINTER — run by the lab, not a gate.
Source: RDKit Descriptors/Lipinski/QED; Bickerton et al. Nat. Chem. 2012 (QED), Lipinski 2001, Veber 2002.


§2 — Per-endpoint aggregator input maps (contributing fields → common quantity + transform)
Each map lists the fields each aggregate.py consumes, the common quantity it harmonizes onto, the
transform from each model's raw output, and any output that cannot be cleanly mapped (→ §3).
hERG (GATE) — target = P(block) on 0–1, then harmonize-then-weight-toward-sensitivity
ModelField(s)Transform → P(block)BayeshERGscore; alea,episscore is already P(block) → identity; alea/epis feed the split-case adjudicatorCardioTox netpredict() valuealready P(hERG blocker) → identity (confirm scalar/array shape)CToxPred2hERG-channel 0/1 vote + %-confidence stringvote → weighted vote (NOT the prob average); confidence → weight/adjudicatorADMET-AIhERGpre-screen P(block) → identityADMETlab 3.0hERG head + uncertaintypre-screen P(block) → identity (field name TBD)CardioGenAI (optional vote)discriminative hERGregression pIC50 → P(block) needs a mapping (threshold pIC50≥5 or logistic) — F-1; classification → P directly

Common quantity: P(block), 0–1, with a decision threshold. Unanimous safe → pass; unanimous blocker →
fail (or CardioGenAI redesign if a valuable, FTO-selective hit); split → adjudicate with BayeshERG
alea/epis + CToxPred2 multichannel (high-uncertainty disagreement = "measure it").
Weight toward sensitivity, not plain mean.

metabolism — TWO quantities, not three votes

Stability (whole-molecule): Clearance_Hepatocyte_AZ, Clearance_Microsome_AZ (ADMET-AI) + ADMETlab
metabolic-stability head → CLint-like number (↑ = less stable).
Site-of-metabolism (per-atom soft-spot rank): SMARTCyp Rank/Score (per isoform 3A4/2D6/2C9;
lower Score = SoM) and FAME3R per-atom SoM prob (↑ = SoM; raw 0–1 probability, no hard-coded 0.3
cutoff — that threshold was the legacy Java FAME 3; co-rank ordinally per §3-F2).
Common quantity for SoM: a per-atom ordinal soft-spot ranking aligned on atom index (NOT a shared
numeric scale — SMARTCyp Score is inverted/kJ-mol, FAME3R is a 0–1 prob → rank each, then compare top
atoms — F-2). Confidence = generalist stability vs SoM agreement.

clearance — DECOMPOSED; renal vs hepatic explicit; never one number
ComponentModel → fieldUnitNoteRenalWatanabe fe, CLr (+ fu,p) [web]fe class; CLr mL/min/kg?manual shortlist readHepaticmetabolism SoM (SMARTCyp/FAME3R) + Clearance_Hepatocyte_AZ/Clearance_Microsome_AZ + OPERA Clint_predµL/min/10⁶ cells; mL/min/g; µL/min/10⁶the CLint conditional specialistAggregate / totalPKSmart CL + fold-errormL/min/kgranking only (R²=0.31); surface fold-errorIntegratorPBPK C(t) → Cmax/AUC [shortlist]—consumes CL/fu/permeability

Do NOT combine the four clearance numbers numerically — different units and matrices (F-3). Keep renal,
hepatic, and aggregate as separate decomposed reads; the renal-vs-hepatic fork is resolved by experiment.

distribution / BBB — passive-penetration flag separate from efflux flag
SignalModel → fieldTransformPassive penetrationBBB Score (0–6), CNS MPO (0–6), BBB_Martins (P), BOILED-Egg BBB (bool)map each to penetrant / borderline / non flag and vote (incompatible scales — F-4)EffluxPgp_Broccatelli (P), Watanabe P-gp NER.class [web], Kp,uu,brain [web]efflux/penetration flags

Real answer = experimental Kp,uu. BBB is desirable, not a gate — this endpoint is triage only.

ppb — common quantity = fraction bound (0–1)
Model → fieldTransformOCHEM PPB (primary)fraction/percent bound → normalize to 0–1 (confirm fraction vs % — F-7)ADMET-AI PPBR_AZ% bound → /100OPERA FuB_predfraction unbound → 1 − FuB

Direction: ↑ = more bound (less free). Not a gate; single tool acceptable, cross-checks optional.

solubility — common quantity = relative solubility rank (uncertainty = SFI-vs-generalist discrepancy)
Model → fieldDirectionTransformSFI (primary)LOWER = betternegate for co-ranking (or rank ordinally)Solubility_AqSolDB (ADMET-AI)↑ log S = bettercross-check

Direction inversion between the two — reconcile before ranking. Likely a series strength (low-aromatic oxetane).

lipophilicity — common quantity = logD consensus (log units), anchored to measured logD ≈ 1
Model → fieldTransformRDKit Crippen MolLogPlogP → convert to logD via pKa (or keep as WLOGP lens)OPERA LogD_pred (+ Conf_index_LogD)logD → identity; carry AD/confSwissADME WLOGP/MLOGP/XLOGP3reproducible 3-lens mean (+ optional OPERA logD)

logP vs logD (F-12): for the di-basic FTO series logP ≠ logD at pH 7.4 — compare logD-to-logD; SFI
needs cLogD. Spread across lenses = the flag; scatter → lean on measured logD ≈ 1.

permeability (aggregate-only) — permeability flag + absorption flag

Consumes Caco2_Wang (log Papp, cm/s), HIA_Hou (P), PAMPA_NCATS (P), Bioavailability_Ma/%F
(P — weak, suspicion), Pgp_Broccatelli (P efflux), BOILED-Egg HIA (bool). No single scalar.

structural_alerts — union of PAINS/BRENK matches (soft flag; counts + matched-alert list).
synthesizability — escalating tier (the ladder IS the confidence signal)

SAscore (1–10, lower=easier) → RAscore (P route findable) → AiZynthFinder (solved bool + routes). Different
scales → report a tier/flag, not one scalar.

toxicity — bulk-substitute panel (automatable) + ProTox confirmatory (web, shortlist)

Bulk: ADMET-AI LD50_Zhu, DILI, hERG, AMES, Carcinogens_Lagunin, ClinTox, Skin_Reaction +
ADMETlab organ-tox heads (nephro/neuro/cyto/immuno/genotox) + toxicophores alerts → per-endpoint P(toxic).
Shortlist: ProTox LD50 (mg/kg), class (1–6), Active/Inactive + prob per endpoint (the richer read).
LD50_Zhu (−log mol/kg scale) is NOT directly comparable to ProTox LD50 (mg/kg) — F-5. Keep them as
separate reads (bulk triage vs shortlist confirmation).

druglikeness — context flags only (Lipinski violations, Veber pass, QED); no gate aggregation.

§3 — Flags list (ambiguous/unmappable outputs, missing units/direction, build-time reads)
Unmappable / cross-scale (the aggregator author must know before writing aggregate.py):

F-1 (hERG): CardioGenAI discriminative regression emits pIC50, not P(block) → needs a
pIC50→probability mapping (threshold pIC50 ≥ 5, or a logistic/calibration) before joining the P(block)
average. (Update 2 Jul 2026: RESOLVED — CardioGenAI keys "hERG pIC50"/"NaV1.5 pIC50"/"CaV1.2 pIC50"
and CToxPred2 columns are now verified — CToxPred2 emits a 0/1 vote + %-string confidence, not a
probability, so it joins as a weighted vote, not in the probability average. CardioTox net now RESOLVED
too — repo Abdulk084/CardioTox exists (earlier "unavailable" note was wrong); predict() returns a NumPy
array of P(block). Only remaining hERG gap: the ADMETlab hERG column literal name — one of its 119 CSV
columns, needs a single live /api/admetCSV call (F-6).)*
F-2 (metabolism): SMARTCyp Score (inverted, kJ/mol scale, lower=SoM) and FAME3R SoM probability
(0–1) cannot share a numeric scale — co-rank atoms by ordinal per-atom rank, not by
averaging values. (Update 2 Jul 2026: RESOLVED — SMARTCyp CSV column template read from the legacy
CDK port (…,Atom,Ranking,Score,Energy,…,2DSASA; co-rank on Ranking; re-verify header against the 3.0
Python output). SMARTCyp 3.0 is Python/RDKit — no openjdk (a mid-pass note saying "Java" read the
legacy cdk/smartcyp repo and was retracted; see #8). FAME3R verified as sklearn predict_proba[:,1]
per-atom prob + separate FAME3RScore AD; the "0.3" threshold was the old Java FAME 3, not FAME3R.)*
F-3 (clearance): four different clearance units — PKSmart CL (mL/min/kg), ADMET-AI
Clearance_Hepatocyte_AZ (µL/min/10⁶ cells), ADMET-AI Clearance_Microsome_AZ (mL/min/g — confirm),
OPERA Clint (µL/min/10⁶ cells), DruMAP CLint (µL/min/mg). Never combine numerically; keep decomposed.
F-4 (distribution): BBB Score & CNS MPO (0–6 desirability), BBB_Martins (probability), BOILED-Egg
(bool) are on incompatible scales — map each to penetrant/borderline/non and vote; do not average.

Missing/uncertain units or direction (read before use — a wrong value corrupts aggregation):

F-5 (ADMET-AI regression): (Update 2 Jul 2026: RESOLVED from admet_ai/resources/data/admet.csv —
Clearance_Hepatocyte_AZ = uL/min/10⁶ cells, Clearance_Microsome_AZ = uL/min/mg, LD50_Zhu =
log(1/(mol/kg)) so higher = more toxic. LD50_Zhu is not comparable to ProTox LD50 (mg/kg) — keep
separate. PPBR_AZ = %.)*
F-17 (ADMET-AI reliability — NEW, 2 Jul 2026): ADMET-AI v2's own reported metrics (same admet.csv) show
VDss_Lombardo R² = −1.21 and Half_Life_Obach R² = −2.39 — worse than predicting the mean. The
distribution/PK aggregators must exclude ADMET-AI from VDss and half-life entirely; both clearance heads
are weak (R² ≈ 0.26–0.28) → low-weight/qualitative only. ADMET-AI's classification heads are strong
(HIA 0.99, Pgp 0.95, CYP-inhibition 0.89–0.94, BBB 0.90, hERG 0.84) and can be trusted as normal votes.
F-12 (lipophilicity): logP ≠ logD for the di-basic FTO series at pH 7.4 — reconcile via pKa; compare
logD-to-logD; SFI needs cLogD not cLogP.
F-13 (pKa source): BBB Score, CNS MPO, and SFI (via cLogD) all require a pKa — standardize ONE pKa
source (OPERA pKa_pred or a single predictor) across them or results are not internally comparable.

Output docs that must be read against the installed package/service at build time:

F-6 (ADMETlab 3.0): (Update 2 Jul 2026: the request/transport contract is now VERIFIED from the
ToxMCP/admetlab-mcp wrapper — POST /api/admet (fallback /api/single/admet) with
{"SMILES":[...], "feature":bool, "uncertain":bool} → taskId, then POST /api/admetCSV with
{"taskId":...} → CSV; wash via /api/washmol; optional X-API-KEY. Uncertainty is a per-endpoint
Youden's-index high/low-confidence flag; architecture DMPNN-Des.) Only remaining unknown: the
literal 119 endpoint column names inside the returned CSV — the wrapper passes the CSV through, so
capture the header from one live /api/admetCSV call at build time. Async + reportedly unstable →
retry/backoff + cache.
F-7 (OCHEM PPB): response JSON field names + result unit (fraction vs %) — read from docs.ochem.eu;
numeric modelId for ochem.eu/article/29 is a manual OCHEM-UI lookup (~30 s, login/navigation).
F-8 (OpenADMET): (Update 2 Jul 2026: RESOLVED from inference/inference.py — output columns are
OADMET_PRED_{tag}_{task} + OADMET_STD_{tag}_{task} (native per-prediction σ, DIRECT uncertainty);
classification tasks go through predict_proba. Pretrained weights are pulled from S3, not HuggingFace
and not retrain-only.)*
F-9 (BOILED-Egg): (Update 2 Jul 2026: RESOLVED — mechanism + usable constants confirmed from
bfmilne/pyBOILEDegg: two point-in-polygon regions in (x = TPSA, y = WLOGP) space (white/HIA,
yolk/BBB), vertex lists shipped in the repo and tracing the Daina & Zoete ellipses. Embed the polygons or
reconstruct the analytic ellipse; watch the axis convention.)*
F-10 (OPERA): (Update 2 Jul 2026: RESOLVED from OPERA_Source_code/OPERA.m + output_options.txt
— header is MoleculeID, then <X>_pred, AD_<X>, AD_index_<X>, Conf_index_<X> per endpoint; no
separate _predRange column in this source version.)* Heavy MCR+Java runtime → still isolate.
F-11 (AiZynthFinder): (Update 2 Jul 2026: RESOLVED from analysis/tree_analysis.py — stats keys
is_solved (not solved), top_score, number_of_steps, number_of_routes, number_of_nodes,
number_of_precursors, number_of_precursors_in_stock; go/no-go = is_solved, rank by top_score.)*
F-1/F-2 field names: (Update 2 Jul 2026: CToxPred2, SMARTCyp, FAME3R, PKSmart, CardioGenAI literal
output names are now verified (see §4), including CardioTox net (repo exists); the only literal names
still pending are ADMETlab's 119 CSV columns (one live /api/admetCSV call).)*

Web-only / manual-SOP outputs (never in the bulk loop):

F-14 (DruMAP one session): batch renal fe/CLr/fu,p (#10) + P-gp brain NER.class (#17) + CLint +
Fa + fu,brain + Kp,uu,brain in ONE manual session; define the fixed ledger transcription shape.
F-15 (ProTox): web-only, no bulk API; Active/Inactive + probability per endpoint + LD50 (mg/kg) + class
(1–6). The off-target / MIE / respiratory / eco / nutritional endpoints have no automatable substitute.

Cross-cutting:

F-16 (standardization): no model documents desalting/protonation handling for the FTO di-cation —
define ONE upstream standardization (canonical parent, defined neutralization/protonation state) feeding
every model, or hERG / SoM / logD predictions diverge silently. This is the single most important
build-time decision for input-contract consistency.


§4 — Changelog: second verification pass (2 Jul 2026)
These items were resolved by cloning the upstream repos and reading example outputs / hardcoded headers /
predict_proba usage directly — no model execution required. Each is now marked VERIFIED in §1 with the
file cited. This is the "tool calls I'd deferred but could actually make now" pass.
#ModelWhat was resolvedPrimary source read1CToxPred2Exact 16-col export incl. hERG (0/1 int) + hERG_confidence ("{:.1%}" string), Nav1.5/Cav1.2 sameissararab/CToxPred2 notebooks/nutils.py, components/menu.py2CardioGenAIDiscriminative keys "hERG pIC50"/"NaV1.5 pIC50"/"CaV1.2 pIC50"; non-blocker cutoff pIC50 ≥ 5.0gregory-kyro/CardioGenAI src/Optimization_Framework.py, README3PKSmartColumns human_CL_mL_min_kg, human_VDss_L_kg, human_fup, human_thalf, human_MRT (CL = mL/min/kg)srijitseal/PKSmart external-test CSVs4FAME3Rsklearn predict_proba[:,1] per-atom SoM prob + separate FAME3RScore AD; no shipped CSV; "0.3" was old FAME 3molinfo-vienna/FAME3R score.py, PythonAPI.ipynb5SMARTCypCSV header Molecule,Atom,Ranking,Score,Energy,Relative Span,2D6ranking,2D6score,Span2End,N+Dist,2Cranking,2Cscore,COODist,2DSASA (from the legacy CDK/Java line — template only; re-verify vs 3.0 output); 3.0 is Python 3 + RDKit, NOT Java — no openjdk (retracts an earlier "it's Java" note that read the legacy repo)cdk/smartcyp WriteResultsAsCSV.java; SMARTCyp 3.0 note (Olsen 2019) + smartcyp.sund.ku.dk6OpenADMETOADMET_PRED_{tag}_{task} + OADMET_STD_{tag}_{task} (native σ); weights from S3 not HFOpenADMET/openadmet-models inference/inference.py, comparison/posthoc.py7AiZynthFinderStats keys is_solved (not solved), top_score, number_of_steps, number_of_routes, number_of_precursors[_in_stock]MolecularAI/aizynthfinder analysis/tree_analysis.py8ADMET-AI v2All 52 heads' units/task_type/metrics; clearance = uL/min/10⁶ cells & uL/min/mg; LD50 = log(1/(mol/kg)); PPBR = %; VDss R²=−1.21, t½ R²=−2.39 → discard those (F-17)swansonk14/admet_ai resources/data/admet.csv9OPERAHeader MoleculeID, <X>_pred, AD_<X>, AD_index_<X>, Conf_index_<X>; no _predRange colNIEHS/OPERA OPERA_Source_code/OPERA.m, output_options.txt10ADMETlab 3.0Uncertainty = Youden-index high/low-confidence flag (not continuous σ); DMPNN-DesNAR 2024 paper (academic.oup.com/nar/…/gkae236)11ADMETlab 3.0 (API)Request/transport contract: POST /api/admet→taskId→POST /api/admetCSV; payload {SMILES,feature,uncertain}; wash /api/washmolToxMCP/admetlab-mcp client/admet_client.py, settings.py12CardioTox netload_ensemble().predict(smiles, probabilities=False) → NumPy array of P(block); probabilities=True→[P(non),P(block)]; repo existsAbdulk084/CardioTox cardiotox/model.py, README13BOILED-EggTwo point-in-polygon regions in (x=TPSA, y=WLOGP); white=HIA, yolk=BBB; usable vertex listsbfmilne/pyBOILEDegg PyBOILEDegg.py + Daina & Zoete 2016
Corrections: One stands — CardioTox net's repo Abdulk084/CardioTox was briefly flagged unavailable → it
exists, the 404 was a rate-limited API query (#12). One is retracted: a mid-pass note relabeled
SMARTCyp as "Java/CDK" (#5) after reading the legacy cdk/smartcyp repo — but SMARTCyp 3.0 is Python 3 +
RDKit (primary sources), so that relabel was the error and the metabolism env needs no openjdk.
One new flag raised: F-17 (ADMET-AI VDss/half-life unusable; clearance low-weight).
Still genuinely build-time / needs a live or authenticated session (the honest residue):

ADMETlab CSV columns (F-6): the request/transport contract is verified; the literal 119 endpoint
column names need one live /api/admetCSV call to capture the header (nothing else about the model).
OCHEM PPB modelId (F-7): an authenticated OCHEM-UI lookup (~30 s); the REST field names could be read
from docs.ochem.eu but the numeric model id is behind login.
DruMAP (F-14) / ProTox (F-15): per-molecule predictions run only through their web UIs (no bulk API);
batch them in one manual session as already specified.

Everything else that was flagged as "read at build time" for a literal output name has now been read from
source. CardioTox net and BOILED-Egg are resolved (they were on the earlier "still open" list). What
truly can't be pre-read is a value that only exists once the model or web service is actually invoked.

Resume marker
All 30 finalized model entries have I/O records (§1), an aggregator input map per endpoint (§2), a
consolidated flag list (§3), and a verification changelog (§4). As of the second pass (2 Jul 2026), the
literal output contracts that were reachable from source are verified (see §4); what genuinely still needs
a live/authenticated session is narrow — ADMETlab's 119 CSV column names (one /api/admetCSV call, F-6),
OCHEM modelId (F-7), and the DruMAP/ProTox web runs (F-14/F-15) — plus the standardization decision
(F-16), which is a choice, not a fetch. CardioTox net and BOILED-Egg are now resolved. Next step: turn §1 into
core/schemas.py and §2 into the aggregate.py files, honoring the F-1…F-17 flags — and remember
CToxPred2 = 0/1 vote + %-string, CardioTox = bare P(block) array, SMARTCyp 3.0 = Python/RDKit (no
openjdk; metabolism is JVM-free), and ADMET-AI must not feed VDss/half-life.
End of I/O contract specification. Specifications only — no code.