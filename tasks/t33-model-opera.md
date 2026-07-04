# t33-model-opera - OPERA (logP/logD/pKa + AD; MATLAB MCR + Java, OUT-OF-BAND)

**Kind:** model-heavy · **Autonomy:** review · **Runs:** author laptop; runtime out-of-band on box
**Touch only:** `endpoints/lipophilicity/opera/**`, `tests/test_model_opera.py`
**Deps:** t12-gate-phase1 · **Template:** heavy/out-of-band - README recipe + a PARSER `run.py` (no pixi env)

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §1 #21 (OPERA - VERIFIED output columns).
- `docs/FTO_ADMET_Model_Provenance_VERIFIED.md` §B#23 + §E.4 (MCR + Java; isolate).
- `CLAUDE.md` §4 (isolate OUTSIDE pixi).

## Design (out-of-band)
OPERA is compiled MATLAB → free **MATLAB Compiler Runtime (MCR, e.g. v912)** + **Java (PaDEL/CDK)**. It is
**isolated OUTSIDE pixi** (`env_manifest=None`). The **code deliverable is `run.py` as a parser/wrapper**: it
invokes the out-of-band `./run_OPERA.sh <MCR_path> -d in.csv -o preds.txt -e LogP LogD pKa ... -v 1` (path to
the MCR + OPERA install comes from config/README) and parses `preds.txt` into `OutputRecord`s. The MCR/Java
install itself is documented in the README, not solved by pixi.

## Build
- Requested endpoints for this pipeline: **LogP, LogD, pKa_a/pKa_b, FuB, Clint, Caco2** (multi-endpoint).
- Output columns (VERIFIED): first col `MoleculeID`; then per endpoint X - `<X>_pred`, `AD_<X>` (0/1 in/out
  domain), `AD_index_<X>` (0-1), `Conf_index_<X>` (0-1, **↑ = more reliable → DIRECT uncertainty**).
  **No `_predRange` column.** Units: LogP (log Kow), LogD (log), FuB (fraction), Clint (µL/min/10⁶ cells),
  Caco2 (logPapp).
- `run.py` parses these into records: `endpoint_values` = the `_pred` values; **`AD_<X>`/`AD_index_<X>`/
  `Conf_index_<X>` → `uncertainty`** (ad_in_domain / ad_index / confidence). Unit-test the parser against a
  captured sample `preds.txt` (no MCR needed for the parser test).
- **Cross-cutting** (`endpoints = {lipophilicity, clearance, ppb}`): LogD/pKa standardize SFI/BBB/CNS-MPO,
  Clint cross-checks metabolism, FuB cross-checks OCHEM PPB.

## Landmines
- **Isolate outside pixi** - no MCR/Java in any pixi env; the README carries the install recipe.
- The `_pred`/`AD_`/`AD_index_`/`Conf_index_` casing is verified - parse exactly; there is **no** range column.
- `Conf_index` is a real DIRECT uncertainty - populate it, don't discard it.

## Done (gate: model-heavy - README recipe + parser; box smoke if MCR installed, else needs_aaran)
- `run.py` parser turns a sample `preds.txt` into records with `uncertainty` populated (unit test green,
  laptop). README documents the MCR/Java install recipe + the exact `run_OPERA.sh` command + output mapping.
- If MCR is installed on the box, a real smoke on FTO-43 runs and `smoke.ok=true`; if the heavy runtime is
  **not yet installed**, report `status=needs_aaran` (the parser is done; the MCR install is the residue).

## Blocked if
- The parser cannot be built/tested against a sample output (should not happen), or the OPERA release itself
  is unobtainable → BLOCK. (Missing MCR install ⇒ `needs_aaran`, not blocked.)
