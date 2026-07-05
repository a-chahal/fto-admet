"""The triage endpoint package.

Makes the endpoint importable so core can (later) load its ``aggregate.py``. As with every endpoint,
aggregators select their models by *endpoint membership* in the registry
(``Endpoint.triage in spec.endpoints``), never by folder layout (CLAUDE.md §2, SETTLED §6), so this
package stays a thin marker: the per-model adapters live in their own subfolders, each in an isolated
pixi env.

triage physically hosts the three cross-cutting generalists (``admet_ai``, ``admetlab3``, ``openadmet``):
they sit under this folder but their outputs feed several endpoints' aggregators, because their registry
``endpoints`` set is a superset (e.g. ``admet_ai`` carries triage + herg + metabolism + clearance + ppb +
solubility + lipophilicity + permeability + distribution + toxicity). Model -> endpoint is a light graph
(``ModelSpec.endpoints`` is a set); an aggregator that wants ADMET-AI's ``hERG`` head queries the registry
by ``Endpoint.herg``, not by the ``triage/`` folder it happens to live in.
"""
