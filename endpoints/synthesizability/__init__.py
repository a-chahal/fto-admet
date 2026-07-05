"""The synthesizability endpoint package.

Makes the endpoint importable so core can (later) load its ``aggregate.py``. Like every endpoint
package (CLAUDE.md §2, SETTLED §6) it is a thin marker: aggregators select their models by *endpoint
membership* in the registry (``Endpoint.synthesizability in spec.endpoints``), never by folder layout,
so the per-model adapters live in their own subfolders, each in an isolated pixi env.

Models that feed synthesizability: ``sascore`` (Ertl & Schuffenhauer synthetic-accessibility score,
t20; a deterministic RDKit-Contrib rule reporting a single 1-10 score).

**Escalating tier ladder, not one scalar** (docs IO_SPEC §25 / §2 synthesizability). The three rungs
have different scales and are reported as a tier/flag, never averaged:

    SAscore (1-10, LOWER = easier) -> RAscore (P route findable) -> AiZynthFinder (solved bool + routes)

``sascore`` is the **first rung**: a fast triage screen. Its direction inverts the "higher = better"
intuition: **lower SAscore = easier to synthesize** (Ertl & Schuffenhauer 2009). The synthesizability
aggregator (t48) consumes it as the first rung of that ladder; this adapter emits only the raw score.
"""
