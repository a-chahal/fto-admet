#!/usr/bin/env python
"""toxicity aggregator - a panel of independent, single-source toxicity features.

Toxicity is not one number: it is a set of unrelated liabilities (organ tox, mutagenicity, the Tox21
nuclear-receptor / stress-response panel, an acute-lethality magnitude, a structural-alert count). Each is
its OWN feature with its OWN source, and nothing here is averaged across features. The bulk automatable
reads come from two models:

    ADMET-AI classifier heads   -> one P(toxic) [0,1] feature per head (DILI, AMES, ClinTox, the Tox21
                                   NR-*/SR-* panel, hERG, carcinogenicity, skin reaction).
    ADMET-AI ``LD50_Zhu``       -> ``acute_ld50``, a MAGNITUDE (log 1/(mol/kg), up = more toxic), never a P.
    toxicophores ``tox_alert_count`` -> ``tox_alerts``, a BRENK structural-alert count (0 = clean).

Every feature is single-source, so ``build_feature`` fills ``score`` from that source (a trained spec, where
one exists, calibrates the value and attaches a conformal interval; otherwise the lone value passes through
with no interval). A feature is emitted ONLY when its source key is present on a supplied record: a molecule
with no ADMET-AI record simply has no probability features (no fabricated zeros). This aggregator runs in the
core env (no box, no GPU), consumes fields already emitted by the contributing models (identified by
``rec.model``, never by folder), and carries NO pass/fail verdict - the decision policy is downstream
(CLAUDE.md §4a). ProTox is a confirmatory web read handled out of this loop (t39 SOP), not read here.
See ``docs/ENDPOINTS.md`` for the fuller rationale.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from core.aggregate import (
    EndpointVerdict,
    Feature,
    MoleculeVerdict,
    Source,
    as_output_record,
    normalize_molecules,
    num,
)
from core.fusion import build_feature
from core.models import Endpoint, ModelName
from core.schemas import OutputRecord

# ADMET-AI classifier heads whose output is directly P(toxic) in [0, 1]. Mapping is
# {canonical feature name: ADMET-AI (TDC) head key in ``endpoint_values``}. Built as a dict so a new head
# is one line and every feature is produced by the same DRY loop below.
ADMET_AI_PROB_HEADS: dict[str, str] = {
    "dili": "DILI",
    "ames_mutagenicity": "AMES",
    "clinical_toxicity": "ClinTox",
    "carcinogenicity": "Carcinogens_Lagunin",
    "skin_reaction": "Skin_Reaction",
    "herg_cardiotox": "hERG",
    "nr_ar": "NR-AR",
    "nr_ar_lbd": "NR-AR-LBD",
    "nr_ahr": "NR-AhR",
    "nr_aromatase": "NR-Aromatase",
    "nr_er": "NR-ER",
    "nr_er_lbd": "NR-ER-LBD",
    "nr_ppar_gamma": "NR-PPAR-gamma",
    "sr_are": "SR-ARE",
    "sr_atad5": "SR-ATAD5",
    "sr_hse": "SR-HSE",
    "sr_mmp": "SR-MMP",
    "sr_p53": "SR-p53",
}

# ADMET-AI acute-lethality MAGNITUDE head (log(1/(mol/kg)), up = more toxic). NOT a probability (F-5).
LD50_FEATURE = "acute_ld50"
LD50_KEY = "LD50_Zhu"
LD50_UNIT = "log(1/(mol/kg)) (up = more acutely toxic)"

# toxicophores (t18) BRENK structural-alert count, with the matched names carried in ``raw``.
TOX_ALERTS_FEATURE = "tox_alerts"
TOX_ALERT_COUNT_KEY = "tox_alert_count"
TOX_ALERTS_UNIT = "count of BRENK tox alerts (0 = clean)"


def _single_feature(endpoint: Endpoint, feature: str, unit: str, sources: list[Source]) -> Feature | None:
    """A single-source feature via ``build_feature`` (trained spec calibrates if present). None if no source."""
    if not sources:
        return None
    return build_feature(endpoint, feature, unit, sources)


def _prob_features(records: Sequence[OutputRecord]) -> list[Feature]:
    """One P(toxic) feature per ADMET-AI classifier head that is present (built from the DRY head dict)."""
    features: list[Feature] = []
    for feature, key in ADMET_AI_PROB_HEADS.items():
        sources = [Source(model="admet_ai", value=v)
                   for rec in records if rec.model == ModelName.admet_ai
                   for v in [num((rec.endpoint_values or {}).get(key))] if v is not None]
        f = _single_feature(Endpoint.toxicity, feature, f"P({feature}) [0,1] (up = more toxic)", sources)
        if f is not None:
            features.append(f)
    return features


def _ld50_feature(records: Sequence[OutputRecord]) -> Feature | None:
    """Acute oral LD50 magnitude (ADMET-AI ``LD50_Zhu``): a scalar read, never a probability (F-5)."""
    sources = [Source(model="admet_ai", value=v)
               for rec in records if rec.model == ModelName.admet_ai
               for v in [num((rec.endpoint_values or {}).get(LD50_KEY))] if v is not None]
    return _single_feature(Endpoint.toxicity, LD50_FEATURE, LD50_UNIT, sources)


def _tox_alerts_feature(records: Sequence[OutputRecord]) -> Feature | None:
    """toxicophores BRENK structural-alert count (the matched names stay upstream in the model's raw record)."""
    sources = [Source(model="toxicophores", value=v)
               for rec in records if rec.model == ModelName.toxicophores
               for v in [num((rec.endpoint_values or {}).get(TOX_ALERT_COUNT_KEY))] if v is not None]
    return _single_feature(Endpoint.toxicity, TOX_ALERTS_FEATURE, TOX_ALERTS_UNIT, sources)


def _molecule(mol_id: str, records: Sequence[Any]) -> MoleculeVerdict:
    recs = [as_output_record(r) for r in records]
    features = _prob_features(recs)
    for f in (_ld50_feature(recs), _tox_alerts_feature(recs)):
        if f is not None:
            features.append(f)
    return MoleculeVerdict(endpoint=Endpoint.toxicity, mol_id=mol_id, features=features)


def aggregate(molecules: Mapping[str, Sequence[Any]] | Sequence[Any]) -> EndpointVerdict:
    """Screen toxicity for a batch: a panel of independent single-source features per molecule.

    Each ADMET-AI classifier head becomes its own P(toxic) feature, ``LD50_Zhu`` becomes ``acute_ld50``
    (a magnitude), and the toxicophores count becomes ``tox_alerts``. A feature appears only when its source
    key is present on a supplied record (no fabricated zeros).
    """
    mols = [_molecule(mid, recs) for mid, recs in normalize_molecules(molecules)]
    return EndpointVerdict(endpoint=Endpoint.toxicity, molecules=mols, n_molecules=len(mols))
