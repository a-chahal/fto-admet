# CLAUDE.md - FTO-ADMET build contract (auto-loaded; standing law for every session)

You are building the **FTO-ADMET / DMPK screening pipeline** (Gilson lab × Rana lab, pediatric CNS
tumor FTO-inhibitor program; lead **FTO-43**, PubChem CID 164886650). This file is the law. It is
loaded into every session automatically. Do **not** re-derive anything settled here. The full
rationale lives in `docs/` (four settled markdown files); this file is the operative summary plus the
things that will silently corrupt results if you get them wrong.

Each session builds **exactly one task** (`tasks/<id>.md`) to its done-criteria, then stops. You do
not plan the project, pick the next task, or touch other tasks. The orchestrator (`run.sh`) does
sequencing; you do one unit of work well.

---

## 0. Golden invariants (never violate)

1. **Lockfiles are solved ON THE BOX, never synthesized locally.** `pixi.lock` for any model must be
   produced by `pixi install` on Rosenbluth (Linux + CUDA). macOS/laptop cannot resolve Linux+CUDA
   wheels. Committing a hand-written, laptop-solved, or partial lockfile is a **fabrication** and a
   hard failure (see §5). If the box can't solve it, the task is **BLOCKED**, not done.
   *(This is about per-model envs. The one exception is the **root/core env** - no CUDA/model deps, so it
   is cross-platform and multi-platform-solved once; see `tasks/t00b-core-env.md`.)*
2. **Storage discipline.** Everything project-related lives under `/zfs/sanjanp/`: code + run ledger +
   final outputs in `/zfs/sanjanp/fto-admet/`, and envs + package caches + model weights in
   `/zfs/sanjanp/fto-admet-envs/` (the `FTO_ADMET_ENV_CACHE` path). **Nothing project-related in `$HOME`**
   (it is ~97% full). Before any install, confirm pixi's env dir + `PIXI_CACHE_DIR` + `HF_HOME` +
   `PIP_CACHE_DIR` all point under `/zfs`, and keep the pixi cache and the envs on the **same `/zfs`
   volume** so pixi's hardlinking works. (Set once in `t00-bootstrap-box`.)
3. **One environment per model.** These upstream tools have mutually incompatible deps. `core` cannot
   import them - it shells out. Isolation is mandatory.
4. **Dependency manager is pixi.** Decided and frozen. conda+conda-lock is only a documented fallback
   if the lab ever mandates it. No plain conda without a lockfile, ever.
5. **git is the two-way bridge.** Code flows laptop→repo→box (`git pull` on the box). Lockfiles are
   solved on the box and committed from the laptop identity (or via a scoped deploy key). Never commit
   envs, weights, data, caches, or secrets. `.gitignore` covers `.pixi/`, `__pycache__/`, `data/`,
   `.env`, `.harness/logs/`, caches.
6. **The ledger record is written by the job, on the box, at completion** - append-only JSONL on
   `/zfs`, never SQLite over NFS. A dropped laptop connection must never lose a run record.

---

## 1. Dev topology (how work reaches the box)

Claude Code runs **locally**; it drives Rosenbluth over `ssh rosenbluth '<cmd>'` (alias in
`~/.ssh/config` with `ControlMaster`/`ControlPersist`). Consequences you must respect:

- **Each `ssh '<cmd>'` is a fresh login shell.** A `cd`, an `export CUDA_VISIBLE_DEVICES=N`, or a
  claimed GPU does **not** carry to the next call. Compose stateful steps into one connection:
  `ssh rosenbluth 'cd $REPO && export CUDA_VISIBLE_DEVICES=N && pixi run …'`.
- **Long jobs are fire-and-poll, not fire-and-wait.** Launch detached in tmux
  (`ssh rosenbluth 'tmux new -d -s <job> "…; echo DONE > <job>.flag"'`) and poll for the flag / tail
  the log. A blocking hour-long `ssh` dies with the connection (no scheduler catches it).
- **GPU claiming is manual.** `nvidia-smi` (fresh, at claim time - a 144-day-idle tmux holds GPU 0),
  pick a device under the free-mem threshold, hold it with a **soft lock file** on shared storage
  (`$FTO_ADMET_ROOT/.locks/gpu{N}.lock`) since the env var can't span connections.

