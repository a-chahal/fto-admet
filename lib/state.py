#!/usr/bin/env python3
"""state.py - durable task-state ledger for the FTO-ADMET build loop.

Single source of run status. Reads the DAG from MANIFEST.yaml, tracks each task's status in
STATE.json, and answers the one question the orchestrator needs: "what is the next task that is ready
to run?" Ready = status PENDING and every dependency is DONE.

Design goals (match project priorities): reliability (atomic writes, never a half-written STATE.json),
reproducibility (status survives across fresh sessions and restarts - this is what makes the loop
resumable), zero external dependencies (stdlib only, with a minimal manifest parser used if PyYAML is
absent, so this runs before any pixi env exists).

Usage:
    state.py seed # create/extend STATE.json from MANIFEST.yaml (never clobbers)
    state.py next [--include-human] # print id of next ready task, or nothing
    state.py field <id> <key> # print one manifest/state field (kind, autonomy, test, status)
    state.py set <id> <status> [--note S] [--commit S] [--attempts-inc]
    state.py summary # counts + BLOCKED / NEEDS_AARAN / DEFERRED lists
    state.py validate # check the DAG: unknown deps, cycles

Statuses: PENDING IN_PROGRESS DONE BLOCKED NEEDS_AARAN DEFERRED
"""
from __future__ import annotations
import argparse
import contextlib
import fcntl
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "MANIFEST.yaml")
STATE = os.path.join(ROOT, "STATE.json")
LOCK = STATE + ".lock"


@contextlib.contextmanager
def state_lock():
    """Exclusive lock around a read-modify-write of STATE.json. Without it, two concurrent `set`s each
    read the whole file and the second write clobbers the first's change (a lost update). The atomic
    replace in save_state prevents *corruption*; this prevents *lost updates* - so parallel workers are
    safe, not just the serial loop. POSIX (linux + macOS)."""
    with open(LOCK, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)

TERMINAL = {"DONE", "BLOCKED", "NEEDS_AARAN", "DEFERRED"}
VALID = {"PENDING", "IN_PROGRESS"} | TERMINAL
# A dependency is "satisfied" for a downstream task once its adapter + schema exist. That is true at
# DONE, at NEEDS_AARAN (e.g. an API adapter built; only a live literal remains), and at DEFERRED (a
# scaffold exists by decision). It is NOT satisfied at BLOCKED / PENDING / IN_PROGRESS. Aggregators test
# against synthetic OutputRecords, so they need the schema, not the model's real output.
SATISFIED = {"DONE", "NEEDS_AARAN", "DEFERRED"}


# --------------------------------------------------------------------------- manifest parsing
def load_manifest() -> dict:
    """Return the parsed manifest. Prefer PyYAML; fall back to a minimal parser that handles
    exactly this project's manifest shape (block-sequence of mappings, scalar values, flow-list
    `deps: [a, b]`). The fallback is intentionally narrow - it is not a general YAML parser."""
    with open(MANIFEST, "r", encoding="utf-8") as fh:
        text = fh.read()
    try:
        import yaml # type: ignore
        return yaml.safe_load(text)
    except Exception:
        return _mini_parse(text)


def _mini_parse(text: str) -> dict:
    out: dict = {"tasks": []}
    cur: dict | None = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip() if not _in_quotes(raw) else raw.rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        s = line.strip()
        if indent == 0 and s.endswith(":"):
            # top-level key with nested block (phases:, tasks:) - we only care about tasks
            cur_key = s[:-1]
            out.setdefault(cur_key, [] if cur_key in ("tasks", "phases") else {})
            _cur_top[0] = cur_key
            continue
        if indent == 0 and ":" in s:
            k, v = s.split(":", 1)
            out[k.strip()] = _scalar(v.strip())
            continue
        if _cur_top[0] == "tasks":
            if s.startswith("- "):
                cur = {}
                out["tasks"].append(cur)
                s = s[2:].strip()
                if not s:
                    continue
            if cur is not None and ":" in s:
                k, v = s.split(":", 1)
                cur[k.strip()] = _scalar(v.strip())
    return out


_cur_top = [""]


def _in_quotes(line: str) -> bool:
    # a value like test: tests/ -m "not model" contains a '#'? no; but quotes may contain '#'
    return line.count('"') >= 2 and "#" in line and line.index('"') < line.index("#")


def _scalar(v: str):
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        return [x.strip() for x in inner.split(",")] if inner else []
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    if v.isdigit() or (v.startswith("-") and v[1:].isdigit()):
        return int(v)
    return v


