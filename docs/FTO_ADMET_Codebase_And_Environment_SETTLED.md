FTO-ADMET — Codebase & Environment Architecture (SETTLED)
Reconciled (2 Jul 2026): dependency manager DECIDED = pixi (§4); model roster synced to the
finalized set — DeepHIT + Spielvogel dropped, CardioDPi → ctoxpred2/, Java FAME 3 → fame3r/
(Python), ADMET-AI pinned v2, and SMARTCyp 3.0 corrected to Python/RDKit (no JVM). See the
skeleton's §9 for the roster rationale.
Status: FROZEN. Companion to FTO_ADMET_Pipeline_Skeleton_SETTLED.md. That file settles which
models and endpoints exist. This file settles how the code is laid out, how dependencies are
managed, how the machine is used, and how work moves to GitHub. Point new contexts at both.
What is settled here: file system, dependency-management tool, per-model isolation, the
registry/dispatch/aggregator contract, the Rosenbluth execution model, the dev topology (Claude
Code runs locally and drives the box over SSH — §8), the GPU discipline, storage placement, and the
git workflow. What is not settled: the exact function names and signatures inside core/
(deliberately left for the Claude Code sessions), and the remaining items flagged in §11.

1. Settled decisions at a glance
QuestionDecisionWhyLanguagePythonEntire cheminformatics/ADMET + ML stack is Python-native; non-Python models hide behind a uniform CLINotebooksExploration only — never the execution substrateHidden state + bad git diffs kill reproducibility; runs are scriptsDependency managerpixi (DECIDED)Built-in lockfiles = deterministic rebuilds; conda-compatible; project-local. Chosen over conda+conda-lock; decision closed (§4).IsolationOne environment per modelThese tools have mutually incompatible deps; isolation is mandatory, not stylisticRoot layoutendpoints/, core/, tests/ + pyproject.toml + README.md (+ config/ignore files)Everything nests inside the three folders; root stays unclutteredExecutionBare subprocess on the single box, driven remotely via ssh … 'command'No scheduler. Each SSH call is a fresh shell (compose stateful steps into one connection); long jobs run detached in tmux and are polled, not blocked onContainersNo (for now)Isolation problem here is dependency conflict, not multi-tenancy; envs solve it. Apptainer is a future option onlyDev methodClaude Code runs LOCALLY on the laptop; it drives Rosenbluth over ssh sanjanp@rosenbluth.ucsd.edu 'command'Nothing of yours is installed on the shared sanjanp account, so your Claude credentials never land on it (§8a). The box only ever sees sanjanp running shell commandsSource of truthgit (code) + committed lockfiles (envs), as a TWO-WAY bridgeCode flows laptop→repo→box; lockfiles are solved on the box and flow box→repo→laptop (they can't be solved on macOS)

2. The machine (Rosenbluth) — the constraints everything follows from
Confirmed live from the box:

Single 4-GPU host, bare SSH, no scheduler. No SLURM / k8s / any queue. You SSH in and run
python. Dispatch is therefore always a local subprocess on this one node — no job arrays,
no pods, no login-vs-compute split.
GPU claiming is manual and convention-based. nvidia-smi to find a free GPU (<15 MiB used =
free per the MOTD), export CUDA_VISIBLE_DEVICES=N to claim it. Nothing enforces the claim —
a long-lived tmux session is how people hold it across disconnects.
Storage:
MountTypeUse it forNotes$HOME (/home/sanjanp)local ext4almost nothing97% full, ~12G free, no quota tooling. Off-limits for project data./scratch/sanjanp/…local NVMeenvs, caches, model weightsFast, local. Subdir must be requested. Treat as disposable./zfs/sanjanp/…NFS (Gilson lab)git clone, run ledger, final outputs115T free, persistent, backed by real FS. Slower for many-small-files I/O.

Internet egress: direct, no proxy. PyPI / HuggingFace / GitHub all reachable. Installs and
git push work straight from the box.
CUDA: no working module system, no wired-in system CUDA. Bring-your-own-CUDA via the env —
e.g. torch==2.5.1+cu121 ships its own runtime and works against the 575.57.08 driver (already
proven in the existing gli conda env).

Placement rule that falls out of this: code + ledger + outputs-of-record → /zfs; installed
envs + package caches + weights → /scratch; nothing project-related in $HOME.

3. File system (complete)
Repo lives at /zfs/sanjanp/fto-admet/. Tracked root is three folders + two files (+ standard
config/ignore files). Everything else nests.
fto-admet/
├── endpoints/                      # one folder per endpoint; models nest inside
│   ├── triage/
│   │   ├── __init__.py
│   │   ├── aggregate.py            # endpoint aggregation logic
│   │   ├── admet_ai/
│   │   │   ├── pixi.toml           # this model's isolated env (intent)
│   │   │   ├── pixi.lock           # exact resolved env (committed)
│   │   │   ├── run.py              # standardized CLI adapter: --input --output [--gpu]
│   │   │   ├── vendor/             # upstream code, unmodified
│   │   │   └── README.md           # provenance: upstream commit, citation, quirks, access tag
│   │   ├── admetlab3/              # CODE-API: env is just an HTTP client; run.py calls REST
│   │   └── openadmet/
│   ├── herg/                       # PRIMARY GO/NO-GO GATE
│   │   ├── aggregate.py            # harmonize-then-weight-toward-sensitivity (NOT averaging)
│   │   ├── bayesherg/  cardiotox_net/  ctoxpred2/  cardiogenai/   # deephit dropped; ctoxpred2 replaces cardiodpi
│   ├── metabolism/
│   │   ├── aggregate.py            # generalist "is it stable" vs SoM "where"; agreement = confidence
│   │   ├── smartcyp/  fame3r/      # both Python: SMARTCyp 3.0 (RDKit) + FAME3R (pip/conda-forge); NO JVM
│   ├── clearance/
│   │   ├── aggregate.py            # DECOMPOSE renal vs hepatic; never one number
│   │   ├── watanabe_renal/         # WEB-ONLY → README SOP only, no run.py
│   │   ├── pksmart/                # CODE-PKG, emits fold-error
│   │   └── pbpk/                   # POINTER (OSP/PK-Sim); out of bulk loop; README + optional scripts
│   ├── distribution/
│   │   ├── aggregate.py            # passive scores are rough filters; real answer = experimental Kp,uu
│   │   ├── bbb_score/  boiled_egg/  cns_mpo/   # rule-based (see physchem note §5)
│   │   ├── pgp/                                 # narrow-domain ML (spielvogel dropped — dataset-only)
│   │   └── watanabe_pgp_brain/     # WEB-ONLY → README SOP only
│   ├── ppb/
│   │   ├── aggregate.py
│   │   └── ochem_ppb/              # CODE-API (REST); pin the public model ID in README
│   ├── solubility/
│   │   ├── aggregate.py            # SFI vs generalist discrepancy = the flag
│   │   └── sfi/                    # rule (cLogD + #aromatic rings)
│   ├── lipophilicity/
│   │   ├── aggregate.py            # spread across lenses = flag; anchor to measured logD ≈ 1
│   │   ├── rdkit_crippen/  opera/  swissadme/  # OPERA standalone; SwissADME WEB-SUBSTITUTABLE
│   ├── permeability/
│   │   └── aggregate.py            # NO own models — consumes triage generalists (Caco-2/HIA/%F) + BOILED-Egg
│   ├── structural_alerts/
│   │   ├── aggregate.py
│   │   └── pains_brenk/            # rule (RDKit)
│   ├── synthesizability/
│   │   ├── aggregate.py            # escalating rigor ladder = the confidence signal
│   │   ├── sascore/  rascore/  aizynthfinder/
│   ├── toxicity/
│   │   ├── aggregate.py
│   │   ├── toxicophores/           # rule (RDKit)
│   │   └── protox/                 # WEB-ONLY → README SOP; bulk substituted via triage generalists
│   └── druglikeness/
│       ├── aggregate.py
│       └── lipinski_veber_qed/     # rule (RDKit)
├── core/                           # your orchestration package (installed with `pip install -e .`)
│   ├── __init__.py
│   ├── config.py                   # reads .env → resolves /zfs, /scratch paths (collaborator-agnostic)
│   ├── models.py                   # ModelName + Endpoint StrEnums
│   ├── registry.py                 # ModelSpec (frozen dataclass) + REGISTRY dict
│   ├── schemas.py                  # pydantic input/output contracts (per model / per input-type)
│   ├── gpu.py                      # nvidia-smi query, device pick, soft lock files
│   ├── dispatch.py                 # run ONE model: validate → resolve env → gpu? → subprocess → collect → ledger
│   ├── run.py                      # run_endpoint(ep, input) = registry query → dispatch each → aggregate; + CLI
│   └── ledger.py                   # append-only run ledger (JSONL on /zfs; see §7)
├── tests/
│   ├── conftest.py                 # fixtures: FTO-43 SMILES, tmp dirs
│   ├── test_registry.py            # every ModelName has a spec; paths exist; endpoints valid
│   ├── test_schemas.py             # input-contract validation logic
│   ├── test_gpu.py                 # picker parses nvidia-smi, respects locks (mocked)
│   └── test_smoke.py               # @pytest.mark.model — per-model tiny-input run; opt-in, shells into each env
├── pyproject.toml                  # packages `core` AND doubles as the root pixi manifest (orchestrator env)
├── pixi.lock                       # orchestrator env lock (committed)
├── CLAUDE.md                       # persistent project context for Claude Code sessions
├── README.md                       # human onboarding: setup, paths, run commands
├── .gitignore                      # ignores .pixi/, __pycache__/, data/, .env, *.lock caches
└── .env.example                    # committed template; each collaborator copies to gitignored .env
Why two manifest types (deliberate, not inconsistent)

pyproject.toml appears where there is a package to build — i.e. only at root, for core.
It also carries [tool.pixi.*] tables so it doubles as the orchestrator environment manifest.
pixi.toml appears in each model folder, where the thing is purely an environment, not a
package. Rule of thumb: pyproject.toml = "this is code we ship"; pixi.toml = "this is just an
environment we run something in."

Every file, by job
FileJobendpoints/<ep>/<model>/pixi.tomlDeclares that model's isolated env (intent: channels + deps)endpoints/<ep>/<model>/pixi.lockThe exact resolved env. Committed — this is the reproducibility guaranteeendpoints/<ep>/<model>/run.pyUniform adapter. Same CLI for every model: reads --input, writes --output, optionally honors --gpu. Hides the upstream mess behind one interfaceendpoints/<ep>/<model>/vendor/Upstream research code, unmodified, so it can be re-pulled/re-verified independently of your wrapperendpoints/<ep>/<model>/README.mdProvenance: upstream repo + commit/version, citation, access tag, known quirks. Web-only models put their manual SOP hereendpoints/<ep>/aggregate.pyEndpoint-specific fusion of its models' outputs. Runs in the core env (operates on collected outputs, not on the models' conflicting deps)endpoints/<ep>/__init__.pyMakes the endpoint importable so core can load its aggregatorcore/config.pySingle place that resolves machine paths from .env; nothing hardcodes /zfs/sanjanpcore/models.pyModelName and Endpoint as StrEnum — the primary keys of the systemcore/registry.pyModelSpec + the REGISTRY dict. Curated, version-controlled, reviewable in PRscore/schemas.pypydantic contracts; validate input before a subprocess launchescore/gpu.pyThe scheduler Rosenbluth doesn't have: pick a free GPU, set CUDA_VISIBLE_DEVICES, hold a soft lockcore/dispatch.pyRuns exactly one model, generically. The only place that shells outcore/run.pyRuns an endpoint (enumerate → dispatch → aggregate) and hosts the CLIcore/ledger.pyRecords every run for provenance (§7)pyproject.tomlPackages core; also the orchestrator env manifestCLAUDE.mdTells Claude Code the conventions so it doesn't re-derive them each session.env.example → .envPer-person path config; keeps the repo collaborator-agnostic

4. Dependency manager — DECIDED: pixi
Decision: pixi. This is closed — no longer an open question. Rationale, tied to the lab's stated
#1 value (reproducibility):

A plain conda environment.yml specifies version ranges and re-resolves each install, so two
installs on different days can differ. That silently undercuts reproducibility.
pixi generates a pixi.lock automatically — the exact resolved graph — so a rebuild is
bit-for-bit deterministic. This is the property that makes "envs are disposable, lockfiles are the
source of truth" actually true (critical given /scratch may be purged).
pixi is not leaving the conda ecosystem — it pulls the same conda-forge / bioconda packages and
can import an upstream environment.yml as a starting point. It's a better front-end to the same
packages.
It is project-local (.pixi/), so it coexists cleanly with the lab's existing gli conda env
without touching it.

Status: closed. This was previously flagged for ratification with Gilson (the lab's existing
workflow is conda); that decision is now made in favor of pixi. The considered fallback,
conda + conda-lock, is retained only as a documented contingency: because pixi pulls the same
conda-forge/bioconda packages, every manifest in this repo maps 1:1 to environment.yml +
conda-lock.yml with no structural change if the lab ever mandates conda. The non-negotiable that
drove the choice holds either way — no plain conda without a lockfile.

5. Endpoint × model inventory (all of it, mapped to the tree)
Roles/access tags are from the skeleton. "Bulk loop?" = can it run in the automated pass over many
compounds (No = shortlist/manual only). Rule-based models are RDKit/formula and trivially
reproducible; each still gets its own (trivial) pixi.toml so folders stay self-contained and
dispatch stays uniform — the duplication is a few lines and buys self-containment.
EndpointModel (folder)RoleAccessBulk loop?GPU?triageadmet_ai (v2)BROAD (excl. VDss/t½ heads)CODE-PKGYesoptadmetlab3BROADCODE-APIYesnoopenadmetBROAD (reference)CODE-PKGYesoptherg (GATE)bayeshergUNCERT (Bayesian)CODE-PKGYesyescardiotox_netENSEMBLECODE-PKGYesyesdeephitDROPPED (no repo; redundant w/ cardiotox_net)———ctoxpred2SPECIFIC (secondary; replaces cardiodpi)CODE-PKGNooptcardiogenaiPOINTER (redesign; gated on binding + FTO-vs-ALKBH5)CODE-PKGNoyesmetabolismsmartcypSPECIFIC (SoM)CODE-PKG (Python 3 + RDKit; no JVM)Yesnofame3rSPECIFIC (SoM; Python replaces Java FAME 3)CODE-PKG (pip/conda-forge)Yesnoclearancewatanabe_renalSPECIFIC (renal)WEB-ONLYNonopksmartUNCERT (fold-error)CODE-PKGYesoptpbpkPOINTER (integrator)CODE (OSP; R 4.x + .NET 8 — isolate outside pixi)Nonodistributionbbb_scoreruleCODE-ALGOYesnoboiled_eggrule (also feeds permeability)CODE-ALGOYesnocns_mporuleCODE-ALGOYesnopgpSPECIFIC (narrow ML)CODEYesoptspielvogelDROPPED (dataset-only; no released model)———watanabe_pgp_brainSPECIFICWEB-ONLYNonoppbochem_ppbSPECIFICCODE-APIYesnosolubilitysfiruleCODE-ALGOYesnolipophilicityrdkit_crippenSPECIFIC (single)CODE-PKGYesnooperaSPECIFIC (ML + AD flag)CODE-STANDALONE (MATLAB MCR + Java; isolate)YesnoswissadmeUNCERT (5-way consensus)WEB-SUBSTITUTABLEcode recon / webnopermeability(no own models) — aggregate over triage generalists (Caco-2/HIA/%F) + BOILED-EggBROADvia generalistsYes—structural_alertspains_brenkruleCODE-PKGYesnosynthesizabilitysascoreSPECIFIC (triage)CODE-PKGYesnorascoreSPECIFIC (2nd opinion)CODE-PKGYesoptaizynthfinderSPECIFIC (route search)CODE-PKGshortlistopttoxicitytoxicophoresruleCODE-PKGYesnoprotoxSPECIFIC (domain)WEB-ONLY (bulk-substituted via triage)Nonodruglikenesslipinski_veber_qedPOINTER (context)CODE-PKGYesno
The former VERIFY items are now resolved: deephit is dropped (no primary repo; redundant with
cardiotox_net), and cardiodpi is replaced by ctoxpred2 (issararab/CToxPred2 — in-code,
same three channels, ships uncertainty). No hERG model remains in an unverified state.
Cross-cutting models (folder = home, but consumed by several endpoints). The generalists
admet_ai and admetlab3 physically live under triage/ but their output fields are consumed by
solubility (cross-check), permeability (Caco-2/HIA/%F), toxicity (bulk substitute), and as the
hERG/tox pre-screen. boiled_egg lives under distribution/ but also feeds permeability. This is
the one place the endpoint→model relation is a light graph, not a strict tree. Represent it with
ModelSpec.endpoints as a set; aggregators query the registry by endpoint rather than by folder.
Web-only models (watanabe_renal, watanabe_pgp_brain, protox) have no pixi.toml/run.py
— just a README.md with the manual SOP (URL, inputs, how to transcribe results into the ledger).
They are run by hand on the shortlist and never enter the bulk loop.

6. The registry / dispatch / aggregator contract
The single design that ties isolation, structure, and orchestration together. Because each model runs
in its own env, core cannot import them — it shells out.

ModelName(StrEnum) — one member per model; the primary key.
ModelSpec (frozen dataclass) per model: name, endpoints: frozenset[Endpoint],
env_manifest (path to its pixi.toml), entrypoint (path to its run.py), input_schema,
output_schema, requires_gpu: bool, in_bulk_loop: bool, provenance (upstream commit, citation).
REGISTRY: dict[ModelName, ModelSpec] — curated in code, reviewed in PRs.
dispatch.run_model(name, input, output_dir): look up spec → validate input against schema →
if requires_gpu, ask gpu.py for a device → shell out
(pixi run --manifest-path <env_manifest> python <entrypoint> --input … --output …) → collect
output → write a ledger record.
run.run_endpoint(endpoint, input): [s for s in REGISTRY.values() if endpoint in s.endpoints and s.in_bulk_loop] → dispatch each → hand collected outputs to that endpoint's aggregate.py.

dispatch and run_endpoint are generic and singular — they don't grow with the number of
endpoints. The only endpoint-specific code you write is the N aggregate.py files. Adding a model =
add a folder + one enum member + one registry entry. Adding an endpoint = add a folder + an aggregator.

7. GPU discipline & the run ledger (Rosenbluth-specific core code)
Because there's no scheduler, core does two jobs a scheduler would otherwise do:
core/gpu.py — parse nvidia-smi, pick a device under the free-memory threshold, set
CUDA_VISIBLE_DEVICES for the run. Query fresh at claim time (never cache "free" — a
144-day-idle tmux session currently holds GPU 0). Because each SSH call is a fresh shell, an
export CUDA_VISIBLE_DEVICES=N in one call is gone by the next — so (a) the pick and the job that
uses it must ride the same connection (ssh … 'export CUDA_VISIBLE_DEVICES=N && pixi run …' or a
persistent tmux session), and (b) the durable claim is the soft lock file on shared storage (e.g.
$FTO_ADMET_ROOT/.locks/gpu{N}.lock), checked alongside nvidia-smi, since the env var can't span
connections. Once you dispatch many models across 4 GPUs, your own concurrent runs are the main
collision risk. Models with requires_gpu=False (all rule-based, SMARTCyp/FAME, PKSmart, PPB, …)
never touch this path.
core/ledger.py — an append-only JSONL file on /zfs recording every run:
{model, input_hash, output_path, env_lock_hash, cuda_device, timestamp, status}. JSONL, not SQLite:
the ledger lives on NFS, and SQLite's file locking is unreliable over NFS — appends are safe. Load
into pandas/SQLite in-memory for querying. This is your reproducibility trail; keep it on persistent
/zfs, never on purgeable /scratch. Design decision (settled): the ledger record is written by
the job itself, on the box, at completion — not by the laptop-side driver. With no scheduler and
long jobs living in detached tmux, a dropped laptop connection must never lose the record; writing it
box-side makes the run self-documenting regardless of whether the laptop is still attached.

8. Environment management & the dev loop
8a. Dev topology — where Claude Code runs, and why (settled)
Claude Code runs on the laptop, never on Rosenbluth. It drives the box exactly the way you would
by hand: it runs ssh sanjanp@rosenbluth.ucsd.edu 'command' in its local shell, the command executes
on the box, output returns, the connection closes. Rosenbluth has no idea Claude is involved — it sees
sanjanp running shell commands over SSH, indistinguishable from an interactive login. No agent, no
binary, and no Claude credentials are ever deployed to the shared account (this is the fix for the
shared-sanjanp-login problem: your Claude login lives in your laptop's ~/.claude; the co-user of
the box cannot reach it and cannot burn your usage).
This means the install-and-fix loop can happen on the box: Claude runs ssh … 'pixi install',
reads the error, edits the local pixi.toml, pushes/scps it over, re-runs — the loop closes
remotely while the brain and credentials stay local. Two properties of this transport shape the
core design and must be respected:

Each ssh 'command' is a fresh login shell — no state carries between calls. A cd, an
export CUDA_VISIBLE_DEVICES=N, or a claimed GPU set in one call is gone in the next. Anything
stateful must be composed into a single connection (ssh … 'cd … && export … && pixi run …') or
held in a persistent tmux session the driver sends keystrokes into. (Drives the GPU rule in §7.)
Long jobs must be fire-and-poll, not fire-and-wait. A blocking ssh … 'hour_long_run' dies if
the laptop connection drops (no scheduler to catch it). Launch detached — ssh … 'tmux new -d -s <job> "…"' or nohup … & with a logfile — and poll for completion / tail the log. (Drives the
ledger rule in §7: the job writes its own completion record on the box.)

Auth: the laptop's default key (~/.ssh/id_ed25519) is already in Rosenbluth's authorized_keys
for sanjanp, so connections are silent. Add a Host rosenbluth alias to ~/.ssh/config with a
ControlMaster/ControlPersist block — it reuses one connection across calls (faster) and softens
the fresh-shell friction above.
8b. First-time setup
On the laptop: install Claude Code locally (native installer or npm). Clone the repo locally; this
is where the authoring loop runs.
On the box (via ssh, or Claude Code driving it):

Request a /scratch/sanjanp/ subdir from whoever administers the box.
Install pixi on the box (single-command install; egress is open).
Point pixi's solved-environment location and package cache at /scratch (pixi
detached-environments + PIXI_CACHE_DIR), and set HF_HOME / PIP_CACHE_DIR to /scratch
too, so nothing large lands in the 97%-full $HOME. (Verify exact pixi config keys against docs.)
git clone the repo into /zfs/sanjanp/fto-admet/.
cp .env.example .env; set FTO_ADMET_ROOT=/zfs/sanjanp/fto-admet and
FTO_ADMET_ENV_CACHE=/scratch/sanjanp/fto-admet-envs.
pixi install at root; pip install -e . to make core importable. Per-model pixi install
happens as you build each model — and the resulting pixi.lock is committed from the box
(§9), because macOS can't solve the box's Linux+CUDA envs.

8c. Daily loop
Author locally with Claude Code (edit core/, adapters, tests; run the fast test tier locally — it
needs no GPU) → commit/push → Claude drives the box over ssh … 'git pull && pixi install && …' for
the parts that must run there (env installs, per-model smoke tests, GPU runs). Long runs go into
detached tmux on the box and are polled. The credential-sensitive work never requires anything of
yours to live on the shared account.
Storage discipline (recap)
Code + ledger + final outputs → /zfs. Envs + caches + weights → /scratch (disposable; rebuilt
from committed lockfiles). Nothing project-related in $HOME.
Testing
Top-level tests/, pytest, test_*.py. Two tiers: fast unit tests (registry integrity, schema
validation) run in the core env on every change; per-model smoke tests (@pytest.mark.model)
shell into each model's env with a tiny fixed input and are opt-in (CI/nightly), not part of the
default run. conftest.py holds the canonical FTO-43 fixture.

9. Git / GitHub workflow (two-way bridge)
Git is the bridge between two clones: the laptop clone (where Claude Code authors) and the box
clone at /zfs/sanjanp/fto-admet/ (where things run). Two directions of flow:

Code: laptop → repo → box. Author locally, git push, then ssh … 'git pull' on the box.
Lockfiles: box → repo → laptop. pixi.lock for a model must be solved on the box (macOS
can't resolve Linux+CUDA wheels). Recommended path that keeps the shared account credential-minimal:
generate the lock on the box, scp it to the laptop, commit it there under your identity, push.
The box then only ever needs to pull, so it holds a read-only GitHub deploy key — no push
credential, and nothing as sensitive as a Claude login. (Simpler alternative if the scp step
grates: give the box a scoped write deploy key and commit lockfiles from the box — but then mind
the identity caveat below.)

Shared-account git identity: commits made on the box are attributed to whatever
user.name/user.email git is configured with there — easily the wrong person on a shared account.
Doing all commits from the laptop (the recommended lock-file path above) sidesteps this entirely; if
you do commit from the box, set the identity explicitly first.
.gitignore carries the reproducibility discipline: ignore .pixi/, __pycache__/, data/,
.env, installed envs, and caches. Commit pixi.toml / pixi.lock, run.py, README.md,
aggregators, and all of core/. Never commit envs, weights, data, or secrets.
Collaborator-agnostic: because paths come from .env (gitignored) via core/config.py, a labmate
clones, sets their own .env, pixi install, and runs — no path edits to the code.

10. Build order (unchanged from prior; restated for completeness)

Walking skeleton: core + one trivial CPU model (RDKit Crippen or SFI) end-to-end, including
ledger + one smoke test. Proves the contract, not an install.
First real isolated env: add one model that needs its own env and exercises the subprocess
adapter (e.g. PKSmart or BayeshERG). De-risks dispatch/env-resolution.
First full endpoint — hERG: all its models + aggregate.py (harmonize-then-weight). Hardest
endpoint first validates the aggregator abstraction and yields an early go/no-go read on FTO-43.
Go wide, one endpoint at a time. Sweep the rule-based cluster (solubility, druglikeness,
structural alerts, BBB/CNS scores) together since they share the trivial-env pattern.

Per-model reality: the real work is getting each upstream repo to install reproducibly in a pinned
env — treat that (not the adapter) as the unit of effort. The former unverified repos are resolved
(deephit dropped, cardiodpi → ctoxpred2); the remaining install-risk watchlist is the legacy
envs — BayeshERG (py3.6 + DGL, CC-BY-NC weights), CardioTox net (py3.7.7 + old TF), RAscore (2021
TF/sklearn) — plus the non-Python runtimes to isolate outside pixi: PBPK (R + .NET 8) and OPERA
(MATLAB MCR + Java). Health-check each before committing to it.

11. Open / to-ratify (not frozen)

pixi vs conda+conda-lock — RESOLVED (pixi). Ratified; see §4. The repo stays tool-agnostic
enough that conda+conda-lock remains a drop-in contingency, but pixi is the committed choice.
Exact core function names & signatures — deliberately deferred to the Claude Code sessions;
Aaran wants to be in on each.
/scratch subdir — must be requested; and glance at what is already consuming 76G of $HOME.
Own Rosenbluth account — resolved to OPTIONAL. The local-Claude-Code-over-SSH topology (§8a)
keeps your Claude credentials entirely off the shared sanjanp account, so a separate account is
no longer required to protect them. It remains a nice-to-have (clean git attribution, no
tmux/GPU collisions with your account-mate, a private ~/.claude if you ever do install Claude
Code on the box) but is not a blocker for any phase of the build.

Plus the validation/decision layer from the skeleton's §11 (applicability-domain rule, conformal
calibration, prospective validation, written decision policy) still sits on top and is still open.

End of settled codebase/environment architecture. Version this file alongside the skeleton; do not
let a new context silently re-derive it.