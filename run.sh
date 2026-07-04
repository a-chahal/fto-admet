#!/usr/bin/env bash
# run.sh - autonomous build orchestrator for the FTO-ADMET pipeline.
#
# The loop: read STATE -> pick the next READY task (PENDING + all deps DONE) -> spawn a FRESH,
# memoryless `claude -p` session whose only context is CLAUDE.md + the rendered DRIVER.md for that
# task -> the session builds one task and writes .harness/results/<id>.json -> the deterministic gate
# (lib/gate.sh) independently verifies the artifacts -> STATE is updated -> repeat.
#
# Fresh session per task is the whole point: context never bloats, so output quality never degrades
# across the ~54-task build. Durable STATE.json makes the loop resumable - a crash, laptop sleep, or
# Ctrl-C just re-enters the loop where it left off. Blocked / human tasks are skipped, never retried
# forever, so one stuck legacy env can't stall the other 40 tasks.
#
# Usage:
# ./run.sh # run until no task is ready, then print the summary
# ./run.sh --once # run a single task and stop
# ./run.sh --max N # run at most N tasks this pass
# ./run.sh --include-human # also attempt human/NEEDS_AARAN tasks (for when Aaran is present)
# ./run.sh --dry-run # print what would run; change no state, spawn nothing
#
# Requires: python3, git, and the `claude` CLI on PATH. Box work happens INSIDE each session over ssh.
set -euo pipefail

HARNESS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${REPO:-$HARNESS}"
STATEPY="python3 $HARNESS/lib/state.py"
GATE="$HARNESS/lib/gate.sh"
DRIVER="$HARNESS/DRIVER.md"
LOGDIR="$HARNESS/.harness/logs"
RESDIR="$HARNESS/.harness/results"
ATTEMPT_CAP="${ATTEMPT_CAP:-3}"

# Claude Code flags for unattended runs. `acceptEdits` is WRONG here: it auto-accepts edits but still
# gates Bash, and headless `claude -p` has no UI to answer that prompt - the action is denied, and the
# auto-mode kill-switch terminates the process after 3 consecutive / 20 total denials. We use `dontAsk`
# (fail-loud: allowed tools run, the rest fail instead of prompting) with the allow/deny rules in
# .claude/settings.json (deny rules are absolute even in bypass). --max-turns caps runaway loops;
# stream-json gives a parseable event log for monitoring. If your plan supports it, `--permission-mode
# auto` (classifier-gated) is a safe alternative - set CLAUDE_FLAGS to use it.
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
MAX_TURNS="${MAX_TURNS:-80}"
CLAUDE_FLAGS="${CLAUDE_FLAGS:---permission-mode dontAsk --max-turns $MAX_TURNS --output-format stream-json}"

ONCE=0; MAX=0; INCLUDE_HUMAN=""; DRY=0; RAN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --once) ONCE=1;;
    --max) MAX="$2"; shift;;
    --include-human) INCLUDE_HUMAN="--include-human";;
    --dry-run) DRY=1;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac; shift
done

mkdir -p "$LOGDIR" "$RESDIR"
# ensure STATE.json exists and matches the manifest (idempotent; never clobbers existing status)
$STATEPY seed >/dev/null
# recover any task orphaned IN_PROGRESS by a previous crash/kill/sleep - this is what makes the loop
# genuinely resumable (a fresh `next` only serves PENDING, so a stuck IN_PROGRESS would stall the build)
$STATEPY reset-stale

echo "== FTO-ADMET orchestrator =="
$STATEPY validate

if [ $DRY -eq 1 ]; then
  echo ""
  echo "-- DRY RUN: build order from current state (no sessions spawned, no state changed) --"
  $STATEPY plan $INCLUDE_HUMAN
  exit 0
fi

while :; do
  TASK="$($STATEPY next $INCLUDE_HUMAN || true)"
  if [ -z "$TASK" ]; then
    echo "-- no ready task remaining --"
    break
  fi
  KIND="$($STATEPY field "$TASK" kind)"
  AUTONOMY="$($STATEPY field "$TASK" autonomy)"
  TASKFILE="tasks/$TASK.md"

  if [ ! -f "$REPO/$TASKFILE" ]; then
    echo "!! $TASK: spec file $TASKFILE not authored yet - marking BLOCKED (author the task file)."
    [ $DRY -eq 0 ] && $STATEPY set "$TASK" BLOCKED --note "spec file $TASKFILE missing"
    continue
  fi

  echo ""
  echo ">> $TASK [$KIND / $AUTONOMY]"

  ATTEMPT="$($STATEPY field "$TASK" attempts)"
  ATTEMPT=$((ATTEMPT + 1))
  LOG="$LOGDIR/$TASK.$ATTEMPT.log"
  $STATEPY set "$TASK" IN_PROGRESS --attempts-inc >/dev/null

  # render the per-session prompt from DRIVER.md
  PROMPT="$(sed -e "s|{{TASK_ID}}|$TASK|g" -e "s|{{TASK_FILE}}|$TASKFILE|g" "$DRIVER")"

  # spawn the fresh, memoryless worker. Its context = auto-loaded CLAUDE.md + this prompt + repo on disk.
  # Wrapped in `timeout` so a hung session (e.g. a stuck pixi solve) can't freeze the whole overnight run;
  # on timeout the gate sees no valid result and the task is retried/BLOCKED like any other failure.
  set +e
  ( cd "$REPO" && printf '%s\n' "$PROMPT" | timeout "${SESSION_TIMEOUT:-3600}" "$CLAUDE_BIN" -p $CLAUDE_FLAGS ) >"$LOG" 2>&1
  CLAUDE_RC=$?
  set -e
  [ "$CLAUDE_RC" = "124" ] && echo " !! session hit SESSION_TIMEOUT (${SESSION_TIMEOUT:-3600}s) - killed" >>"$LOG"
  echo " session exit=$CLAUDE_RC log=$LOG"

  # deterministic gate: independently verify artifacts (does not trust the session's word)
  set +e
  bash "$GATE" "$TASK" >>"$LOG" 2>&1
  GRC=$?
  set -e

  case $GRC in
    0) $STATEPY set "$TASK" DONE --note "gate pass" \
         --commit "$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo '')" >/dev/null
       echo " => DONE";;
    2) $STATEPY set "$TASK" NEEDS_AARAN --note "live/manual step remaining (see result.json)" >/dev/null
       echo " => NEEDS_AARAN";;
    *) if [ "$ATTEMPT" -ge "$ATTEMPT_CAP" ]; then
         $STATEPY set "$TASK" BLOCKED --note "gate failed x$ATTEMPT_CAP (see $LOG)" >/dev/null
         echo " => BLOCKED (attempt cap reached)"
       else
         $STATEPY set "$TASK" PENDING --note "gate failed; will retry (attempt $ATTEMPT/$ATTEMPT_CAP)" >/dev/null
         echo " => retry pending (attempt $ATTEMPT/$ATTEMPT_CAP)"
       fi;;
  esac

  RAN=$((RAN + 1))
  [ "$ONCE" -eq 1 ] && break
  [ "$MAX" -gt 0 ] && [ "$RAN" -ge "$MAX" ] && { echo "-- reached --max $MAX --"; break; }
done

echo ""
$STATEPY summary
