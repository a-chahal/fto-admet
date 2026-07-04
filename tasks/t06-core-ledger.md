# t06-core-ledger - `core/ledger.py` (append-only run ledger)

**Kind:** core · **Autonomy:** high · **Runs:** laptop to author + test; real writes happen on the box
**Touch only:** `core/ledger.py`, `tests/test_ledger.py`
**Deps:** t01-core-config

## Read first
- `docs/FTO_ADMET_Codebase_And_Environment_SETTLED.md` §7 (`core/ledger.py`: JSONL not SQLite; written by the job on the box).
- `CLAUDE.md` §0 (ledger on `/zfs`, written by the job at completion) and the raw-output-caching note in §4a.

## Build
The reproducibility trail. **Append-only JSONL on `/zfs`** (SQLite's file locking is unreliable over NFS;
appends are safe). Written **by the job itself, on the box, at completion**, so a dropped laptop
connection never loses a record.

1. **Record schema** (one JSON object per line):
   `{model, input_hash, output_path, env_lock_hash, cuda_device, timestamp, status}`.
   `status ∈ {ok, fail}`. `timestamp` ISO-8601 UTC. Add `note` (optional, e.g. failure reason).
2. `append(record)` → open the ledger path (`config.ledger`) in append mode, write one line, `flush()` +
   `os.fsync()`. Create the parent dir if missing. No read-modify-write of the whole file.
3. Hash helpers: `hash_input(smiles|input_file)` and `hash_env_lock(pixi.lock path)` - deterministic
   (sha256), so identical inputs/envs produce identical hashes for provenance matching.
4. `load()` → read all lines into a list of dicts (or a DataFrame if pandas is in the core env) for
   querying; tolerate a trailing partial line without crashing.
5. **Raw-output caching helper** (infra, in scope now - `CLAUDE.md` §4a): a `cache_raw(model, input_hash,
   payload)` that writes verbatim upstream responses under `config.root / "cache" / model / <hash>.json`
   so async/web results are reconstructible after a service silently changes.

## Landmines
- **JSONL, not SQLite** (NFS). Append + fsync; never rewrite the file.
- Keep the ledger on persistent storage under `/zfs`, never in a cache dir that could be purged.

## Done (gate: `pixi run pytest tests/test_ledger.py -q` green)
- Appending N records yields N valid JSON lines in order; each parses; required keys present.
- `hash_input`/`hash_env_lock` are deterministic (same input → same hash; different → different).
- `load()` round-trips the records and tolerates a truncated final line.
- `cache_raw` writes a retrievable verbatim payload keyed by (model, input_hash).

## Blocked if
- Laptop-only for authoring+tests (use a tmp dir for the ledger). Record any error and BLOCK.