def tasks_by_id(man: dict) -> dict:
    return {t["id"]: t for t in man.get("tasks", [])}


# --------------------------------------------------------------------------- state io (atomic)
def load_state() -> dict:
    if not os.path.exists(STATE):
        return {"project": "fto-admet", "updated": None, "tasks": {}}
    with open(STATE, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_state(st: dict) -> None:
    st["updated"] = datetime.now(timezone.utc).isoformat()
    d = os.path.dirname(STATE)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".state.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(st, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, STATE) # atomic on POSIX
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# --------------------------------------------------------------------------- commands
def cmd_seed(_):
    man = load_manifest()
    with state_lock():
        st = load_state()
        added = 0
        for tid in tasks_by_id(man):
            if tid not in st["tasks"]:
                st["tasks"][tid] = {"status": "PENDING", "attempts": 0, "note": "", "commit": ""}
                added += 1
        save_state(st)
    print(f"seeded: {added} new task(s); {len(st['tasks'])} total")


def cmd_next(args):
    man = load_manifest()
    st = load_state()
    tbi = tasks_by_id(man)
    satisfied = {tid for tid, s in st["tasks"].items() if s["status"] in SATISFIED}
    # deterministic order = manifest order (already phase-sorted)
    for t in man.get("tasks", []):
        tid = t["id"]
        s = st["tasks"].get(tid, {"status": "PENDING"})
        if s["status"] != "PENDING":
            continue
        if not all(d in satisfied for d in _deps(t)):
            continue
        if t.get("autonomy") == "human" and not args.include_human:
            continue
        print(tid)
        return
    # nothing ready under the given filter
    return


def cmd_field(args):
    man = load_manifest()
    st = load_state()
    t = tasks_by_id(man).get(args.id, {})
    if args.key == "status":
        print(st["tasks"].get(args.id, {}).get("status", "UNKNOWN"))
    elif args.key in ("attempts", "note", "commit"):
        print(st["tasks"].get(args.id, {}).get(args.key, ""))
    else:
        v = t.get(args.key, "")
        print(",".join(v) if isinstance(v, list) else v)


def cmd_set(args):
    status = args.status.upper()
    if status not in VALID:
        sys.exit(f"invalid status {status!r}; valid: {sorted(VALID)}")
    with state_lock():
        st = load_state()
        rec = st["tasks"].setdefault(args.id, {"status": "PENDING", "attempts": 0, "note": "", "commit": ""})
        rec["status"] = status
        if args.attempts_inc:
            rec["attempts"] = int(rec.get("attempts", 0)) + 1
        if args.note is not None:
            rec["note"] = args.note
        if args.commit is not None:
            rec["commit"] = args.commit
        save_state(st)
    print(f"{args.id} -> {status} (attempts={rec['attempts']})")


def cmd_summary(_):
    man = load_manifest()
    st = load_state()
    counts: dict[str, int] = {}
    buckets: dict[str, list] = {"BLOCKED": [], "NEEDS_AARAN": [], "DEFERRED": []}
    for t in man.get("tasks", []):
        tid = t["id"]
        s = st["tasks"].get(tid, {}).get("status", "PENDING")
        counts[s] = counts.get(s, 0) + 1
        if s in buckets:
            buckets[s].append(tid)
    total = sum(counts.values())
    print(f"FTO-ADMET build - {total} tasks")
    for k in ("DONE", "IN_PROGRESS", "PENDING", "NEEDS_AARAN", "BLOCKED", "DEFERRED"):
        if counts.get(k):
            print(f" {k:12} {counts[k]}")
    for name, ids in buckets.items():
        if ids:
            print(f"\n{name}:")
            for i in ids:
                note = st["tasks"].get(i, {}).get("note", "")
                print(f" - {i}: {note}")
    ready = _count_ready(man, st)
    print(f"\nready to run now: {ready}")


def cmd_plan(args):
    """Simulate the build order from the current state WITHOUT mutating STATE.json.
    Greedy topological pass: a task runs when its deps are DONE and it is not human-gated
    (unless --include-human). Shows the realistic unattended execution order, then what would wait
    for Aaran, then anything unreachable behind those."""
    man = load_manifest()
    st = load_state()
    status = {t["id"]: st["tasks"].get(t["id"], {}).get("status", "PENDING") for t in man["tasks"]}
    done = {tid for tid, s in status.items() if s in SATISFIED} # already-satisfied deps count
    order, waiting = [], []
    progressed = True
    while progressed:
        progressed = False
        for t in man["tasks"]:
            tid = t["id"]
            if tid in done or tid in order:
                continue
            if status[tid] in TERMINAL: # already terminal - don't re-run
                continue
            if not all(d in done for d in _deps(t)):
                continue
            if t.get("autonomy") == "human" and not args.include_human:
                if tid not in waiting:
                    waiting.append(tid)
                continue
            order.append(tid)
            done.add(tid)
            progressed = True
    print(f"# autonomous execution order ({len(order)} tasks):")
    for i, tid in enumerate(order, 1):
        print(f"{i:2}. {tid}")
    if waiting:
        print(f"\n# would pause for Aaran ({len(waiting)} human-gated):")
        for tid in waiting:
            print(f" - {tid}")
    unreached = [t["id"] for t in man["tasks"]
                 if t["id"] not in done and t["id"] not in order and t["id"] not in waiting
                 and status[t["id"]] not in TERMINAL]
    if unreached:
        print(f"\n# blocked behind the above until resolved ({len(unreached)}):")
        for tid in unreached:
            print(f" - {tid}")


def cmd_reset_stale(_):
    """Reset any IN_PROGRESS task back to PENDING. A crash / kill / laptop-sleep mid-task leaves a task
    IN_PROGRESS forever, and `next` only serves PENDING - so without this, a crashed task is orphaned and
    the build silently stalls. run.sh calls this on startup so the loop is truly resumable. The attempts
    counter is preserved, so the cap still applies."""
    with state_lock():
        st = load_state()
        n = 0
        for tid, rec in st["tasks"].items():
            if rec.get("status") == "IN_PROGRESS":
                rec["status"] = "PENDING"
                rec["note"] = "reset from stale IN_PROGRESS (crash/kill/sleep resume)"
                n += 1
        if n:
            save_state(st)
    print(f"reset {n} stale IN_PROGRESS task(s)")


def cmd_validate(_):
    man = load_manifest()
    tbi = tasks_by_id(man)
    errs = []
    for t in man.get("tasks", []):
        for d in _deps(t):
            if d not in tbi:
                errs.append(f"{t['id']}: unknown dep {d}")
    # cycle check (Kahn)
    indeg = {tid: 0 for tid in tbi}
    for t in man.get("tasks", []):
        for d in _deps(t):
            if d in indeg:
                indeg[t["id"]] += 1
    from collections import deque
    q = deque([n for n, v in indeg.items() if v == 0])
    seen = 0
    adj: dict[str, list] = {tid: [] for tid in tbi}
    for t in man.get("tasks", []):
        for d in _deps(t):
            if d in adj:
                adj[d].append(t["id"])
    while q:
        n = q.popleft()
        seen += 1
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                q.append(m)
    if seen != len(tbi):
        errs.append(f"cycle detected: only {seen}/{len(tbi)} tasks topologically ordered")
    if errs:
        print("DAG INVALID:")
        for e in errs:
            print(" -", e)
        sys.exit(1)
    print(f"DAG OK: {len(tbi)} tasks, no unknown deps, no cycles")


# --------------------------------------------------------------------------- helpers
def _deps(t: dict) -> list:
    d = t.get("deps", [])
    return d if isinstance(d, list) else ([d] if d else [])


def _count_ready(man, st) -> int:
    satisfied = {tid for tid, s in st["tasks"].items() if s["status"] in SATISFIED}
    n = 0
    for t in man.get("tasks", []):
        s = st["tasks"].get(t["id"], {}).get("status", "PENDING")
        if s == "PENDING" and all(x in satisfied for x in _deps(t)):
            n += 1
    return n


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed").set_defaults(fn=cmd_seed)
    n = sub.add_parser("next"); n.add_argument("--include-human", action="store_true"); n.set_defaults(fn=cmd_next)
    f = sub.add_parser("field"); f.add_argument("id"); f.add_argument("key"); f.set_defaults(fn=cmd_field)
    s = sub.add_parser("set"); s.add_argument("id"); s.add_argument("status")
    s.add_argument("--note"); s.add_argument("--commit"); s.add_argument("--attempts-inc", action="store_true")
    s.set_defaults(fn=cmd_set)
    sub.add_parser("summary").set_defaults(fn=cmd_summary)
    pl = sub.add_parser("plan"); pl.add_argument("--include-human", action="store_true"); pl.set_defaults(fn=cmd_plan)
    sub.add_parser("validate").set_defaults(fn=cmd_validate)
    sub.add_parser("reset-stale").set_defaults(fn=cmd_reset_stale)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        # downstream closed the pipe (e.g. `| head`); exit quietly
        try:
            sys.stdout.close()
        finally:
            os._exit(0)
