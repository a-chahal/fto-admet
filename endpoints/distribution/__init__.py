"""The distribution / BBB / CNS endpoint package.

Makes the endpoint importable so core can (later) load its ``aggregate.py``. Like every endpoint
package (CLAUDE.md §2, SETTLED §6) it is a thin marker: aggregators select their models by *endpoint
membership* in the registry (``Endpoint.distribution in spec.endpoints``), never by folder layout, so
the per-model adapters live in their own subfolders, each in an isolated pixi env.

Models that feed distribution: ``bbb_score`` (the Gupta 2019 passive brain-entry rule, t14; 0-6,
higher = more likely passive BBB penetrant), ``cns_mpo`` (t15), ``boiled_egg`` (the BBB yolk region,
shared with permeability), plus the cross-cutting generalists (e.g. ADMET-AI ``BBB_Martins``) that
carry ``Endpoint.distribution`` in their registry ``endpoints`` set.

These passive-penetration scores are on incompatible scales (F-4: 0-6 desirability vs probability vs
boolean) and are triage filters, not a gate: the real CNS answer is experimental Kp,uu (skeleton
posture). BBB penetration is desirable, not required.
"""
