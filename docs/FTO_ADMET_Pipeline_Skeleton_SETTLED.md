FTO-43 ADMET / DMPK Screening Pipeline — Settled Architecture Skeleton
Status: FROZEN SKELETON. This is the canonical reference for the ADMET/DMPK computational
screening architecture on the GLI-NT / Rana-lab FTO-inhibitor program. It captures every endpoint,
every model, each model's purpose, its uncertainty role, and the final settled decision (code vs.
web, tier, promotion status).
Reconciled (2 Jul 2026) to the finalized model set. This edit merges the recon findings
(..._Provenance_VERIFIED, ..._Model_IO_SPEC) so all four project docs agree on the roster:
dropped DeepHIT (no primary repo; redundant with CardioTox net) and Spielvogel (dataset-only, no
released model); substituted CardioDPi → CToxPred2 (issararab/CToxPred2, in-code, same 3
channels) and Java FAME 3 → FAME3R (Python, PyPI/conda-forge); pinned ADMET-AI → v2 (retrained;
VDss/half-life heads unusable — excluded); corrected SMARTCyp 3.0 to Python 3 + RDKit (the
"SMARTCyp is Java" note in an earlier IO-spec pass was itself the error — it read the legacy
cdk/smartcyp Java line; primary sources confirm 3.0 is Python/RDKit, so metabolism is JVM-free).
Finalized roster = 30 entries (29 models + permeability aggregate-only).
Why this file exists. As the project grows, seeding a new Claude context with "reference the other
chats" pulls in bloated, redundant context. This file is the single source of truth for the skeleton.
Point new contexts here first. The endpoint set, tool assignments, role taxonomy, uncertainty design,
and specialist-promotion logic are settled and should not be silently re-derived. What is not frozen
is the validation/decision layer (see §11) — that is deliberately open.
Scope note: this file is the ADMET/DMPK arm only. Binding affinity / FTO-vs-ALKBH5 selectivity is a
separate arm (Kunhuan) and is out of scope here except where it gates an ADMET tool (CardioGenAI).

1. Project context (fixed facts)

Lead compound: FTO-43 (paper writes "FTO-43 N"; also TR-FTO-43 N, TRANA4; vendor "FTO-IN-8").
PubChem CID 164886650. Formula C₁₉H₂₃ClN₂O₂, MW 346.85. Oxetanyl-pyrrolidine series.
Structural driver: two basic nitrogen centers (pyrrolidine tertiary amine + secondary-amine
linker) → the textbook hERG pharmacophore, and the reason hERG is the primary gate.
Measured anchor: series logD ≈ 1 (low). Anchor lipophilicity-dependent predictions to this.
Primary in vivo liability: high clearance (≈89.6 mL/min/kg, near mouse hepatic blood flow →
possible blood-flow-limited/high-extraction) and short t½ (≈0.61 h). Clearance is the thing the
whole optimization exists to fix.
Indication: pediatric CNS tumor (GBM/medulloblastoma) → BBB penetration is desirable, not a
gate. Delivery may be intratumoral / osmotic-pump, which can make oral absorption partly moot.
Predecessor: FTO-04. Proposed analog series: Ring-A "T-series" FTO-09T–FTO-19T (add basic amines
→ would worsen hERG; flagged).


2. Governing design philosophy (settled)

Broad models classify, ensembles generalize, always carry an uncertainty flag (direct or indirect),
never let a single ML prediction jump the gun, confirm anything critical experimentally.
≥2 independent models per endpoint where possible; treat every output as a flag, not ground truth.
The real deliverable is relative within-series ranking (Δ between close analogs), not absolute
public-model values. Anchor to the few measured series values.
Applicability domain (AD) awareness: the oxetane chemotype is out-of-distribution for essentially
every public model. Predictions are triage until confirmed.
Endpoints that are true go/no-go gates get extra rigor; everything else is triage.


3. Role taxonomy (the 5 model roles)
TagRoleBROADBroad/generalist multi-endpoint ML baselineENSEMBLEMultiple representations fused for generalizabilityUNCERTEmits or implies a confidence signalSPECIFICRule-based, mechanistic, or dedicated single-endpoint modelPOINTERConditional/optional tool, not in the main funnel

