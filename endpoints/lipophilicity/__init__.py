"""The lipophilicity endpoint package.

Makes the endpoint importable so core can (later) load its ``aggregate.py`` (t40). The aggregator
selects its models by *endpoint membership* in the registry (``Endpoint.lipophilicity in
spec.endpoints``), never by folder layout (CLAUDE.md §2, SETTLED §6), so this package intentionally
stays a thin marker: the per-model adapters live in their own subfolders, each in an isolated pixi env.

Models that feed lipophilicity: ``rdkit_crippen`` (the WLOGP lens, t10), plus the cross-cutting
``admet_ai`` and ``opera`` and the ``swissadme`` reconstruction, which carry ``Endpoint.lipophilicity``
in their registry ``endpoints`` set.
"""
