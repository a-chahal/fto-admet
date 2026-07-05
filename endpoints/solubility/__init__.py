"""The solubility endpoint package.

Makes the endpoint importable so core can (later) load its ``aggregate.py`` (t41). The aggregator
selects its models by *endpoint membership* in the registry (``Endpoint.solubility in
spec.endpoints``), never by folder layout (CLAUDE.md §2, SETTLED §6), so this package intentionally
stays a thin marker: the per-model adapters live in their own subfolders, each in an isolated pixi env.

Models that feed solubility: ``sfi`` (the Solubility Forecast Index rule, t13; LOWER = better), plus the
cross-cutting generalists (e.g. ADMET-AI ``Solubility_AqSolDB``, higher log S = better) that carry
``Endpoint.solubility`` in their registry ``endpoints`` set. The t41 aggregator reconciles the direction
inversion between SFI (lower = more soluble) and the generalist log S (higher = more soluble).
"""
