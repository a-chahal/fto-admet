"""The permeability endpoint package (aggregate-only - no ModelName maps to it).

Permeability owns no adapter of its own (IO_SPEC §1 #23, SETTLED §6). It is a pure aggregate read that
consumes fields already emitted by the cross-cutting generalists (ADMET-AI ``Caco2_Wang``, ``HIA_Hou``,
``PAMPA_NCATS``, ``Bioavailability_Ma``, ``Pgp_Broccatelli``) plus the BOILED-Egg HIA boolean
(``HIA_boiled_egg``, the same one registered implementation that also serves distribution's BBB read).
Like every endpoint package it is a thin marker: the aggregator selects contributors by *endpoint
membership* in the registry (``Endpoint.permeability in spec.endpoints``), never by folder layout.

The endpoint may be partly moot for FTO-43 given possible intratumoral / osmotic-pump delivery (task
t46, IO_SPEC §1 #23): oral GI absorption matters less if the drug is not delivered orally. So this is
KEPT as an aggregate triage read (a permeability flag + an absorption flag), not a gate, and there is
NO single combined permeability scalar.
"""
