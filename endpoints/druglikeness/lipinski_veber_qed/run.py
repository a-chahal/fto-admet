#!/usr/bin/env python
"""lipinski_veber_qed adapter - drug-likeness context rule (druglikeness endpoint).

Uniform model CLI (CLAUDE.md §2, SETTLED §6):

    python run.py --input <path> --output <path> [--gpu N]

A CODE-PKG rule (no weights, no GPU): pure RDKit descriptors + ``rdkit.Chem.QED``. It runs in this
model's ISOLATED pixi env (rdkit + python only) and therefore CANNOT import ``core`` (a separate env).
So it emits plain JSON matching the shape of ``core.schemas.OutputRecord``; the dispatcher validates that
JSON against the real schema on collection. The exact keys are documented in ``README.md`` and mirrored
here.

Endpoint: druglikeness. Emits three context flags (docs IO_SPEC §30):

    endpoint_values = {
        "Lipinski_violations": <int 0-4; fewer = more drug-like>,
        "Veber_pass": <bool; pass = more drug-like>,
        "QED": <float 0-1; UP = more drug-like>,
    }

Definitions (docs §30, fixed here so a downstream reader never re-derives them):
- **Lipinski Ro5 violations** (Lipinski 2001): count of the four rules VIOLATED - MW > 500, HBD > 5,
  HBA > 10, MolLogP > 5. So 0 = passes all four, 4 = fails all four; **fewer violations = more
  drug-like**. (Reported as the violation *count*, the "int 0-4" sense in docs §30, not the pass bool.)
- **Veber pass** (Veber 2002): ``RotatableBonds <= 10 AND TPSA <= 140`` -> True; **pass = more
  drug-like**.
- **QED** (Bickerton et al. 2012): ``rdkit.Chem.QED.qed(mol)``, a 0-1 quantitative estimate of
  drug-likeness; **higher = more drug-like**.

**Context / POINTER only - NOT a gate** (the landmine, docs §30 / task t19). These are run for the lab's
sanity check; the druglikeness aggregator (t50) reports them as flags and never turns a violation into a
kill. Many marketed drugs violate Ro5. This adapter only emits the raw flags + the underlying descriptors
(in ``raw``); no promotion / kill logic lives here.

Crippen note (flag F-12): the logP used for the Ro5 lipophilicity rule is the Wildman-Crippen ``MolLogP``
(``Descriptors.MolLogP``), the same lens as ``rdkit_crippen`` (t10). It is logP, NOT logD; the di-basic
FTO logD conversion needs a shared pKa and is done downstream, never silently here.

``--gpu`` is accepted and ignored (``requires_gpu=False``): the uniform CLI is identical for every model
so the dispatcher can build one command, but these are pure CPU descriptors.

Robustness: an invalid or unparseable SMILES yields a per-record result with null endpoint values and the
reason in ``raw`` - it does not crash the run, so one bad molecule never sinks a bulk batch.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from rdkit import Chem, rdBase
from rdkit.Chem import QED, Crippen, Descriptors

MODEL = "lipinski_veber_qed"

# Lipinski Ro5 thresholds (Lipinski 2001) and Veber thresholds (Veber 2002). Kept as named constants so
# the exact cutoffs and their sense are auditable and never re-derived downstream.
RO5_MW_MAX = 500.0
RO5_HBD_MAX = 5
RO5_HBA_MAX = 10
RO5_LOGP_MAX = 5.0
VEBER_ROTB_MAX = 10
VEBER_TPSA_MAX = 140.0


def _provenance() -> dict[str, Any]:
    """Provenance stamped onto every emitted record. ``rdkit_version`` is read live, not fabricated."""
    return {
        "model": MODEL,
        "method": (
            "RDKit drug-likeness context rule. Lipinski Ro5 violation count (Descriptors.MolWt, "
            "Lipinski.NumHDonors, Lipinski.NumHAcceptors, Descriptors.MolLogP/Crippen vs MW<=500, "
            "HBD<=5, HBA<=10, logP<=5); Veber pass (Descriptors.NumRotatableBonds<=10 and "
            "Descriptors.TPSA<=140); QED (rdkit.Chem.QED.qed). Context / POINTER only, not a gate: "
            "fewer violations = more drug-like, Veber pass = more drug-like, higher QED = more "
            "drug-like."
        ),
        "rdkit_version": rdBase.rdkitVersion,
        "citation": (
            "Lipinski CA et al. Adv Drug Deliv Rev 2001, 46(1-3):3-26 (Rule of 5); Veber DF et al. "
            "J Med Chem 2002, 45(12):2615-2623 (rotatable bonds / TPSA); Bickerton GR et al. Nat Chem "
            "2012, 4(2):90-98 (QED). Descriptors as implemented in RDKit."
        ),
        "license": "BSD-3-Clause (RDKit)",
    }


def _descriptors(mol: Chem.Mol) -> dict[str, Any]:
    """Compute the six raw RDKit descriptors the three flags are derived from (docs §30 input contract)."""
    return {
        "MW": float(Descriptors.MolWt(mol)),
        "HBD": int(Descriptors.NumHDonors(mol)),
        "HBA": int(Descriptors.NumHAcceptors(mol)),
        "RotB": int(Descriptors.NumRotatableBonds(mol)),
        "TPSA": float(Descriptors.TPSA(mol)),
        "logP": float(Crippen.MolLogP(mol)),  # Wildman-Crippen, same lens as rdkit_crippen (t10)
    }


def _lipinski_violations(d: dict[str, Any]) -> int:
    """Count the Ro5 rules VIOLATED (0-4); fewer = more drug-like (docs §30)."""
    return int(
        (d["MW"] > RO5_MW_MAX)
        + (d["HBD"] > RO5_HBD_MAX)
        + (d["HBA"] > RO5_HBA_MAX)
        + (d["logP"] > RO5_LOGP_MAX)
    )


def _veber_pass(d: dict[str, Any]) -> bool:
    """Veber: RotB <= 10 AND TPSA <= 140 -> pass; pass = more drug-like (docs §30)."""
    return bool(d["RotB"] <= VEBER_ROTB_MAX and d["TPSA"] <= VEBER_TPSA_MAX)


def parse_inputs(text: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse the ``--input`` payload into ``(records, single)``.

    Accepts the three forms the core may feed a model adapter (same as the t10 template):
    - a single ``InputRecord`` JSON object (what ``dispatch.run_model`` writes) -> ``single=True``,
    - a JSON array of ``InputRecord`` objects (a bulk batch) -> ``single=False``,
    - a ``.smi`` file (``<SMILES><whitespace><title>`` per line, ``#`` comments) -> ``single=False``.

    ``single`` is echoed back so the output mirrors the input arity: one object in -> one object out.

    JSON is detected by *trying to parse it*, not by a leading-character heuristic: a ``.smi`` line can
    legitimately begin with ``[`` (a bracket atom, e.g. ``[O-]``, ``[nH]``, ``[N+]``), which a naive
    "starts with ``[`` -> JSON" test would misread as a JSON array. A ``{``/``[``-leading payload is
    parsed as JSON; anything that is not valid JSON falls back to ``.smi`` line parsing.
    """
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            data = None  # not JSON after all (e.g. a .smi whose first SMILES is a bracket atom)
        if isinstance(data, dict):
            return [data], True
        if isinstance(data, list):
            return list(data), False
        if data is not None:
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


