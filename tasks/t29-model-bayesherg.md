# t29-model-bayesherg - BayeshERG (hERG; legacy py3.6 + DGL; Bayesian uncertainty)

**Kind:** model-legacy · **Autonomy:** review · **Runs:** author laptop; env + smoke on box (serialize on the box)
**Touch only:** `endpoints/herg/bayesherg/**`, `tests/test_model_bayesherg.py`
**Deps:** t12-gate-phase1 · **Template:** follow t11 · **LEGACY - health-check the env FIRST**

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §1 #4 (BayeshERG I/O - 3 output columns).
- `docs/FTO_ADMET_Model_Provenance_VERIFIED.md` §B#4 + §E.8 (py3.6 + DGL, CC-BY-NC weights, env-age risk).
- `CLAUDE.md` §0 (lock on box), §5 (BLOCKED protocol - this is a blocked-expected env).

## Health-check FIRST (before writing the adapter)
The stack is **Python 3.6 + `dgl` + old `pytorch` + `rdkit`** (repo last modified 2022-11-18, no releases).
This combo on the **575.x CUDA driver** is known-painful. Before building the adapter, prove the env resolves
on the box: try a pinned legacy `pixi`/conda env; if CUDA won't cooperate, fall back to a **CPU-only or
old-CUDA build** (BayeshERG on CPU is acceptable for the shortlist). If neither resolves after 3 honest
attempts, **BLOCK** with the exact solver/CUDA error - do not fabricate a lock.

## Build (only after the env resolves)
- Input: `.csv` with a `smiles` column (optional `ID`). CLI:
  `python main.py -i input.csv -o out_name -c {cpu|gpu} -t <n_mc_samples, default 30>`.
- Output: appends **three columns** to `prediction_results/<out_name>.csv`:
  `score` (prob 0-1, hERG blocker prob, **↑ = more likely blocker**), `alea` (aleatoric ≥0),
  `epis` (epistemic ≥0). (Also writes attention `.svg`s - ignore for the bulk path.)
- Map `score` → `endpoint_values["P_block"]` (identity, feeds the gate core average); **`alea` + `epis` →
  `uncertainty`** (`uncertainty.aleatoric` / `uncertainty.epistemic` - these drive the split-case adjudicator).
- Vendor the repo; `requires_gpu=True` but honor a CPU fallback flag.

## Landmines
- **Trained weights are CC-BY-NC-4.0** (academic use only, no commercial) - the source is MIT but the weights
  aren't. **Record this in the README**; any hERG hit found with them inherits the restriction.
- Emit the aleatoric/epistemic split faithfully - it's what makes BayeshERG the adjudicator (better than a
  single MC-dropout scalar).
- Legacy env: **isolate**; do not let its old torch/dgl leak into any other env.

## Done (gate: model kind - box-solved lock + smoke ok)
- Box smoke on FTO-43 returns `score` + `alea` + `epis`; `uncertainty` carries the split; lock box-solved
  (may be CPU-only/old-CUDA - that's fine).
- README: CC-BY-NC weights, py3.6/DGL legacy note, CPU-fallback if used, direction. Access CODE-PKG.

## Blocked if
- The py3.6 + DGL + torch stack won't resolve on the box in any CPU or CUDA form after 3 attempts → BLOCK
  with the exact error. A clean BLOCK here is a real, expected signal - not a failure of this task.
