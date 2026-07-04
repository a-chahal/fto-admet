#!/usr/bin/env bash
# gate.sh - deterministic done-check for one task. Exit 0 = pass, 1 = fail, 2 = needs_aaran.
#
# The gate does NOT trust the worker's self-report. It re-verifies the concrete artifacts the worker
# claims to have produced. This is the anti-fabrication layer from CLAUDE.md §5: a green result is only
# accepted if the artifacts that would prove it actually exist and are real.
#
# Usage: gate.sh <task-id>
# Env: REPO (default: harness dir's parent = repo root), ROSENBLUTH (ssh alias, default "rosenbluth"),
# GATE_RERUN_SMOKE=1 to re-run model smoke tests on the box instead of trusting result.json's
# smoke block (slower, maximally strict).
set -euo pipefail

HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="${REPO:-$HARNESS_DIR}"
ROSENBLUTH="${ROSENBLUTH:-rosenbluth}"
STATEPY="python3 $HARNESS_DIR/lib/state.py"

TASK="${1:?usage: gate.sh <task-id>}"
RESULT="$HARNESS_DIR/.harness/results/$TASK.json"
KIND="$($STATEPY field "$TASK" kind)"

fail() { echo "GATE FAIL [$TASK]: $*" >&2; exit 1; }
ok() { echo "GATE PASS [$TASK]: ${1:-ok}"; exit 0; }
needs(){ echo "GATE NEEDS_AARAN [$TASK]: ${1:-live step remaining}"; exit 2; }

# ---- 0. result file must exist, parse, and not self-report a failure ----------------------------
[ -f "$RESULT" ] || fail "no result file at $RESULT (worker did not finish)"
python3 -c "import json,sys; json.load(open('$RESULT'))" 2>/dev/null || fail "result file is not valid JSON"
STATUS="$(python3 -c "import json;print(json.load(open('$RESULT')).get('status',''))")"
[ "$STATUS" = "blocked" ] && fail "worker self-reported blocked: $(python3 -c "import json;print(json.load(open('$RESULT')).get('note',''))")"

# ---- helper: assert a file exists and is non-trivial --------------------------------------------
assert_file() { [ -f "$REPO/$1" ] || fail "missing artifact: $1"; [ -s "$REPO/$1" ] || fail "empty artifact: $1"; }

# ---- helper: a pixi.lock must be BOX-SOLVED (linux-64 + real hashes), never fabricated ----------
assert_boxlock() {
  local lock="$REPO/$1"
  [ -f "$lock" ] || fail "missing pixi.lock: $1"
  grep -q "linux-64" "$lock" || fail "pixi.lock has no linux-64 platform section (not box-solved): $1"
  grep -Eq "(sha256|md5):" "$lock" || fail "pixi.lock has no package hashes (looks fabricated): $1"
}

# ---- helper: run a pytest target in the core env (laptop; no GPU) -------------------------------
run_pytest() {
  local target="$1"
  ( cd "$REPO" && pixi run pytest $target -q ) || fail "pytest failed: $target"
}

# ---- helper: model folder from the task id (endpoints/<ep>/<model>) is read from result artifacts
model_folder() {
  python3 - "$RESULT" <<'PY'
import json,sys
r=json.load(open(sys.argv[1]))
# convention: first artifact under endpoints/.../ gives the folder
for a in r.get("artifacts",[]):
    if a.startswith("endpoints/") and a.count("/")>=3:
        print("/".join(a.split("/")[:3])); break
PY
}

