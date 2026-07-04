# t28-model-pgp - P-gp efflux flag (DERIVED from generalists; no independent env)

**Kind:** model-code (DERIVED) · **Autonomy:** high · **Runs:** author laptop; no box env
**Touch only:** `endpoints/distribution/pgp/**`, `tests/test_model_pgp.py`
**Deps:** t21-model-admet_ai · **Template:** derived - see below (NOT the t11 env pattern)

## Read first
- `docs/FTO_ADMET_Model_IO_SPEC.md` §1 #16 (P-gp via generalists).
- `CLAUDE.md` §5 (a DERIVED model has no env - README-only gate).

## Design decision (respect the settled skeleton)
The skeleton states P-gp is sourced **"via generalists (no separate service)"**. So `pgp` is a **DERIVED /
virtual model**: it has **no `pixi.toml`, no `pixi.lock`, no independent run.py execution**. Its value is the
`Pgp_Broccatelli` probability from **ADMET-AI** (t21), cross-checked with the **ADMETlab** P-gp head (t35).
It exists as a registry entry so provenance is explicit and the aggregator can query it by endpoint.

## Build
1. **Registry provenance:** confirm `pgp` in `core/registry.py` has `env_manifest=None`, `entrypoint=None`,
   `endpoints={distribution, permeability}`, and provenance `derived_from=[admet_ai, admetlab3]`.
2. **`README.md`** - mark it `**DERIVED (no env)**` (the gate keys on this), document that the P-gp
   substrate/inhibitor probability (0-1, **↑ = more efflux liability**) comes from `Pgp_Broccatelli`
   (ADMET-AI) with the ADMETlab P-gp head as cross-check; narrow-domain, **not a gate**.
3. **Wiring note (for t44/t46):** the distribution (t44) and permeability (t46) aggregators read
   `Pgp_Broccatelli` from the already-collected ADMET-AI output - no separate dispatch. Add a `pgp.py` helper
   in the folder that extracts/normalizes the field from a generalist `OutputRecord` (unit-testable, no env).
4. `tests/test_model_pgp.py`: given a synthetic ADMET-AI output with `Pgp_Broccatelli`, the helper returns the
   normalized efflux flag (0-1); no box, no subprocess.

## Landmines
- **No env, no lock, no smoke** - this is DERIVED. Do not build a duplicate P-gp model or a separate env.
- Narrow-domain flag, not a gate.

## Done (gate: model kind, DERIVED path - README + helper, no lock/smoke)
- README marked `DERIVED (no env)` with the source + direction; `pgp.py` helper extracts/normalizes the
  generalist P-gp field; `test_model_pgp.py` green on the laptop.
- Registry entry has `env_manifest=None` + `derived_from`.

## Blocked if
- Nothing external; laptop-only. Record any error and BLOCK.