4. Uncertainty design (settled — the "baked-in" feature)
Every endpoint carries a confidence signal, one of two ways:

DIRECT (model emits its own): BayeshERG (Bayesian), PKSmart (fold-error/GMFE, widens out-of-domain),
OPERA (applicability-domain check).
INDIRECT (cross-model spread = confidence flag): hERG ensemble agreement, SwissADME consensus-of-5
divergence, RDKit/OPERA/SwissADME logP spread, metabolism (generalist stability vs SoM site-finding
agreement), solubility (SFI vs generalist discrepancy).

Unifying rule: convergence = trust; scatter = flag and lean on the measured value.

5. Specialist-promotion rule (settled) + outcomes
An endpoint earns a dedicated single-endpoint specialist only if all three hold:

It is decision-critical (a gate, not a triage flag).
A dedicated model materially beats the generalist (usually needs real endpoint-specific data +
exploitable structure).
The specialist gives something the generalist structurally cannot (mechanism, calibrated uncertainty,
interpretability).

Outcomes (strict test):

PROMOTED: hERG (all three pass) → the ensemble gate.
RETAINED on sole-provider grounds: Site-of-metabolism (SMARTCyp/FAME) — fails "gate" but is the only
tool that answers where; justified separately.
CONDITIONAL (unlocks only with series data): Hepatic metabolic stability / CLint — passes (1) and (3);
(2) is PARTIAL and upgrades to PASS given a handful of measured microsomal/hepatocyte points on the series.
This is the one specialist the project would be justified in building, and only after that data exists.
Everything else: generalist-tier / rule / not promotable (see §10). The slogan "specialist everywhere"
promotes zero new endpoints today.


6. Access / automatability legend (settled)
TagMeaningCODE-PKGPython/conda package — drop-inCODE-APIDocumented REST APICODE-STANDALONEDownloadable CLI / Java / standalone binary; runs on the clusterCODE-ALGOPure formula/rule — reimplement, no service neededWEB-ONLYOnly public access is a human using a websiteWEB-SUBSTITUTABLEWebsite-only, but its function is reproducible in codeVERIFYAccess method unconfirmed; check repo before committing
Pipeline goal is full automation over large compound sets → WEB-ONLY tools cannot sit in the bulk loop;
they run manually on the shortlist only.