case "$KIND" in

  bootstrap)
    # human-run; accept the worker's needs_aaran/pass self-report + require a note documenting box config
    [ "$STATUS" = "needs_aaran" ] && needs "box provisioning incomplete (pixi config / clone / .env)"
    ok "bootstrap recorded"
    ;;

  core|gate)
    TARGET="$($STATEPY field "$TASK" test)"
    [ -n "$TARGET" ] || fail "no pytest target declared in manifest"
    run_pytest "$TARGET"
    ok "pytest green: $TARGET"
    ;;

  aggregator)
    TARGET="$($STATEPY field "$TASK" test)"
    [ -n "$TARGET" ] || fail "no pytest target declared in manifest"
    run_pytest "$TARGET"
    ok "aggregator tests green: $TARGET"
    ;;

  aggregator-deferred)
    # hERG gate math is DEFERRED: accept a scaffold that is explicitly marked, refuse real weights
    [ "$STATUS" = "needs_aaran" ] || fail "deferred aggregator must report needs_aaran, not $STATUS"
    FOLDER="$(model_folder)"; [ -n "$FOLDER" ] && assert_file "$FOLDER/aggregate.py"
    grep -qi "DEFERRED" "$REPO/$FOLDER/aggregate.py" || fail "scaffold missing explicit DEFERRED marker"
    needs "hERG gate math deferred by decision - scaffold only"
    ;;

  sop)
    FOLDER="$(model_folder)"; [ -n "$FOLDER" ] || fail "no endpoints/ folder in artifacts"
    assert_file "$FOLDER/README.md"
    for sec in URL INPUTS "OUTPUT FIELDS" "LEDGER"; do
      grep -qi "$sec" "$REPO/$FOLDER/README.md" || fail "SOP README missing section: $sec"
    done
    ok "web-only SOP README complete"
    ;;

  model-api)
    # transport code + cache + placeholder schema present; live literal (header/modelId) is the residue
    FOLDER="$(model_folder)"; [ -n "$FOLDER" ] || fail "no endpoints/ folder in artifacts"
    assert_file "$FOLDER/run.py"
    assert_file "$FOLDER/README.md"
    grep -qi "TODO" "$REPO/$FOLDER/README.md" || fail "API adapter README must record the live-lookup TODO"
    [ "$STATUS" = "needs_aaran" ] && needs "live lookup (CSV header / modelId) requires an authenticated session"
    ok "API adapter built (placeholder schema)"
    ;;

  model-rule|model-code|model-legacy|model-heavy)
    FOLDER="$(model_folder)"; [ -n "$FOLDER" ] || fail "no endpoints/ folder in artifacts"
    assert_file "$FOLDER/README.md"
    # DERIVED models (e.g. pgp) have no env / run.py / smoke - the README + registry entry are the contract.
    if grep -qi "DERIVED" "$REPO/$FOLDER/README.md"; then
      ok "derived model (no env) - README contract present"
    fi
    assert_file "$FOLDER/run.py"
    # heavy non-python runtimes (OPERA/PBPK) isolate OUTSIDE pixi -> no in-folder pixi.lock required,
    # but they must ship a documented env recipe and a README SOP.
    if [ "$KIND" = "model-heavy" ] && grep -qiE "opera|pbpk|osp|matlab|\.net|ospsuite" "$REPO/$FOLDER/README.md"; then
      : # env is out-of-band; README is the contract
    else
      assert_boxlock "$FOLDER/pixi.lock"
    fi
    if [ "${GATE_RERUN_SMOKE:-0}" = "1" ]; then
      ( cd "$REPO" && ssh "$ROSENBLUTH" "cd \$FTO_ADMET_ROOT && pixi run --manifest-path $FOLDER/pixi.toml \
          python $FOLDER/run.py --input tests/fixtures/fto43.smi --output /tmp/$TASK.out" ) \
        || fail "box smoke re-run failed"
    else
      SMOKE_OK="$(python3 -c "import json;print(json.load(open('$RESULT')).get('smoke',{}).get('ok',False))")"
      [ "$SMOKE_OK" = "True" ] || fail "result.json smoke.ok is not true (set GATE_RERUN_SMOKE=1 to verify on box)"
    fi
    ok "model built + lock box-solved + smoke ok"
    ;;

  *)
    fail "unknown kind: $KIND"
    ;;
esac