---

## 2. The contract you build against (registry / dispatch / aggregator)

- **`ModelName(StrEnum)`** - one member per model, the primary key.
- **`ModelSpec`** (frozen dataclass): `name`, `endpoints: frozenset[Endpoint]`, `env_manifest`
  (path to `pixi.toml`), `entrypoint` (path to `run.py`), `input_schema`, `output_schema`,
  `requires_gpu`, `in_bulk_loop`, provenance (upstream commit, citation).
- **`REGISTRY: dict[ModelName, ModelSpec]`** - curated, reviewed in PRs.
- **`dispatch.run_model(name, input, out)`** - validate input → resolve env → gpu? → shell out
  (`pixi run --manifest-path <env> python <entrypoint> --input … --output …`) → collect → ledger.
- **`run.run_endpoint(ep, input)`** - `[s for s in REGISTRY.values() if ep in s.endpoints and
  s.in_bulk_loop]` → dispatch each → hand collected outputs to that endpoint's `aggregate.py`.
- **Every model adapter is the same CLI:** `run.py --input <path> --output <path> [--gpu N]`. It hides
  the upstream mess behind one uniform interface. Upstream code lives unmodified in `vendor/`.
- **Cross-cutting models** (`admet_ai`, `admetlab3`, `boiled_egg`) live in one folder but their
  outputs feed several endpoints. Model→endpoint is a light **graph**: `ModelSpec.endpoints` is a
  **set**; aggregators query the registry by endpoint, never by folder.

---

## 3. Schema rule (build this in from day one - do not retrofit)

`core/schemas.py` must **reserve fields for uncertainty and applicability-domain (AD) from the
start**, even though the *operational AD rule and calibration are DEFERRED* (§6). Many models emit
native signals - OPERA `Conf_index`/`AD`/`AD_index`, PKSmart fold-error, BayeshERG `alea`/`epis`,
OpenADMET per-prediction σ, FAME3R `FAME3RScore`, ADMETlab high/low-confidence flag. If the output
schema has nowhere to put these, every adapter gets re-touched later. Reserve them now; leave the
*policy* that consumes them for later.

---

## 4. LANDMINES - decided facts that will silently corrupt results if re-derived

Treat each as an order, not a suggestion. These are the exact points where a plausible guess is wrong.

- **SMARTCyp 3.0 is Python 3 + RDKit - NO `openjdk`.** Only legacy 1.x/2.x were Java/CDK. The CSV
  header quoted in `docs/…_IO_SPEC.md §1 #8` is the **legacy-Java template** - **re-verify against a
  real SMARTCyp 3.0 run and do NOT hardcode it.** The whole metabolism endpoint is JVM-free.
- **ADMET-AI is pinned to v2** (Chemprop v2, retrained - predictions differ from the v1 paper/web
  server). **EXCLUDE the VDss (R²=-1.21) and half-life (R²=-2.39) heads entirely** (worse than the
  mean). Clearance heads are **low-weight/qualitative only**. Classification heads are strong (HIA,
  Pgp, CYP, BBB, hERG) and used normally.
- **CToxPred2 hERG output is a 0/1 int vote + a percent-STRING confidence** (`"{:.1%}"`, e.g.
  `"87.3%"` → strip `%`, ÷100). It joins the hERG gate as a **confidence-weighted vote**, NOT as a
  probability in the average. Same for Nav1.5/Cav1.2 (context).
- **CardioTox net returns a bare NumPy array of P(block)**, no named field - align **positionally** to
  the input list. Applicability limit: Morgan-fingerprint on-bits ≤ 93.
- **CardioGenAI discriminative keys contain a literal space**: `"hERG pIC50"`, `"NaV1.5 pIC50"`,
  `"CaV1.2 pIC50"`. Quote exactly. Non-blocker cutoff = pIC50 ≥ 5.0. Generative output is **GATED**:
  it must be filtered on Kunhuan's FTO-binding + FTO-vs-ALKBH5 selectivity before use (cross-arm
  contract does not exist yet → generative path is scaffold-only / POINTER).
