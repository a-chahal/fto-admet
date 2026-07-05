#!/usr/bin/env python
"""cns_mpo adapter - the Wager CNS MPO rule (distribution / BBB / CNS endpoint).

Uniform model CLI (CLAUDE.md §2, SETTLED §6):

    python run.py --input <path> --output <path> [--gpu N] [--pka FLOAT]

A CODE-ALGO rule (no weights, no GPU): pure RDKit + arithmetic. It runs in this model's ISOLATED pixi
env (rdkit + python only) and therefore CANNOT import ``core`` (a separate env). So it emits plain JSON
matching the shape of ``core.schemas.OutputRecord``; the dispatcher validates that JSON against the real
schema on collection. The exact keys are documented in ``README.md`` and mirrored here.

Endpoint: distribution. The CNS MPO (Central Nervous System Multiparameter Optimization; Wager et al.,
ACS Chem. Neurosci. 2010, 1(6):435-449, DOI 10.1021/cn100008c, updated 2016, DOI 10.1021/acschemneuro.6b00029)
is the sum of six physicochemical desirability transforms:

    CNS_MPO = D(MW) + D(cLogP) + D(cLogD) + D(HBD) + D(pKa) + D(TPSA)   -> single float on 0..6

Each ``D(x)`` maps one descriptor to a desirability in [0, 1] with EQUAL weight, so the six-term sum
spans 0..6. Five transforms are monotonic decreasing (MW, cLogP, cLogD, HBD, most-basic pKa: smaller is
more CNS-desirable); TPSA is HUMP-shaped (a mid-range window is best). The published Wager 2010 inflection
points (score 1.0 -> score 0.0), the same numbers every reference port uses:

    MW    : 1.0 at <=360,  0.0 at >=500     (monotonic decreasing)
    cLogP : 1.0 at <=3.0,  0.0 at >=5.0      (monotonic decreasing)
    cLogD : 1.0 at <=2.0,  0.0 at >=4.0      (monotonic decreasing)
    HBD   : 1.0 at <=0.5,  0.0 at >=3.5      (monotonic decreasing)
    pKa   : 1.0 at <=8.0,  0.0 at >=10.0     (monotonic decreasing, most-basic center)
    TPSA  : 0.0 at <=20, ramps to 1.0 at 40, plateau 1.0 to 90, ramps to 0.0 at >=120  (hump)

Direction / units matter (CLAUDE.md §4): CNS_MPO is dimensionless on a fixed 0-6 scale and
**HIGHER = more CNS-desirable** (Wager 2010; drugs with MPO >= 4 are enriched among marketed CNS drugs).
It is a ROUGH filter only, NOT a gate: it is weak on the harder PET-tracer set (AUC 0.53) and sits on an
incompatible scale from the other distribution signals (F-4), reconciled ordinally at t42, never averaged.

Two decided facts this rule must honor (shared with t13 SFI / t14 BBB Score):

- **cLogD, not cLogP, for the D(cLogD) term (flag F-12).** For the di-basic FTO series logP != logD at
  pH 7.4. cLogD is derived from Crippen cLogP (the t10 Wildman-Crippen WLOGP lens) corrected with a pKa
  via Henderson-Hasselbalch: for a base ``cLogD = cLogP - log10(1 + 10^(pKa - 7.4))``. Not skipped.
- **The pKa source is DEFERRED (F-13) and injectable.** BBB Score, CNS MPO, and SFI must all share ONE
  pKa source, which is not yet decided. Until it is, this adapter uses the SAME documented PLACEHOLDER
  base pKa as t13 (SFI) / t14 (BBB Score) - do NOT diverge per model. It feeds BOTH the D(pKa) term and
  the cLogD correction. It is injectable: ``--pka`` overrides per run, and when F-13 lands (OPERA
  ``pKa_pred`` or one chosen predictor) that source feeds ``--pka`` here. TODO(F-13): swap the placeholder
  for the single shared pKa source. Do NOT treat ``PLACEHOLDER_PKA`` as a decided value.

``--gpu`` is accepted and ignored (``requires_gpu=False``): the uniform CLI is the same for every model so
the dispatcher can build one command, but CNS MPO is pure CPU arithmetic.

Robustness: an invalid or unparseable SMILES yields a per-record result with null values and the reason in
``raw`` - it does not crash the run, so one bad molecule never sinks a bulk batch.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from rdkit import Chem, rdBase
from rdkit.Chem import Crippen, Descriptors, rdMolDescriptors

MODEL = "cns_mpo"

# --- F-13 DEFERRED: single shared pKa source not yet decided (CLAUDE.md §4a). ---------------------
# Until F-13 lands, the D(pKa) term AND the cLogD correction use this documented PLACEHOLDER base pKa.
# It is a stand-in, NOT a decision: a generic basic-amine value for the di-basic FTO series so the pKa
# terms are scored rather than dropped/pinned. It MUST match t13 (SFI) / t14 (BBB Score) - the three
# rules are internally comparable only if the pKa is identical. Injectable via ``--pka``; when F-13 is
# decided the shared source (OPERA pKa_pred or one chosen predictor) feeds that flag.
# TODO(F-13): replace this placeholder with the single shared pKa source across BBB Score / CNS MPO / SFI.
PLACEHOLDER_PKA = 9.0
PLACEHOLDER_PKA_SOURCE = "placeholder-constant (F-13 DEFERRED; swap for OPERA pKa_pred / one shared predictor)"

PH = 7.4  # cLogD is evaluated at physiological pH 7.4 (the "cLogD(7.4)" the CNS MPO uses).


def _provenance(pka: float, pka_source: str) -> dict[str, Any]:
    """Provenance stamped onto every emitted record. ``rdkit_version`` is read live, not fabricated.

    The pKa value + its source are stamped so a record is self-describing: a reader can see the CNS MPO
    was computed with the F-13 placeholder (or an injected value), never guess it.
    """
    return {
        "model": MODEL,
        "method": (
            "CNS_MPO (Wager et al. 2010/2016) = D(MW) + D(cLogP) + D(cLogD) + D(HBD) + D(pKa) + D(TPSA), "
            "each D a paper desirability transform to [0,1] with equal weight: MW/cLogP/cLogD/HBD/pKa "
            "monotonic-decreasing (inflections 360/500, 3/5, 2/4, 0.5/3.5, 8/10), TPSA hump (0 at <=20, "
            "1 on 40-90, 0 at >=120). cLogP = Crippen MolLogP (Wildman-Crippen 1999 WLOGP lens); "
            "cLogD = cLogP - log10(1 + 10^(pKa - 7.4)) (Henderson-Hasselbalch base correction, F-12); "
            "MW = rdkit Descriptors.MolWt (average); HBD = CalcNumHBD; TPSA = CalcTPSA (Ertl); "
            "most-basic pKa injected (F-13 placeholder)"
        ),
        "rdkit_version": rdBase.rdkitVersion,
        "pka": pka,
        "pka_source": pka_source,
        "citation": (
            "Wager TT, Hou X, Verhoest PR, Villalobos A. \"Moving beyond Rules: The Development of a "
            "Central Nervous System Multiparameter Optimization (CNS MPO) Approach.\" ACS Chem Neurosci "
            "2010, 1(6):435-449, DOI 10.1021/cn100008c; update ACS Chem Neurosci 2016, 7(6):767-775, "
            "DOI 10.1021/acschemneuro.6b00029. Reference port: github.com/Adam-maz/CNS_MPO_calculator."
        ),
        "license": "BSD-3-Clause (RDKit)",
    }


def desirability_decreasing(x: float, one_below: float, zero_above: float) -> float:
    """Monotonic-decreasing desirability: 1.0 at ``x <= one_below``, linear to 0.0 at ``x >= zero_above``.

    The Wager transform for the five "smaller is better" properties (MW, cLogP, cLogD, HBD, pKa). Between
    the two inflection points the score falls linearly; outside them it is clamped to 1.0 / 0.0.
    """
    if x <= one_below:
        return 1.0
    if x >= zero_above:
        return 0.0
    return (zero_above - x) / (zero_above - one_below)


def desirability_tpsa(tpsa: float) -> float:
    """Hump-shaped TPSA desirability (Wager 2010): a mid-range polar-surface window is most CNS-desirable.

    0.0 at ``TPSA <= 20``, ramps linearly to 1.0 at ``TPSA = 40``, plateau 1.0 across 40..90, ramps back
    down to 0.0 at ``TPSA >= 120``. Swapping the ramp direction would silently invert the term.
    """
    if tpsa <= 20.0 or tpsa >= 120.0:
        return 0.0
    if tpsa < 40.0:
        return (tpsa - 20.0) / (40.0 - 20.0)
    if tpsa <= 90.0:
        return 1.0
    return (120.0 - tpsa) / (120.0 - 90.0)


def clogd_base(clogp: float, pka: float, ph: float = PH) -> float:
    """cLogD at ``ph`` from cLogP for a monoprotic BASE via Henderson-Hasselbalch (same as t13 SFI).

    ``cLogD = cLogP - log10(1 + 10^(pKa - pH))``. For a base the ionized (protonated) fraction grows as pH
    drops below pKa, subtracting from the apparent logD. This is the F-12 correction the FTO di-basic series
    needs; the pKa comes from the injectable (currently placeholder) source, never invented per molecule.
    """
    return clogp - math.log10(1.0 + 10.0 ** (pka - ph))


def cns_mpo(mol: Chem.Mol, pka: float) -> dict[str, Any]:
    """Compute the CNS MPO and its six component desirabilities for one RDKit molecule and pKa.

    Returns the score, the six raw descriptors, and the six D(*) desirabilities (each in [0,1]); the score
    is exactly their sum, so a reader can reconstruct and audit it.
    """
    mw = float(Descriptors.MolWt(mol))
    clogp = float(Crippen.MolLogP(mol))
    clogd = float(clogd_base(clogp, pka))
    hbd = int(rdMolDescriptors.CalcNumHBD(mol))
    tpsa = float(rdMolDescriptors.CalcTPSA(mol))

    d_mw = desirability_decreasing(mw, 360.0, 500.0)
    d_clogp = desirability_decreasing(clogp, 3.0, 5.0)
    d_clogd = desirability_decreasing(clogd, 2.0, 4.0)
    d_hbd = desirability_decreasing(hbd, 0.5, 3.5)
    d_pka = desirability_decreasing(pka, 8.0, 10.0)
    d_tpsa = desirability_tpsa(tpsa)
    score = d_mw + d_clogp + d_clogd + d_hbd + d_pka + d_tpsa

    return {
        "CNS_MPO": float(score),
        "MW": float(mw),
        "cLogP_crippen": float(clogp),
        "cLogD_7.4": float(clogd),
        "nHBD": int(hbd),
        "TPSA": float(tpsa),
        "D_MW": float(d_mw),
        "D_cLogP": float(d_clogp),
        "D_cLogD": float(d_clogd),
        "D_HBD": float(d_hbd),
        "D_pKa": float(d_pka),
        "D_TPSA": float(d_tpsa),
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
            "endpoint_values": {"CNS_MPO": None},
            "raw": {
                "error": "RDKit could not parse SMILES (invalid or empty)",
                "smiles": smiles,
                "mol_id": mol_id,
            },
        }

    terms = cns_mpo(mol, pka)
    return {
        **base,
        "endpoint_values": {"CNS_MPO": terms["CNS_MPO"]},
        "raw": {
            "smiles": smiles,
            "mol_id": mol_id,
            "pka": pka,
            "pka_source": pka_source,
            "ph": PH,
            **terms,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CNS MPO (Wager 2010/2016) rule adapter (uniform model CLI).")
    parser.add_argument("--input", required=True, type=Path, help="pipeline input (InputRecord JSON, JSON array, or .smi)")
    parser.add_argument("--output", required=True, type=Path, help="where to write the OutputRecord JSON")
    parser.add_argument("--gpu", type=int, default=None, help="ignored (cns_mpo is CPU-only); present for the uniform CLI")
    parser.add_argument(
        "--pka",
        type=float,
        default=None,
        help="injectable most-basic pKa for the D(pKa) term and the cLogD correction (F-13). Omitted -> "
        "PLACEHOLDER_PKA; the F-13 shared pKa source (same as t13/t14) will feed this once decided.",
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
