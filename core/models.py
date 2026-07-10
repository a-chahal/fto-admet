"""The two enums that are the primary keys of the whole pipeline (CLAUDE.md §2).

``Endpoint`` names the screening endpoints an aggregator can be asked to run; ``ModelName`` names
each adapter that produces predictions. ``registry``, ``dispatch``, and every ``aggregate.py`` key off
these members, so the *values* are a stable contract: each member's value is its lowercased name, and
membership by string works (``ModelName("pksmart") is ModelName.pksmart``). Both are ``StrEnum`` so a
member compares equal to and serializes as its plain string.

Counts are fixed and load-bearing: exactly 13 endpoints and 26 model names (SETTLED §5). A wrong
count or a dropped/renamed member surfaces later as a registry or aggregator mismatch. Permeability is
aggregate-only and has no ``ModelName``. The dropped/replaced upstreams (deephit, spielvogel,
cardiodpi, fame3; CLAUDE.md §4) are intentionally absent.
"""

from __future__ import annotations

from enum import StrEnum


class Endpoint(StrEnum):
    """A screening endpoint an aggregator collects models for (SETTLED §5). 13 members, no more."""

    triage = "triage"
    herg = "herg"
    metabolism = "metabolism"
    clearance = "clearance"
    distribution = "distribution"
    ppb = "ppb"
    solubility = "solubility"
    lipophilicity = "lipophilicity"
    permeability = "permeability"  # aggregate-only: no ModelName maps to it
    structural_alerts = "structural_alerts"
    synthesizability = "synthesizability"
    toxicity = "toxicity"
    druglikeness = "druglikeness"


class ModelName(StrEnum):
    """One member per model adapter, the registry's primary key (CLAUDE.md §2). 26 members, no more."""

    admet_ai = "admet_ai"
    bayesherg = "bayesherg"
    cardiotox_net = "cardiotox_net"
    cardiogenai = "cardiogenai"
    smartcyp = "smartcyp"
    fame3r = "fame3r"
    watanabe_renal = "watanabe_renal"
    pksmart = "pksmart"
    pbpk = "pbpk"
    bbb_score = "bbb_score"
    boiled_egg = "boiled_egg"
    cns_mpo = "cns_mpo"
    pgp = "pgp"
    watanabe_pgp_brain = "watanabe_pgp_brain"
    ochem_ppb = "ochem_ppb"
    sfi = "sfi"
    rdkit_crippen = "rdkit_crippen"
    opera = "opera"
    swissadme = "swissadme"
    pains_brenk = "pains_brenk"
    sascore = "sascore"
    rascore = "rascore"
    aizynthfinder = "aizynthfinder"
    toxicophores = "toxicophores"
    protox = "protox"
    lipinski_veber_qed = "lipinski_veber_qed"