- **NEVER combine the four clearance numbers numerically** - different units and matrices: PKSmart CL
  (mL/min/kg), ADMET-AI `Clearance_Hepatocyte_AZ` (µL/min/10⁶ cells), ADMET-AI `Clearance_Microsome_AZ`
  (µL/min/mg), OPERA `Clint` (µL/min/10⁶ cells), DruMAP CLint (µL/min/mg). Keep **renal / hepatic /
  aggregate decomposed**. The renal-vs-hepatic fork is resolved by experiment, not models.
- **Direction inversions (harmonize before ranking):** SFI **lower = better** vs generalist solubility
  higher = better; SMARTCyp `Score`/`Ranking` **lower = more likely SoM** vs FAME3R probability higher
  = more likely SoM → **co-rank atoms ordinally, never average the raw values.**
- **OCHEM PPB** outputs **% bound** and expects a **desalted neutral parent**. The numeric `modelId`
  for the REST call (`ochem.eu/article/29` = the Han 2025 consensus model) is a **live authenticated
  lookup** → `NEEDS_AARAN`. Build the adapter with a placeholder `modelId` constant + retry/backoff +
  response cache.
- **ADMETlab 3.0** transport is verified (`POST /api/admet`→`taskId`→`POST /api/admetCSV`; payload
  `{SMILES, feature, uncertain}`; wash `/api/washmol`; uncertainty = per-endpoint Youden high/low
  flag). The **literal 119 CSV column names require one live `/api/admetCSV` call** → `NEEDS_AARAN`.
  Build the adapter + placeholder schema; leave a TODO to capture the header.
- **DROPPED / REPLACED - never add to the funnel:** DeepHIT (dropped), Spielvogel (dropped),
  CardioDPi → **CToxPred2**, Java FAME 3 → **FAME3R** (Python).
- **BayeshERG trained weights are CC-BY-NC-4.0** (academic use only). Record in its README; any hERG
  hit found with them inherits the non-commercial restriction.
- **Non-Python heavy runtimes isolate OUTSIDE pixi:** PBPK (R 4.x + .NET 8 + OSP binaries), OPERA
  (MATLAB MCR + Java PaDEL/CDK). Driven out-of-band; results transcribed to the ledger like web tools.
- **BOILED-Egg is a point-in-polygon test in (x = TPSA, y = WLOGP) space** - white = HIA, yolk = BBB.
  Swapping the axes silently inverts the call.

## 4a. DEFERRED decisions - do NOT invent these; flag and stop at the boundary

- **F-16 input standardization** (the FTO di-cation: protonation/tautomer/stereo). Not yet decided.
  Feed each model a single canonical input from `core` (a documented placeholder standardizer) and
  **flag** where a model's expectation (e.g. OCHEM wants desalted neutral) diverges. Do not silently
  pick a protonation state per model.
- **F-13 single pKa source** (BBB Score / CNS MPO / SFI-cLogD all need one shared pKa). Undecided - 
  wire a single injectable pKa source with a placeholder (OPERA `pKa_pred`) and a clear TODO.
- **hERG gate math** (`herg/aggregate.py`): harmonize-then-weight-toward-sensitivity is a philosophy,
  not numbers. The thresholds/weights are **DEFERRED**. Build hERG *adapters*; the hERG aggregator is
  **scaffold-only + DEFERRED marker** (task `t52`), not real math.
- The wider validation/decision layer (operational AD rule, conformal calibration, prospective
  validation, written decision policy, null/ceiling benchmarks) sits on top and is **out of scope** for
  the build. Only the *schema hooks* (§3) and *raw-output caching* (§below) are built now.

