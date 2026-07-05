#!/usr/bin/env python
"""sfi adapter - the Solubility Forecast Index rule (solubility endpoint).

Uniform model CLI (CLAUDE.md §2, SETTLED §6):

    python run.py --input <path> --output <path> [--gpu N] [--pka FLOAT]

A CODE-ALGO rule (no weights, no GPU): pure RDKit + arithmetic. It runs in this model's ISOLATED pixi
env (rdkit + python only) and therefore CANNOT import ``core`` (a separate env). So it emits plain JSON
matching the shape of ``core.schemas.OutputRecord``; the dispatcher validates that JSON against the real
schema on collection. The exact keys are documented in ``README.md`` and mirrored here.

Endpoint: solubility. The Solubility Forecast Index (Bhal/GSK; Pat Walters' "Solubility Forecast Index"
blog, the reference Gilson shared):

    SFI = cLogD(7.4) + (#aromatic rings)          -> single float
    endpoint_values = {"SFI": <float>, "cLogD_7.4": <float>, "n_aromatic_rings": <int>}

Direction / units matter (CLAUDE.md §4): SFI is dimensionless and **LOWER = better (more soluble)**. This
inverts vs a generalist solubility model (higher log S = better); the t41 aggregator reconciles the two,
here we just emit SFI faithfully. See README.

Two decided facts this rule must honor:

- **cLogD, not cLogP (flag F-12).** For the di-basic FTO series logP != logD at pH 7.4. cLogD is derived
  from Crippen cLogP (the t10 Wildman-Crippen WLOGP lens) corrected with a pKa via Henderson-Hasselbalch.
  For a base: ``cLogD = cLogP - log10(1 + 10^(pKa - 7.4))``. We do NOT skip the pKa correction.
- **The pKa source is DEFERRED (F-13) and injectable.** BBB Score, CNS MPO, and SFI must all share ONE
  pKa source, which is not yet decided. Until it is, this adapter uses a documented PLACEHOLDER base pKa
  (``PLACEHOLDER_PKA``). It is injectable: ``--pka`` overrides per run, and when F-13 lands (OPERA
  ``pKa_pred`` or one chosen predictor) that source feeds ``--pka`` here. TODO(F-13): swap the placeholder
  for the single shared pKa source. Do NOT treat ``PLACEHOLDER_PKA`` as a decided value.

``--gpu`` is accepted and ignored (``requires_gpu=False``): the uniform CLI is the same for every model so
the dispatcher can build one command, but SFI is pure CPU arithmetic.

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
from rdkit.Chem import Crippen, rdMolDescriptors

MODEL = "sfi"

# --- F-13 DEFERRED: single shared pKa source not yet decided (CLAUDE.md §4a). ---------------------
# Until F-13 lands, cLogD uses this documented PLACEHOLDER base pKa. It is a stand-in, NOT a decision:
# a generic basic-amine value for the di-basic FTO series so the pKa correction is applied (F-12 forbids
# skipping it) rather than silently pinning logD = logP. It is injectable via ``--pka``; when F-13 is
# decided the shared source (OPERA pKa_pred or one chosen predictor) feeds that flag.
# TODO(F-13): replace this placeholder with the single shared pKa source across BBB Score / CNS MPO / SFI.
PLACEHOLDER_PKA = 9.0
PLACEHOLDER_PKA_SOURCE = "placeholder-constant (F-13 DEFERRED; swap for OPERA pKa_pred / one shared predictor)"

PH = 7.4  # SFI is defined at physiological pH 7.4 (the "7.4" in cLogD(7.4)).


def _provenance(pka: float, pka_source: str) -> dict[str, Any]:
    """Provenance stamped onto every emitted record. ``rdkit_version`` is read live, not fabricated.

    The pKa value + its source are stamped so a record is self-describing: a reader can see the cLogD was
    computed with the F-13 placeholder (or an injected value), never guess it.
    """
    return {
        "model": MODEL,
        "method": (
            "SFI = cLogD(7.4) + #aromatic rings; cLogD = Crippen cLogP (Wildman-Crippen 1999 WLOGP lens) "
            "minus a Henderson-Hasselbalch base correction log10(1 + 10^(pKa - 7.4)); "
            "#aromatic rings = rdkit.Chem.rdMolDescriptors.CalcNumAromaticRings"
        ),
        "rdkit_version": rdBase.rdkitVersion,
        "pka": pka,
        "pka_source": pka_source,
        "citation": (
            "Bhal SK et al. Mol Pharm 2007 (SFI concept, GSK); Pat Walters, "
            "\"Solubility Forecast Index\" (practicalcheminformatics blog); Wildman & Crippen, "
            "J Chem Inf Comput Sci 1999, 39(5):868-873 (cLogP)."
        ),
        "license": "BSD-3-Clause (RDKit)",
    }


def clogd_base(clogp: float, pka: float, ph: float = PH) -> float:
    """cLogD at ``ph`` from cLogP for a monoprotic BASE via Henderson-Hasselbalch.

    ``cLogD = cLogP - log10(1 + 10^(pKa - pH))``. For a base the ionized (protonated) fraction grows as pH
    drops below pKa, subtracting from the apparent logD. This is the F-12 correction the FTO di-basic series
    needs; the pKa comes from the injectable (currently placeholder) source, never invented per molecule.
    """
    return clogp - math.log10(1.0 + 10.0 ** (pka - ph))


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

    A rule (deterministic given the injected pKa), so ``uncertainty`` is ``None`` here - the SFI-vs-generalist
    discrepancy the IO spec mentions is computed downstream by the t41 aggregator, not natively by this rule.
    An invalid or empty SMILES returns a valid record with null ``endpoint_values`` and the reason in ``raw``
    rather than raising - the uniform contract's per-record error behavior.
    """
    smiles = str(rec.get("smiles") or "").strip()
    mol_id = rec.get("mol_id")
    base: dict[str, Any] = {"model": MODEL, "uncertainty": None, "provenance": _provenance(pka, pka_source)}

    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return {
            **base,
            "endpoint_values": {"SFI": None, "cLogD_7.4": None, "n_aromatic_rings": None},
            "raw": {
                "error": "RDKit could not parse SMILES (invalid or empty)",
                "smiles": smiles,
                "mol_id": mol_id,
            },
        }

    clogp = float(Crippen.MolLogP(mol))
    clogd = float(clogd_base(clogp, pka))
    n_aromatic = int(rdMolDescriptors.CalcNumAromaticRings(mol))
    sfi = float(clogd + n_aromatic)
    return {
        **base,
        "endpoint_values": {"SFI": sfi, "cLogD_7.4": clogd, "n_aromatic_rings": n_aromatic},
        "raw": {
            "smiles": smiles,
            "mol_id": mol_id,
            "SFI": sfi,
            "cLogD_7.4": clogd,
            "cLogP_crippen": clogp,
            "n_aromatic_rings": n_aromatic,
            "pka": pka,
            "pka_source": pka_source,
            "ph": PH,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Solubility Forecast Index (SFI) rule adapter (uniform model CLI).")
    parser.add_argument("--input", required=True, type=Path, help="pipeline input (InputRecord JSON, JSON array, or .smi)")
    parser.add_argument("--output", required=True, type=Path, help="where to write the OutputRecord JSON")
    parser.add_argument("--gpu", type=int, default=None, help="ignored (sfi is CPU-only); present for the uniform CLI")
    parser.add_argument(
        "--pka",
        type=float,
        default=None,
        help="injectable base pKa for the cLogD correction (F-13). Omitted -> PLACEHOLDER_PKA; the F-13 "
        "shared pKa source will feed this once decided.",
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
