# t34-model-pbpk - PBPK / OSP (whole-body integrator; R 4.x + .NET 8, OUT-OF-BAND)

**Kind:** model-heavy · **Autonomy:** review · **Runs:** author laptop; runtime out-of-band on box · **in_bulk_loop = False**
**Touch only:** `endpoints/clearance/pbpk/**`, `tests/test_model_pbpk.py`
**Deps:** t12-gate-phase1 · **Template:** heavy/out-of-band - README SOP + optional R scaffold (no pixi env)

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §1 #12 (PBPK - not a per-molecule predictor).
- `docs/FTO_ADMET_Model_Provenance_VERIFIED.md` §B#13 + §E.4 (R 4.x + .NET 8 + OSP binaries).

## Design (POINTER; out-of-band)
PBPK is **not a per-molecule predictor** - it is an **integrator**. A PK-Sim model is parameterized with
**other endpoints' outputs** (CL, fu, permeability, logP) and simulated via the **`ospsuite` R package**
(**R 4.x + .NET 8 + OSP binaries**). `env_manifest=None`, `in_bulk_loop=False`, **shortlist only**. It runs
after the endpoints that feed it, so it is not on the automated bulk path.

## Build (mostly documentation + scaffold)
- **README SOP:** the install recipe (R 4.x, .NET 8, OSP Suite / PK-Sim binaries), how the model is
  parameterized from upstream endpoint outputs (which fields → which PK-Sim inputs), the simulation invocation
  via `ospsuite`, and **which output metrics get transcribed to the ledger** (C(t) profile → Cmax, AUC, etc.
   - no fixed output schema; the modeler extracts key metrics).
- **Optional R scaffold:** a commented `pbpk.R` skeleton showing the `ospsuite` call structure and the
  parameterization from upstream outputs - a starting point, not a turnkey run.
- `run.py` (thin): a ledger-transcription helper that takes the extracted metrics (Cmax/AUC/…) and writes an
  `OutputRecord` (so PBPK results enter the ledger uniformly). Unit-test it on sample metrics (no OSP needed).

## Landmines
- **Not a predictor - an integrator.** Do not treat it as SMILES→number; it consumes other endpoints' outputs.
- **Isolate outside pixi** (R + .NET). Shortlist only; never in the bulk loop.

## Done (gate: model-heavy - README SOP + transcription helper)
- README SOP complete (install recipe, parameterization mapping, transcribed metrics); `pbpk.R` scaffold
  present; `run.py` transcription helper unit-tested on sample metrics (laptop).
- If the OSP/R/.NET stack is installed on the box, note it; otherwise `status=needs_aaran` for the heavy
  install (the SOP + scaffold are the deliverable).

## Blocked if
- The transcription helper can't be built/tested (should not happen) → BLOCK. (Missing OSP install ⇒
  `needs_aaran`, not blocked - PBPK is a POINTER, expected to trail the endpoints that feed it.)
