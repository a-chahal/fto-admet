"""The toxicity endpoint package.

Makes the endpoint importable so core can (later) load its ``aggregate.py``. Like every endpoint
package (CLAUDE.md §2, SETTLED §6) it is a thin marker: aggregators select their models by *endpoint
membership* in the registry (``Endpoint.toxicity in spec.endpoints``), never by folder layout, so the
per-model adapters live in their own subfolders, each in an isolated pixi env.

Models that feed toxicity: ``toxicophores`` (the RDKit FilterCatalog toxicity-alert screen, t18: a
single documented alert catalog - BRENK by default - reporting a match boolean + matched-alert names +
count) and, later, ``protox`` (the ProTox 3.0 WEB-ONLY SOP, t29) plus the cross-cutting generalist
``admet_ai`` (its tox classifier heads carry ``Endpoint.toxicity`` in the registry ``endpoints`` set).
The endpoint's aggregator rolls the ADMET-AI tox heads together with the toxicophores alerts into a
per-endpoint P(toxic) (docs IO_SPEC §2). (Organ-specific tox was an admetlab3 read; admetlab3 has been
removed, so organ-tox is a ProTox-manual-shortlist read only until an automatable replacement lands.)

``toxicophores`` is a **soft** structural-alert filter (docs IO_SPEC §28): it OVER-flags, so a hit means
"look closer", not auto-kill; **more alerts = more flagged**. It is DISTINCT from the ``structural_alerts``
``pains_brenk`` screen (t17) by *intent* - toxicity (known toxic / reactive substructures) here, versus
assay-interference (PAINS) there - not by mechanism, even though both are RDKit ``FilterCatalog`` screens.
The consuming policy is downstream; the adapter here only emits the raw flag / count / matched names.
"""
