"""The plasma-protein-binding (ppb) endpoint package.

Makes the endpoint importable so core can (later) load its ``aggregate.py``. Like every endpoint, the
aggregator selects its models by *endpoint membership* in the registry (``Endpoint.ppb in
spec.endpoints``), never by folder layout (CLAUDE.md §2, SETTLED §6), so this package stays a thin
marker: the per-model adapters live in their own subfolders.

The common ppb quantity is **fraction bound (0-1)**, direction ↑ = more bound / less free (IO_SPEC §2).
Models feeding ppb: ``ochem_ppb`` (the primary, an async REST model; this task t36), plus the
cross-cutting ``admet_ai`` (``PPBR_AZ`` = % bound -> /100), ``admetlab3`` (% bound), and ``opera``
(``FuB_pred`` = fraction *unbound* -> 1 - FuB), which each carry ``Endpoint.ppb`` in their registry
``endpoints`` set. The ppb aggregator that harmonizes these (fraction-vs-percent-vs-unbound, F-7) is a
later task; this package only makes the endpoint importable.
"""