**Raw-output caching is in scope now** (it's infra, not policy): every async/web adapter
(`admetlab3`, `ochem_ppb`, and the web SOPs' transcription) caches raw responses to `/zfs` so a result
is reconstructible after the upstream service silently changes.

---

## 5. Definition of DONE, the BLOCKED protocol, and the no-fabricate rule

At the end of a task you MUST write a machine-readable result file to
`.harness/results/<task-id>.json`:

```json
{ "task": "<id>", "kind": "<kind>", "status": "pass|blocked|needs_aaran",
  "attempts": <int>, "artifacts": ["<path>", …], "smoke": {"ran": true, "ok": true, "detail": "…"},
  "note": "<one line>", "commit": "<sha or branch>" }
```

**DONE (status=pass) by kind - the orchestrator's gate re-verifies these independently:**
- **core / aggregator / gate** - the declared pytest target passes in the core env
  (`pixi run pytest <target> -q`, exit 0). No box, no GPU.
- **model (code, incl. rule/legacy/heavy)** - `endpoints/<ep>/<m>/pixi.lock` exists, was **solved on
  the box** (contains a `linux-64` platform section with real package hashes - the gate checks this to
  catch fabrication), `run.py` honors the uniform CLI, the **smoke test passes on the box** against the
  FTO-43 fixture with output matching the declared `output_schema` (units + direction correct),
  `README.md` provenance is filled (upstream commit, citation, access tag, quirks, license).
- **sop (web-only)** - `README.md` exists and contains the required sections: `URL`, `INPUTS`,
  `SELECT` (e.g. "ALL models"), `OUTPUT FIELDS`, `LEDGER TRANSCRIPTION SHAPE`. No code, no smoke.
- **api-model** - HTTP client + retry/backoff + response cache + placeholder schema + mocked unit test
  pass, README carries the live-lookup TODO. Status = **`needs_aaran`** (the live header/modelId is the
  only remaining step), which the orchestrator files under NEEDS_AARAN, not DONE.

**BLOCKED protocol.** If a step cannot complete (env won't resolve on the box, upstream repo broken,
missing artifact), after **`ATTEMPT_CAP` (default 3)** honest attempts: set `status=blocked`, write the
**exact error** into `.harness/results/<id>.json` and the model `README.md`, then stop. Never loop.

**No-fabricate rule (hard).** Never write a lockfile the box did not solve. Never claim a smoke test
ran that did not. Never fill a schema field with a guessed unit/direction to make a check pass - if a
literal (a column name, a `modelId`, a header) is only knowable from a live run you cannot do, mark it
`needs_aaran` and leave the placeholder. A green check obtained by fabrication is the worst outcome in
this project; a clean BLOCKED is a good outcome.

**Permission-denial handling.** This runs headless (`claude -p`, `dontAsk` mode). If a tool call is
denied by policy or a safety classifier, treat it as a real boundary: find a safer path or mark the task
BLOCKED - do **not** retry the same denied action repeatedly. Repeated denials (≈3 consecutive) trigger
the kill-switch that terminates the session; a terminated session simply fails its gate and is retried
or BLOCKED by the orchestrator (never a fabricated pass), but hammering a denied action wastes an attempt.

**Scope rule.** Touch only files under your task's folder(s) + your `.harness/results/<id>.json`.
Do not edit `core` from a model task, other models, `MANIFEST.yaml`, or `STATE.json` (the orchestrator
owns state). Commit to branch `task/<id>`; open a PR if the workflow uses them.

**Commit rules (strict).**
- Commit with plain `git` commands only.
- Never add AI/Claude co-authorship. No `Co-Authored-By: Claude` trailer, no "Generated with Claude
  Code" line, no mention of Claude, Anthropic, or any AI anywhere in a commit message, PR, or code
  comment. Write commit messages as a human engineer would. (The repo also sets
  `includeCoAuthoredBy: false`, but do not rely on it alone.)

**Style rule (strict): never use em dashes.** Do not use the em dash character anywhere: not in code,
comments, commit messages, READMEs, markdown, docstrings, or any output. Use a hyphen, a colon, a comma,
or two separate sentences instead. This applies to en dashes and the unicode minus sign too: use a plain
ASCII hyphen (`-`) for ranges and negatives.

---

## 6. Where to read more (do not paste these wholesale - read the cited section)

- `docs/FTO_ADMET_Pipeline_Skeleton_SETTLED.md` - endpoints, roles, promotion logic.
- `docs/FTO_ADMET_Codebase_And_Environment_SETTLED.md` - file tree, pixi, topology, git bridge.
- `docs/FTO_ADMET_Model_Provenance_VERIFIED.md` - per-model repo health, deps, license, install path.
- `docs/FTO_ADMET_Model_IO_SPEC.md` - per-model I/O contract (§1), aggregator maps (§2), flags F-1…F-17 (§3).

Your task file (`tasks/<id>.md`) cites the exact sections you need. Read those, not the whole doc.
