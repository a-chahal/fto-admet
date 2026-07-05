"""The structural-alerts endpoint package.

Makes the endpoint importable so core can (later) load its ``aggregate.py``. Like every endpoint
package (CLAUDE.md §2, SETTLED §6) it is a thin marker: aggregators select their models by *endpoint
membership* in the registry (``Endpoint.structural_alerts in spec.endpoints``), never by folder layout,
so the per-model adapters live in their own subfolders, each in an isolated pixi env.

Models that feed structural_alerts: ``pains_brenk`` (the RDKit FilterCatalog PAINS + BRENK screen, t17;
per-catalog match boolean + matched-alert list + matched-atom substructure + count) and, later, the
``toxicophores`` reactive/tox alert set (t18), plus the cross-cutting generalists (e.g. ADMET-AI's
``PAINS_alert`` / ``BRENK_alert`` / ``NIH_alert`` count shortcuts) that carry
``Endpoint.structural_alerts`` in their registry ``endpoints`` set.

These are **soft** filters (docs IO_SPEC §24): they OVER-flag, so a hit means "look closer", not
auto-kill. The direction is uniform: **more alerts = more flagged**. PAINS in particular matters for
this program because the FTO assay is fluorescence-based, so a PAINS hit is a prompt to check for
readout interference rather than a disqualification. The consuming policy is downstream; the adapters
here only emit the raw counts/flags and the matched substructures.
"""
