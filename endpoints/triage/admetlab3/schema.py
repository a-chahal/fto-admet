"""Placeholder output schema for the ADMETlab 3.0 adapter (F-6).

The ADMETlab 3.0 ``/api/admetCSV`` response carries **119 endpoints**, each with a predicted
value/probability, an empirical decision-state (coloured-dot category), an uncertainty-estimation score,
and alert-substructure highlights (NAR 2024 paper; IO_SPEC §1 #2). The request/transport contract is
VERIFIED, but the **literal column names** are only knowable from one live ``/api/admetCSV`` call: the
ToxMCP/admetlab-mcp reference wrapper passes the CSV through without enumerating them.

Per the no-fabricate rule (CLAUDE.md §5) we do NOT invent the 119 column names. ``run.py`` parses the CSV
header GENERICALLY (whatever columns come back become ``endpoint_values``), and this module records only
what is DOCUMENTED so a reviewer can see what to expect and what is still owed.

# TODO(F-6): capture the full literal 119-column header from ONE live /api/admetCSV call and freeze it
#           here (KNOWN_COLUMNS), then wire the per-endpoint direction/units + the confidence-flag column
#           map into the aggregators. Until then this stays a placeholder and the task is `needs_aaran`.
"""

from __future__ import annotations

# Head groups CONFIRMED present from the NAR 2024 paper + the ADMETlab 3.0 skeleton match (IO_SPEC §1 #2).
# These are documented CATEGORIES / head families, NOT the verbatim CSV column strings (those are F-6).
KNOWN_TOX_HEADS: tuple[str, ...] = (
    "hERG",            # cardiotox; also feeds the herg endpoint (cross-cutting)
    "nephrotoxicity",
    "neurotoxicity",
    "ototoxicity",
    "hematotoxicity",
    "genotoxicity",
    "RPMI-8226 immunotoxicity",
    "A549 cytotoxicity",
    "HEK293 cytotoxicity",
)

# The documented ADMET category families the 119 endpoints are drawn from (NAR 2024). The registry routes
# this model to these pipeline endpoints: triage, herg, metabolism, distribution, ppb, toxicity, permeability.
KNOWN_CATEGORIES: tuple[str, ...] = (
    "physicochemical",
    "medicinal chemistry",
    "absorption",
    "distribution",
    "metabolism",
    "excretion",
    "toxicity",
    "toxicophore alerts",
)

# The declared endpoint count in the CSV; the number of *columns* is larger (value + decision-state +
# uncertainty score + alert per endpoint) and is captured live, not asserted here.
DECLARED_ENDPOINT_COUNT = 119

# Filled by a live capture (F-6). Empty here on purpose: no fabricated literals.
KNOWN_COLUMNS: tuple[str, ...] = ()

# Uncertainty semantics (VERIFIED): per-endpoint Youden-index high/low-confidence FLAG (binary), not a
# calibrated sigma. run.py routes this into Uncertainty.extra; the per-column flag map is a TODO (F-6).
UNCERTAINTY_KIND = "per-endpoint Youden-index high/low-confidence flag (binary)"