7. ENDPOINT × MODEL INVENTORY (settled — every model)
Phase 1 — General ADMET triage (funnel entry; flags only, no kills here)
ModelPurposeRoleUncertaintyAccess / decisionADMET-AIBroad multi-endpoint baseline. Pinned to v2 (Chemprop v2, retrained — predictions differ from the v1 paper/web server; no RDKit-fingerprint features); percentile-vs-approved-drugs context. Exclude VDss (R²=−1.21) + half-life (R²=−2.39) heads — worse than the mean; clearance heads low-weight only. Strong on classification heads (HIA/Pgp/CYP/BBB/hERG)BROADINDIRECTCODE-PKG — bulk triageADMETlab 3.0Broad multi-endpoint (multi-task DMPNN + descriptors; 119 endpoints); built-in uncertainty; has organ-tox heads (nephro, neuro, oto, hemato, genotox, cyto A549/HEK293, immuno RPMI-8226, hERG)BROADDIRECT (built-in) + INDIRECTCODE-API — bulk triage; also ProTox tox-substitute sourceOpenADMETNewest open generalist; strongest current data on metabolism/CYP (CYP2J2/3A4 inhibition + reaction phenotyping)BROADINDIRECTCODE-PKG (HF/GitHub) — reference, esp. CYP; early-stage (cluster-split R²≈0.1) → reference not authority
Note: generalists contain internal hERG/tox heads → they are the cheap pre-screen that feeds the dedicated
gates, not a parallel system.
hERG / cardiotoxicity — PRIMARY GO/NO-GO GATE (PROMOTED specialist)
ModelPurposeRoleUncertaintyAccess / decisionBayeshERGGraph NN; blocker probability + Bayesian uncertainty; adjudicates split casesUNCERTDIRECTCODE-PKG (GitHub)CardioTox netMeta-feature ensemble (fuses low/high/intermediate features); robust across metricsENSEMBLEINDIRECTCODE-PKG (GitHub: Abdulk084/CardioTox)DeepHITDROPPED — no primary code repo (web-server-only historically); redundant with CardioTox net, which fills the same sensitivity-tuned-ensemble role with a clean pip package——REMOVED from funnelCToxPred2Explainable multichannel (hERG, Nav1.5, Cav1.2) in-code; DNN (MC-dropout uncertainty) or RF; secondary tier. Replaces CardioDPi (which was web-only/repo-unconfirmed)SPECIFICDIRECT (MC-dropout / ensemble)CODE-PKG (issararab/CToxPred2) — automatable secondary. hERG channel = 0/1 vote weighted by confidence, not a P(block)CardioGenAIGenerative redesign to lower hERG while keeping similarityPOINTER—CODE-PKG (GitHub). GATED: its output must be filtered on FTO binding + FTO-vs-ALKBH5 selectivity (it cannot see binding)
Aggregation (settled): harmonize-then-weight-toward-sensitivity, NOT plain averaging. Harmonize all to a
common probability + decision threshold. Unanimous "safe" → pass. Unanimous "blocker" → fail (or redesign via
CardioGenAI if it's a valuable, selective hit). Split → adjudicate with BayeshERG's uncertainty + CToxPred2's
multichannel read (high-uncertainty disagreement = "measure it, don't trust the model"). CToxPred2 sits
alongside as the secondary multichannel check, not in the core average.
Metabolism — site of metabolism (RETAINED, sole-provider)
ModelPurposeRoleUncertaintyAccess / decisionSMARTCyp 3.0Ranks which atom a CYP will attack (soft spot); rule-based precomputed reactivity, no trainingSPECIFICINDIRECTCODE-PKG (Python 3 + RDKit — not Java; v3.0 was rewritten from the legacy Java/CDK line. No JVM)FAME3RSite of metabolism, broader (phase 1 & 2); random-forest atom classifier. Python re-design of FAME 3 (replaces the Java FAME 3 + its non-commercial license)SPECIFICINDIRECTCODE-PKG (pip install fame3r / conda-forge; MIT)(generalists)Whole-molecule metabolic-stability / CYP-inhibition numberBROAD—via ADMET-AI / ADMETlab
Two questions, not three votes: generalists answer is it stable; SMARTCyp/FAME answer where the soft
spot is (action: block this atom). Confidence = agreement between the generalist stability number and the
site finding; disagreement = flag.
Clearance — weakest endpoint; DECOMPOSED, never a single number
ModelPurposeRoleUncertaintyAccess / decisionWatanabe fe/CLr (via DruMAP)Renal route: fraction excreted unchanged (fe binary classifier, bal. acc 0.74) + renal clearance CLr (two-step: excretion-type classifier → per-type regression), fu,p as descriptorSPECIFIC—WEB-ONLY (STAYS ONLINE). DruMAP web app, no API/download. Run manually on the shortlist. Rebuild judged not worth it (modest model, shortlist-only volume, fork is resolved experimentally). Optional: a lightweight in-house fe classifier only if in-code renal is ever required(hepatic = metabolism)Hepatic route has no separate model — covered by SMARTCyp/FAME + generalist stability——CODE (via §Metabolism). This is the CLint conditional-specialist candidatePKSmartHuman PK params (CL, t½) from structure with fold-error; two-stage RF (animal→human). Weak on CL (R²=0.31, GMFE 2.43) → coarse binning + relative ranking onlyUNCERTDIRECT (fold-error)CODE-PKG (GitHub)PBPKWhole-body mechanistic concentration-time simulation; an integrator, not a trained specialistPOINTER—CODE (open scriptable engines, e.g. OSP/PK-Sim)
Renal-vs-hepatic fork is resolved by experiment, not models → needs measured fe or microsomal/hepatocyte
stability (the standing data ask, §12). Do not treat clearance as one predicted number.
Distribution / BBB / CNS ("predict passive, flag efflux, measure the rest")
ModelPurposeRoleUncertaintyAccess / decisionBBB ScorePassive brain-entry rule over computed propertiesSPECIFIC (rule)—CODE-ALGOBOILED-EggPassive BBB + gut absorption; fixed WLOGP-vs-TPSA geometric rule (algorithmic, not ML)SPECIFIC (rule)—CODE-ALGO (or SwissADME web). Shared with PermeabilityCNS MPOCNS multiparameter optimization; formula over 6 physchem paramsSPECIFIC (rule)—CODE-ALGOP-gpEfflux-substrate flag; ML on small transport data, narrow domainSPECIFIC (narrow)—CODE (generalists / TDC Pgp)Spielvogel efflux/BBBDROPPED — dataset-only (OSF), no released model/repo; feature-gen needs commercial tools + per-molecule QM 3D-PSA; efflux-class AUC only 0.57, and its top feature is BBB Score (#14, already in). Signal largely captured by BBB Score + a PSA term——REMOVED (keep OSF dataset as a benchmark only)Watanabe P-gp brain-efflux (DruMAP)Brain-capillary P-gp efflux potentialSPECIFIC—WEB-ONLY (DruMAP), shortlist/manual
Posture: passive scores are a rough filter only, not brain-exposure prediction. Transport models usable
only inside their narrow training domain. Active cation influx at the human BBB is essentially
unpredictable → real answer is experimental Kp,uu. BBB is desirable (CNS indication), not a gate.
Standing lab questions: (a) is the passive-score approach safe to rely on at all; (b) is BBB transport for
this chemotype characterized enough to model.
Plasma protein binding (fraction unbound / bound)
ModelPurposeRoleUncertaintyAccess / decisionOCHEM PPBFraction bound; ML consensus; strong, respected public modelSPECIFIC—CODE-API (STAYS). REST: ochem.eu/modelservice/postModel → getPrediction (async, batch via $$$$), or rest.ochem.eu/predict; on-prem OCHEM Lite/Flex option. Correction: not web-only; no need to replace. To-do: pin the public model ID
Not a gate (modulator). Single tool is acceptable here.
Solubility
ModelPurposeRoleUncertaintyAccess / decisionSFI (Solubility Forecast Index)Solubility heuristic (lower = better) = cLogD + #aromatic ringsSPECIFIC (rule)INDIRECTCODE-ALGO — primary(generalists)Cross-check for major discrepancyBROAD—ADMET-AI / ADMETlab
Uncertainty = SFI-vs-generalist discrepancy. Likely a strength of the low-aromatic oxetane series.
Lipophilicity (logP / logD) — anchor to measured series logD ≈ 1 first
ModelPurposeRoleUncertaintyAccess / decisionRDKit CrippenFast single-algorithm logPSPECIFIC (single)—CODE-PKG (RDKit)OPERAlogP/logD with applicability-domain check (flags out-of-range)SPECIFIC (ML+AD)DIRECT (AD)CODE-STANDALONE (open-source)SwissADMEConsensus of 5 methods (iLOGP, XLOGP3, WLOGP, MLOGP, SILICOS-IT); spread = flagUNCERTINDIRECTWEB-SUBSTITUTABLE. No API. Reconstruct in code (lose iLOGP + SILICOS-IT, which are SwissADME-proprietary), or use web for the exact 5-way consensus
Uncertainty = spread across the three lenses. Convergence = trust; scatter = flag → lean on measured logD.
Permeability / absorption (keep lean; may be partly moot if delivery is intratumoral)
ModelPurposeRoleUncertaintyAccess / decisionBOILED-EggPassive membrane crossing; fixed WLOGP-vs-TPSA ruleSPECIFIC (rule)—CODE-ALGO (or SwissADME web)Caco-2 / HIAGut-wall uptake; via generalists (dedicated TDC Caco-2/PAMPA/HIA add little)BROAD—CODE (generalists)%F (oral bioavailability)Fraction of oral dose reaching blood; folds in first-pass; weak — treat with suspicionBROAD—CODE (generalists)
Structural alerts / liabilities
ModelPurposeRoleUncertaintyAccess / decisionPAINS / BRENKFlag assay-interfering / reactive groups; soft filter (look-closer, not auto-kill); over-flags. Matters here because the FTO assay is fluorescence-basedSPECIFIC (rule)—CODE-PKG (RDKit)
Synthesizability (tiered: triage → second opinion → real route)
ModelPurposeRoleUncertaintyAccess / decisionSAscoreQuick ease-to-make heuristic (fragment commonness + complexity)SPECIFIC—CODE-PKG (RDKit contrib) — triageRAscoreCan a route be found; classifier trained on a retrosynthesis plannerSPECIFIC—CODE-PKG (GitHub) — second opinionAiZynthFinderActual retrosynthesis route searchSPECIFIC—CODE-PKG (GitHub) — shortlist route-finding
Escalating rigor ladder = the confidence signal. Series almost certainly makeable (cousins of a made lead).
Toxicity
ModelPurposeRoleUncertaintyAccess / decisionStructural alerts (toxicophores)Known toxic substructures; rules for the rule-shapedSPECIFIC (rule)—CODE-PKG (RDKit)ProTox 3.061 endpoints: acute LD50 + class; organ (hepato/neuro/resp/cardio/nephro); mutagenicity, carcinogenicity, cytotoxicity, immunotoxicity, BBB, ecotox, clinical, nutritional; 12 Tox21 pathways; 15 toxicity targets; 14 MIE targets; 6 metabolism targets. Similarity + fragment + ML hybridSPECIFIC (domain)—WEB-ONLY. tox.charite.de, no API/package. Decision: TIERED — see below(bulk substitute)Automatable tox for the bulk passBROAD—CODE — ADMET-AI (LD50, DILI/hepatotox, hERG, AMES, Carcinogens, ClinTox, Skin) + ADMETlab API (nephro, neuro, cyto, immuno, genotox)
ProTox tiering (settled): run the ADMET-AI + ADMETlab-API tox panel for the bulk automated pass; run
ProTox by hand on the shortlist as the richer confirmatory read (its LD50-in-mg/kg depth, organ panel, and
AOP/MIE/off-target mechanistic layer + regulatory standing). This is a coverage/throughput substitute, NOT a
quality-equivalence claim. Endpoints with no automatable counterpart (lost in the bulk pass): respiratory
toxicity, ecotoxicity, nutritional toxicity, the 15 toxicity off-targets, the 14 MIE targets, and most of the
6 metabolism-target panel. Tox21's 12 pathways are available via TDC multi-task models (extra wiring) if needed.
Tox not promoted to specialist: Ames is gate-like but generalists already model it well; organ/carcinogenicity
data too thin. Stays generalist-tier + alerts + ProTox-web-on-shortlist.
Drug-likeness (context, not gates — run by the lab)
ModelPurposeRoleUncertaintyAccess / decisionLipinski / Veber / QEDOral drug-likeness sanity checks; fixed property thresholdsPOINTER—CODE-PKG (RDKit)

8. Access-decision summary (the "online vs code" bottom line)
CategoryToolsWEB-ONLY — run manually on shortlistWatanabe renal fe/CLr (DruMAP), Watanabe P-gp brain-efflux (DruMAP), ProTox 3.0 (bulk substituted, web on shortlist)WEB-SUBSTITUTABLE — reconstruct in codeSwissADME (lose iLOGP + SILICOS-IT)CODE-APIADMETlab 3.0, OCHEM PPBCODE-PKG / STANDALONE / ALGOADMET-AI (v2), OpenADMET, BayeshERG, CardioTox net, CToxPred2, CardioGenAI, SMARTCyp 3.0 (Python/RDKit), FAME3R, PKSmart, PBPK (OSP), P-gp, BBB Score, BOILED-Egg, CNS MPO, SFI, RDKit Crippen, OPERA, Caco-2/HIA (generalists), %F (generalists), PAINS/BRENK, SAscore, RAscore, AiZynthFinder, ProTox bulk substitute, Lipinski/Veber/QEDVERIFY items — RESOLVEDDeepHIT → dropped (no repo; redundant with CardioTox net); CardioDPi → replaced by CToxPred2 (in-code, same 3 channels). Nothing left in this rowNon-Python heavy runtimes (isolate outside pixi/conda)PBPK/OSP (R 4.x + .NET 8 + OSP binaries), OPERA (MATLAB MCR + Java PaDEL/CDK) — driven out-of-band, results transcribed to the ledger like web-only tools
Only genuine automation blockers: Watanabe-renal and ProTox — and both are handled by shortlist/manual +
substitution, not by forcing them into the bulk loop.

9. Corrections locked in (do not re-litigate)

OCHEM PPB has a REST API → stays in-code; earlier "drop it" was wrong.
SwissADME is web-only but its role is reconstructible in code (minus 2 proprietary logP methods).
ProTox stays web for shortlist; bulk is substituted, not replaced-as-equivalent.
Watanabe renal stays online (DruMAP); rebuild is not worth it at current scope.
CardioGenAI output must be gated on FTO binding + ALKBH5 selectivity.
SMARTCyp 3.0 is Python 3 + RDKit, NOT Java. Only 1.x/2.x were Java+CDK; the cdk/smartcyp repo
is that legacy line — do not use it for 3.0, and do not put a JVM in the metabolism env. (A later
IO-spec pass briefly "corrected" this to Java by reading cdk/smartcyp; that was the error.
Primary sources: SMARTCyp 3.0 applications note + the KU group page.)
DeepHIT dropped; Spielvogel dropped; CardioDPi → CToxPred2; FAME 3 (Java) → FAME3R (Python).
Roster is final at 30 entries. Do not re-add the dropped tools to the funnel.
ADMET-AI pinned to v2 (retrained; predictions differ from the v1 paper/web server). Its
VDss and half-life heads are unusable (R² < 0) — exclude them; clearance heads are low-weight.


10. Endpoints that stay generalist-tier (and why — from the strict promotion test)
PPB, solubility, lipophilicity, permeability/%F, BBB/transport → not gates (modulators or anchored to
measured/experimental values). Renal, aggregate PK (PKSmart/PBPK), thin-data tox (DILI, carcinogenicity, Ames)
→ no material specialist beat available (data too thin / endpoint intrinsically hard / multi-task beats
single-task). SFI, CNS MPO, BBB Score, BOILED-Egg, PAINS/BRENK, Lipinski/Veber/QED → deterministic, not
promotable (nothing to specialize).

11. NOT SETTLED — open validation/decision layer (deliberately not frozen)
The skeleton above is frozen. The following sit on top of it and are still open; do not treat them as
decided:

Operational applicability-domain rule — a per-compound/per-endpoint in-domain/out-of-domain test that
fires before a prediction is trusted, plus a policy for OUT (defer/flag/abstain). Critical because the
oxetane chemotype is OOD for every model.
Calibration with coverage guarantees — wrap the trainable endpoints in conformal prediction so the
uncertainty numbers mean what they say, including OOD.
Prospective validation — predict T-series analogs, have Rana measure a handful, report hit rate. Even
5–10 points beats any retrospective benchmark for trust.
Written decision policy — the uniform rule converting (prediction + uncertainty + AD status) into an
action (advance / kill / measure / redesign), per endpoint.
Null + ceiling benchmarks — beat a trivial baseline (rank by logD/MW) and, if available, a commercial
ceiling (ADMET Predictor / QikProp).
Reproducibility/versioning — pin model IDs, versions, dates; cache raw web-tool outputs (they change
silently).


12. Standing data ask (highest leverage)
Any measured ADMET on the series — even a handful of hERG (patch-clamp), microsomal/hepatocyte stability
(CLint), or logD points — unlocks: (a) anchoring/calibration of the public models, (b) trustworthy
within-series ranking, and (c) the CLint conditional specialist. Microsomal/hepatocyte stability is the single
most valuable request, since CLint is both the weakest endpoint and the actual in vivo liability.

End of settled skeleton. Update deliberately and version this file; do not let a new context silently
re-derive the architecture.