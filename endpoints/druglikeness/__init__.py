"""The druglikeness endpoint package.

Makes the endpoint importable so core can (later) load its ``aggregate.py``. Like every endpoint
package (CLAUDE.md §2, SETTLED §6) it is a thin marker: aggregators select their models by *endpoint
membership* in the registry (``Endpoint.druglikeness in spec.endpoints``), never by folder layout, so
the per-model adapters live in their own subfolders, each in an isolated pixi env.

Models that feed druglikeness: ``lipinski_veber_qed`` (the RDKit drug-likeness context rule, t19: a
single deterministic screen reporting Lipinski Ro5 violations, the Veber pass/fail, and QED).

**Context / POINTER only - not a gate** (docs IO_SPEC §30, task t19). The druglikeness endpoint reports
these as *flags* for the lab's sanity check; the aggregator (t50) never turns them into a kill. Lipinski
violations and the Veber test over-summarise (many marketed drugs violate Ro5), so a violation means
"note it", not "drop it". Directions (docs §30): **fewer Lipinski violations = more drug-like**, **Veber
pass = more drug-like**, **higher QED = more drug-like**.
"""
