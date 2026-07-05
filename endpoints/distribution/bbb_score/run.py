#!/usr/bin/env python
"""bbb_score adapter - the Gupta 2019 BBB Score rule (distribution / BBB / CNS endpoint).

Uniform model CLI (CLAUDE.md §2, SETTLED §6):

    python run.py --input <path> --output <path> [--gpu N] [--pka FLOAT]

A CODE-ALGO rule (no weights, no GPU): pure RDKit + arithmetic. It runs in this model's ISOLATED pixi
env (rdkit + python only) and therefore CANNOT import ``core`` (a separate env). So it emits plain JSON
matching the shape of ``core.schemas.OutputRecord``; the dispatcher validates that JSON against the real
schema on collection. The exact keys are documented in ``README.md`` and mirrored here.

Endpoint: distribution. The BBB Score (Gupta, Lee, Barden, Weaver, J. Med. Chem. 2019, 62(21):9824-9836,
DOI 10.1021/acs.jmedchem.9b01220; AUC 0.86) is a multiparameter passive brain-entry score:

    BBB_Score = P(Aro_R) + P(HA) + 1.5*P(MWHBN) + 2*P(TPSA) + 0.5*P(pKa)   -> single float on 0..6
    endpoint_values = {"BBB_Score": <float 0..6>}

Direction / units matter (CLAUDE.md §4): BBB_Score is dimensionless on a 0-6 scale and **HIGHER = more
likely passive BBB penetrant**. It is a PASSIVE filter only, NOT a brain-exposure prediction and NOT a
gate: the real CNS answer is experimental Kp,uu; BBB penetration is desirable, not required. See README.

The five descriptors (all from RDKit ``rdMolDescriptors``) and the desirability weights are reimplemented
directly from the Gupta paper and unit-tested against the ``gkxiao/BBB-score`` reference port on two
molecules with published scores (acetaminophen 4.43 at pKa 9.89, cinnarizine 5.01 at pKa 8.1), so the
formula is auditable and not a black-box dependency.

The pKa source is DEFERRED (F-13) and injectable:

- **The pKa source is DEFERRED (F-13) and injectable.** BBB Score, CNS MPO, and SFI must all share ONE
  pKa source, which is not yet decided. Until it is, this adapter uses the SAME documented PLACEHOLDER
  base pKa as t13 (SFI) / t15 (CNS MPO) - do NOT diverge per model. It is injectable: ``--pka`` overrides
  per run, and when F-13 lands (OPERA ``pKa_pred`` or one chosen predictor) that source feeds ``--pka``
  here. TODO(F-13): swap the placeholder for the single shared pKa source. Do NOT treat ``PLACEHOLDER_PKA``
  as a decided value.

``--gpu`` is accepted and ignored (``requires_gpu=False``): the uniform CLI is the same for every model so
the dispatcher can build one command, but BBB Score is pure CPU arithmetic.

Robustness: an invalid or unparseable SMILES yields a per-record result with null values and the reason in
``raw`` - it does not crash the run, so one bad molecule never sinks a bulk batch.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from rdkit import Chem, rdBase
from rdkit.Chem import rdMolDescriptors

MODEL = "bbb_score"

# --- F-13 DEFERRED: single shared pKa source not yet decided (CLAUDE.md §4a). ---------------------
# Until F-13 lands, the pKa term uses this documented PLACEHOLDER base pKa. It is a stand-in, NOT a
# decision, and it MUST match t13 (SFI) / t15 (CNS MPO): a generic basic-amine value for the di-basic FTO
# series so the pKa desirability term is scored (the score needs a pKa) rather than dropped. It is
# injectable via ``--pka``; when F-13 is decided the shared source (OPERA pKa_pred or one chosen
# predictor) feeds that flag.
# TODO(F-13): replace this placeholder with the single shared pKa source across BBB Score / CNS MPO / SFI.
PLACEHOLDER_PKA = 9.0
PLACEHOLDER_PKA_SOURCE = "placeholder-constant (F-13 DEFERRED; swap for OPERA pKa_pred / one shared predictor)"


def _provenance(pka: float, pka_source: str) -> dict[str, Any]:
    """Provenance stamped onto every emitted record. ``rdkit_version`` is read live, not fabricated.

    The pKa value + its source are stamped so a record is self-describing: a reader can see the BBB Score
    was computed with the F-13 placeholder (or an injected value), never guess it.
    """
    return {
        "model": MODEL,
        "method": (
            "BBB_Score (Gupta et al. 2019) = P(Aro_R) + P(HA) + 1.5*P(MWHBN) + 2*P(TPSA) + 0.5*P(pKa), "
            "each P a paper desirability transform of an RDKit descriptor: #aromatic rings (stepwise), "
            "heavy atoms (cubic, 5<HA<=45), MWHBN=(nHBA+nHBD)/sqrt(MW) (cubic, 0.05<MWHBN<=0.45), "
            "TPSA (linear, 0<TPSA<=120), most-basic pKa (quartic, 3<pKa<=11); reimplemented from the "
            "paper and matched to the gkxiao/BBB-score port"
        ),
        "rdkit_version": rdBase.rdkitVersion,
        "pka": pka,
        "pka_source": pka_source,
        "citation": (
            "Gupta M, Lee HJ, Barden CJ, Weaver DF. \"The Blood-Brain Barrier (BBB) Score.\" "
            "J Med Chem 2019, 62(21):9824-9836, DOI 10.1021/acs.jmedchem.9b01220. Reference RDKit port: "
            "github.com/gkxiao/BBB-score (also github.com/sailfish009/BBB_calculator)."
        ),
        "license": "BSD-3-Clause (RDKit)",
    }


def p_aromatic_rings(aro_r: int) -> float:
    """Stepwise desirability of the aromatic-ring count (Gupta 2019 Table; matches gkxiao/BBB-score)."""
    table = {0: 0.336367, 1: 0.816016, 2: 1.0, 3: 0.691115, 4: 0.199399}
    return table.get(int(aro_r), 0.0)  # aro_r > 4 (or unexpected) -> 0


def p_heavy_atoms(ha: float) -> float:
    """Cubic desirability of the heavy-atom count on 5 < HA <= 45 (max-normalised); 0 outside the range."""
    if 5 < ha <= 45:
        return (0.0000443 * ha ** 3 - 0.004556 * ha ** 2 + 0.12775 * ha - 0.463) / 0.624231
    return 0.0


def p_mwhbn(mwhbn: float) -> float:
    """Cubic desirability of MWHBN = (nHBA+nHBD)/sqrt(MW) on 0.05 < MWHBN <= 0.45; 0 outside the range."""
    if 0.05 < mwhbn <= 0.45:
        return (26.733 * mwhbn ** 3 - 31.495 * mwhbn ** 2 + 9.5202 * mwhbn - 0.1358) / 0.72258
    return 0.0


def p_tpsa(tpsa: float) -> float:
    """Linear desirability of TPSA on 0 < TPSA <= 120 (max-normalised); 0 outside the range."""
    if 0 < tpsa <= 120:
        return (-0.0067 * tpsa + 0.9598) / 0.9598
    return 0.0


def p_pka(pka: float) -> float:
    """Quartic desirability of the most-basic pKa on 3 < pKa <= 11 (max-normalised); 0 outside the range."""
    if 3 < pka <= 11:
        return (
            0.00045068 * pka ** 4 - 0.016331 * pka ** 3 + 0.18618 * pka ** 2 - 0.71043 * pka + 0.8579
        ) / 0.597488
    return 0.0


def bbb_score(mol: Chem.Mol, pka: float) -> dict[str, Any]:
    """Compute the BBB Score and its component terms for one RDKit molecule and pKa.

    Mirrors the gkxiao/BBB-score reference exactly, including its rounding (MW and MWHBN to 2 decimals),
    so this reimplementation reproduces the published reference scores (auditable, not a black box).
    """
    n_hba = rdMolDescriptors.CalcNumHBA(mol)
    n_hbd = rdMolDescriptors.CalcNumHBD(mol)
    hbn = n_hba + n_hbd
    mw = round(rdMolDescriptors.CalcExactMolWt(mol), 2)
    mwhbn = round(hbn / (mw ** 0.5), 2)
    ha = rdMolDescriptors.CalcNumHeavyAtoms(mol)
    aro_r = rdMolDescriptors.CalcNumAromaticRings(mol)
    tpsa = rdMolDescriptors.CalcTPSA(mol)

    p_aro = p_aromatic_rings(aro_r)
    p_ha = p_heavy_atoms(ha)
    p_mw = p_mwhbn(mwhbn)
    p_ps = p_tpsa(tpsa)
    p_pk = p_pka(pka)
    score = round(p_aro + p_ha + 1.5 * p_mw + 2.0 * p_ps + 0.5 * p_pk, 2)

    return {
        "BBB_Score": float(score),
        "MW": float(mw),
        "nHBA": int(n_hba),
        "nHBD": int(n_hbd),
        "HBN": int(hbn),
        "MWHBN": float(mwhbn),
        "HA": int(ha),
        "n_aromatic_rings": int(aro_r),
        "TPSA": float(tpsa),
        "P_ARO_R": float(p_aro),
        "P_HA": float(p_ha),
        "P_MWHBN": float(p_mw),
        "P_TPSA": float(p_ps),
        "P_PKA": float(p_pk),
    }


def parse_inputs(text: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse the ``--input`` payload into ``(records, single)``.

    Accepts the three forms the core may feed a model adapter (same as the t10 template):
    - a single ``InputRecord`` JSON object (what ``dispatch.run_model`` writes) -> ``single=True``,
    - a JSON array of ``InputRecord`` objects (a bulk batch) -> ``single=False``,
    - a ``.smi`` file (``<SMILES><whitespace><title>`` per line, ``#`` comments) -> ``single=False``.

    ``single`` is echoed back so the output mirrors the input arity: one object in -> one object out.
    """
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        data = json.loads(stripped)
        if isinstance(data, dict):
            return [data], True
        if isinstance(data, list):
            return list(data), False
        raise ValueError("input JSON must be an object or an array of objects")

    records: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        mol_id = parts[1] if len(parts) > 1 else None
        records.append({"smiles": parts[0], "mol_id": mol_id})
    return records, False


