# t00-bootstrap-box - one-time box + laptop setup (self-serve)

**Kind:** bootstrap · **Autonomy:** human (quick one-time setup; run before `./run.sh`) · **Runs:** laptop + box
**Touch only:** `.env`, `.env.example`, box/laptop configuration (no pipeline code)
**Deps:** none - this is the root of the DAG

## What this is
A short, self-serve setup. There is **no admin gate**: everything project-related (code, ledger,
outputs, envs, caches, weights) lives under `/zfs/sanjanp/`, which your account already owns, so no
`/scratch` request and no root access are needed. The ssh alias `rosenbluth` is already configured.
`$HOME` stays off-limits for project data (it is ~97% full), which is the only reason the cache/env
paths are pinned to `/zfs`.

## Read first
- `docs/FTO_ADMET_Codebase_And_Environment_SETTLED.md` §2 (storage), §8b (first-time setup).
- `CLAUDE.md` §0.2 (storage discipline), §1 (dev topology).

## Checklist (record outcomes in `.result.json` note)
1. **Install pixi on the laptop and the box** (single-command install; egress is open). The laptop needs
   it for the root/core env + `run.sh`; the box needs it for the per-model envs.
2. **Make the `/zfs` layout** (self-serve, no admin):
   `mkdir -p /zfs/sanjanp/fto-admet-envs /zfs/sanjanp/pixi-cache /zfs/sanjanp/hf /zfs/sanjanp/pip-cache`.
3. **Point pixi + caches at `/zfs`** so nothing large hits `$HOME`, and so the cache and envs share one
   volume (needed for pixi's hardlinking):
   - pixi `detached-environments` -> `/zfs/sanjanp/fto-admet-envs`, `PIXI_CACHE_DIR` -> `/zfs/sanjanp/pixi-cache`,
     `HF_HOME` -> `/zfs/sanjanp/hf`, `PIP_CACHE_DIR` -> `/zfs/sanjanp/pip-cache` (set on both laptop and box).
   - **Verify the exact pixi config keys against current pixi docs** (they drift), then confirm with a
     throwaway `pixi install` that the env + cache dirs materialize under `/zfs`, not `$HOME`
     (`du -sh ~` before/after must not grow).
4. **Clone the repo on the box** into `/zfs/sanjanp/fto-admet/` (the box pulls via git; lockfiles are
   committed from the laptop identity - `CLAUDE.md` §0.5). The ssh alias `rosenbluth` is already set up.
5. **`.env`**: `cp .env.example .env` and set `FTO_ADMET_ROOT=/zfs/sanjanp/fto-admet` and
   `FTO_ADMET_ENV_CACHE=/zfs/sanjanp/fto-admet-envs`. (If `.env.example` does not exist until t01 authors
   it, create a minimal `.env` with these two vars now.)
6. **Sanity:** `ssh rosenbluth nvidia-smi` works; `/zfs/sanjanp` is writable; the box clone is present.

## Notes / caveats
- `/zfs` must have room for envs + weights (these can reach tens of GB across the 30 models). Check free
  space (`df -h /zfs`) before the wide build; if tight, prune old pixi caches between phases.
- If `/zfs` is NFS-mounted, pixi envs work but can be slower and occasionally finicky with file locking or
  symlinks. Keeping the pixi cache and envs on the same `/zfs` volume (step 3) avoids the hardlink issue.

## Done (gate: bootstrap kind)
- `.result.json` records: pixi installed + redirected to `/zfs` on laptop and box (with a before/after
  `$HOME` size showing no growth), `/zfs` layout created, repo cloned on the box, `.env` set. Status `pass`.

## Blocked if
- Not expected. If `/zfs` is unexpectedly not writable by your account, set status `needs_aaran` with the
  exact permission error (the only scenario that would need someone with storage control).
