# pgp - P-gp efflux flag (DERIVED, no env)

**DERIVED (no env).** P-glycoprotein (P-gp / ABCB1) efflux liability is sourced **via the generalists,
with no separate service** (SETTLED skeleton; IO_SPEC §1 #16). So `pgp` is a **virtual / DERIVED model**:
it has **no `pixi.toml`, no `pixi.lock`, and no independently executed `run.py`**. There is nothing to
install and nothing to smoke-test. It exists as a registry entry so provenance is explicit and the
distribution (t44) / permeability (t46) aggregators can query it by endpoint membership, and as the tiny
env-free helper (`pgp.py`) those aggregators call to read the field off an already-collected generalist
output.

## Source + direction

| field | source | range | direction |
| --- | --- | --- | --- |
| P-gp efflux flag | **`Pgp_Broccatelli`** from **ADMET-AI** (t21), cross-checked with the **ADMETlab** P-gp head (t35) | probability `[0, 1]` | **UP = more efflux liability** |

- **Primary source:** ADMET-AI's `Pgp_Broccatelli` head (TDC Pgp_Broccatelli model), already emitted into
  that model's `endpoint_values`. It is a P(P-gp substrate / inhibitor), so its native direction already is
  **higher = more efflux liability** and the helper applies **no inversion**.
- **Cross-check:** the ADMETlab 3.0 P-gp head. ADMETlab's exact CSV column name is one of the 119 literal
  column names that require a single live `/api/admetCSV` call to capture (CLAUDE.md §4; ADMETlab is
  `needs_aaran` at t35). Until t35 captures the header, `ADMETLAB_PGP_KEY` stays `None` and the cross-check
  is a no-op - the literal is **not guessed** (no-fabricate rule). `TODO(t35)`: set `ADMETLAB_PGP_KEY` once
  the live header lands.

## Narrow-domain, NOT a gate

P-gp prediction is a **narrow-domain flag**: usable only in-domain, and it is **not a gate** - do not
promote or reject FTO-43 (or any candidate) on it alone. It is one vote in the **efflux** row that the
distribution (t44) and permeability (t46) aggregators reconcile alongside the web signals (Watanabe P-gp
brain NER.class, Kp,uu,brain - both WEB-ONLY via DruMAP, #17). Higher efflux implies lower CNS penetration,
but the real CNS answer is experimental, not this flag (skeleton posture).

## The helper (`pgp.py`)

`extract_pgp_flag(record) -> float | None` (and the richer `extract_pgp(record) -> PgpFlag`, which also
reports the source head + model for aggregator provenance) takes an **already-collected** generalist
`OutputRecord` - either the validated `core.schemas.OutputRecord` object `core.dispatch` produced for
ADMET-AI / ADMETlab, or its plain-JSON dict form - and returns the normalized efflux flag in `[0, 1]`:

- Reads `endpoint_values`, trying `Pgp_Broccatelli` first, then the ADMETlab P-gp key (once t35 wires it).
- Returns `None` when the head is **absent, null, non-numeric, or outside `[0, 1]`**. Out-of-range values
  are **rejected** (not silently clamped), so a malformed upstream number never poses as a probability.
- Imports nothing from `core` (it duck-types the record), so it is unit-testable on the laptop with **no
  box, GPU, subprocess, or pixi env**. This is the whole "run" surface of a DERIVED model: no dispatch.

**Wiring note (t44 / t46):** the distribution and permeability aggregators read `Pgp_Broccatelli` from the
already-collected ADMET-AI output via this helper - there is **no separate dispatch** for `pgp`. Selecting
`pgp` by endpoint membership documents that the efflux vote exists; the number itself is the generalist's.

## Registry entry

A DERIVED model carries **`env_manifest=None`, `entrypoint=None`** (it never enters the bulk `pixi run`
path) and provenance **`derived_from=[admet_ai, admetlab3]`**. `endpoints={distribution, permeability}` (it
feeds both) is already correct via the registry's `_CROSS_CUTTING` map.

> **Note / follow-up for the registry owner (t04, `core/registry.py` - out of this task's touch scope):**
> the current registry row builds `pgp` with `has_env=True` (so `env_manifest`/`entrypoint` point at a
> non-existent `endpoints/distribution/pgp/pixi.toml` + `run.py`) and access tag `"CODE"`, and `Provenance`
> has no `derived_from` field. To match this DERIVED design the row should be `has_env=False` (giving
> `env_manifest = entrypoint = None`), and `Provenance` should gain a `derived_from=[admet_ai, admetlab3]`
> field. This is a `core` change owned by t04 and is **not** edited here (model tasks must not touch
> `core`); it is flagged so the discrepancy is visible and not silently accepted.

## Provenance

- **Kind:** DERIVED / virtual model - no env, no lock, no smoke. Value comes entirely from the generalists.
- **Upstream:** none of its own. Inherits ADMET-AI's `Pgp_Broccatelli` (TDC Pgp_Broccatelli; Broccatelli et
  al., J. Med. Chem. 2011) and, as cross-check, the ADMETlab 3.0 P-gp head.
- **Access tag:** DERIVED (sourced via generalists).
- **License:** inherits the generalists' licenses (ADMET-AI: MIT; ADMETlab: web service terms). No
  additional weights or code are vendored here.
- **Quirks:** DERIVED - do **not** build a duplicate P-gp model or a separate env; `Pgp_Broccatelli` is
  already `[0, 1]` with UP = more efflux (no inversion); narrow-domain flag, **not a gate**; ADMETlab P-gp
  column name is a `needs_aaran` live literal (t35) - left as `None`, not guessed.