def record_for(rec: dict[str, Any], pka: float, pka_source: str) -> dict[str, Any]:
    """Compute one ``OutputRecord``-shaped dict for a single input record.

    A rule (deterministic given the injected pKa), so ``uncertainty`` is ``None``. An invalid or empty
    SMILES returns a valid record with null ``endpoint_values`` and the reason in ``raw`` rather than
    raising - the uniform contract's per-record error behavior, so one bad molecule never sinks a batch.
    """
    smiles = str(rec.get("smiles") or "").strip()
    mol_id = rec.get("mol_id")
    base: dict[str, Any] = {"model": MODEL, "uncertainty": None, "provenance": _provenance(pka, pka_source)}

    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return {
            **base,
            "endpoint_values": {"BBB_Score": None},
            "raw": {
                "error": "RDKit could not parse SMILES (invalid or empty)",
                "smiles": smiles,
                "mol_id": mol_id,
            },
        }

    terms = bbb_score(mol, pka)
    return {
        **base,
        "endpoint_values": {"BBB_Score": terms["BBB_Score"]},
        "raw": {
            "smiles": smiles,
            "mol_id": mol_id,
            "pka": pka,
            "pka_source": pka_source,
            **terms,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BBB Score (Gupta 2019) rule adapter (uniform model CLI).")
    parser.add_argument("--input", required=True, type=Path, help="pipeline input (InputRecord JSON, JSON array, or .smi)")
    parser.add_argument("--output", required=True, type=Path, help="where to write the OutputRecord JSON")
    parser.add_argument("--gpu", type=int, default=None, help="ignored (bbb_score is CPU-only); present for the uniform CLI")
    parser.add_argument(
        "--pka",
        type=float,
        default=None,
        help="injectable most-basic pKa for the BBB Score pKa term (F-13). Omitted -> PLACEHOLDER_PKA; the "
        "F-13 shared pKa source (same as t13/t15) will feed this once decided.",
    )
    args = parser.parse_args(argv)

    if args.pka is None:
        pka, pka_source = PLACEHOLDER_PKA, PLACEHOLDER_PKA_SOURCE
    else:
        pka, pka_source = args.pka, "injected via --pka"

    records, single = parse_inputs(args.input.read_text(encoding="utf-8"))
    outputs = [record_for(rec, pka, pka_source) for rec in records]
    payload: Any = outputs[0] if (single and len(outputs) == 1) else outputs

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