def record_for(rec: dict[str, Any]) -> dict[str, Any]:
    """Compute one ``OutputRecord``-shaped dict for a single input record.

    A rule (deterministic), so ``uncertainty`` is ``None``. ``endpoint_values`` carries the three scalar
    context flags (``Lipinski_violations``, ``Veber_pass``, ``QED``); the six underlying descriptors live
    in ``raw`` (auditable, non-scalar-policy, per CLAUDE.md §3 / the schema note). An invalid or empty
    SMILES returns a valid record with null values and the reason in ``raw`` rather than raising.
    """
    smiles = str(rec.get("smiles") or "").strip()
    mol_id = rec.get("mol_id")
    base: dict[str, Any] = {"model": MODEL, "uncertainty": None, "provenance": _provenance()}

    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return {
            **base,
            "endpoint_values": {"Lipinski_violations": None, "Veber_pass": None, "QED": None},
            "raw": {
                "error": "RDKit could not parse SMILES (invalid or empty)",
                "smiles": smiles,
                "mol_id": mol_id,
            },
        }

    d = _descriptors(mol)
    violations = _lipinski_violations(d)
    veber = _veber_pass(d)
    qed = float(QED.qed(mol))
    return {
        **base,
        "endpoint_values": {
            "Lipinski_violations": violations,
            "Veber_pass": veber,
            "QED": qed,
        },
        "raw": {
            "smiles": smiles,
            "mol_id": mol_id,
            "descriptors": d,  # MW, HBD, HBA, RotB, TPSA, logP - the six the flags are derived from
            "Lipinski_thresholds": {"MW": RO5_MW_MAX, "HBD": RO5_HBD_MAX, "HBA": RO5_HBA_MAX, "logP": RO5_LOGP_MAX},
            "Veber_thresholds": {"RotB": VEBER_ROTB_MAX, "TPSA": VEBER_TPSA_MAX},
            "context_only": True,  # POINTER / not a gate (docs §30, task t19)
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Drug-likeness context rule (RDKit Lipinski / Veber / QED) - uniform model CLI."
    )
    parser.add_argument("--input", required=True, type=Path, help="pipeline input (InputRecord JSON, JSON array, or .smi)")
    parser.add_argument("--output", required=True, type=Path, help="where to write the OutputRecord JSON")
    parser.add_argument("--gpu", type=int, default=None, help="ignored (lipinski_veber_qed is CPU-only); present for the uniform CLI")
    args = parser.parse_args(argv)

    records, single = parse_inputs(args.input.read_text(encoding="utf-8"))
    outputs = [record_for(rec) for rec in records]
    payload: Any = outputs[0] if (single and len(outputs) == 1) else outputs

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
