#!/usr/bin/env python
"""rdkit_crippen adapter - the walking-skeleton model and the template every later model copies.

Uniform model CLI (CLAUDE.md §2, SETTLED §6):

    python run.py --input <path> --output <path> [--gpu N]

This runs in the model's ISOLATED pixi env (rdkit + python only) and therefore CANNOT import ``core``
(a separate env). So it emits plain JSON matching the shape of ``core.schemas.OutputRecord``; the
dispatcher validates that JSON against the real schema on collection. The exact keys are documented in
``README.md`` and mirrored here so a later model can copy the shape.

Endpoint: lipophilicity. Emits the Wildman-Crippen logP (``rdkit.Chem.Crippen.MolLogP``) - this is
exactly SwissADME's WLOGP lens, reused by the SwissADME reconstruction (t27) and BOILED-Egg (t16) - and
molar refractivity (``MolMR``):

    endpoint_values = {"logP_crippen": <float, log units, UP = more lipophilic>, "MR": <float>}

Direction / units matter (CLAUDE.md §4): logP is in log units and higher means more lipophilic. logP is
NOT logD (flag F-12): for the di-basic FTO series the logD conversion needs a pKa and is done downstream
with a shared pKa source, never silently here.

``--gpu`` is accepted and ignored (``requires_gpu=False``): the uniform CLI is the same for every model
so the dispatcher can build one command, but Crippen is a pure CPU descriptor.

Robustness: an invalid or unparseable SMILES yields a per-record result with null values and the reason
in ``raw`` - it does not crash the run, so one bad molecule never sinks a bulk batch.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from rdkit import Chem, rdBase
from rdkit.Chem import Crippen

MODEL = "rdkit_crippen"


def _provenance() -> dict[str, Any]:
    """Provenance stamped onto every emitted record. ``rdkit_version`` is read live, not fabricated."""
    return {
        "model": MODEL,
        "method": "rdkit.Chem.Crippen.MolLogP / MolMR (Wildman-Crippen 1999 atom contributions)",
        "rdkit_version": rdBase.rdkitVersion,
        "citation": "Wildman SA, Crippen GM. J Chem Inf Comput Sci 1999, 39(5):868-873.",
        "license": "BSD-3-Clause (RDKit)",
    }


def parse_inputs(text: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse the ``--input`` payload into ``(records, single)``.

    Accepts the three forms the core may feed a model adapter:
    - a single ``InputRecord`` JSON object (what ``dispatch.run_model`` writes) -> ``single=True``,
    - a JSON array of ``InputRecord`` objects (a bulk batch) -> ``single=False``,
    - a ``.smi`` file (``<SMILES><whitespace><title>`` per line, ``#`` comments) -> ``single=False``.

    ``single`` is echoed back so the output mirrors the input arity: one object in -> one object out
    (which the dispatcher validates as a single ``OutputRecord``); a list in -> a list out.
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


def record_for(rec: dict[str, Any]) -> dict[str, Any]:
    """Compute one ``OutputRecord``-shaped dict for a single input record.

    Deterministic descriptor, so ``uncertainty`` is ``None`` (nothing native to report). An invalid or
    empty SMILES returns a valid record with null ``endpoint_values`` and the reason in ``raw`` rather
    than raising - the uniform contract's per-record error behavior.
    """
    smiles = str(rec.get("smiles") or "").strip()
    mol_id = rec.get("mol_id")
    base: dict[str, Any] = {"model": MODEL, "uncertainty": None, "provenance": _provenance()}

    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return {
            **base,
            "endpoint_values": {"logP_crippen": None, "MR": None},
            "raw": {
                "error": "RDKit could not parse SMILES (invalid or empty)",
                "smiles": smiles,
                "mol_id": mol_id,
            },
        }

    logp = float(Crippen.MolLogP(mol))
    mr = float(Crippen.MolMR(mol))
    return {
        **base,
        "endpoint_values": {"logP_crippen": logp, "MR": mr},
        "raw": {"smiles": smiles, "mol_id": mol_id, "logP_crippen": logp, "MR": mr},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RDKit Crippen logP/MR adapter (uniform model CLI).")
    parser.add_argument("--input", required=True, type=Path, help="pipeline input (InputRecord JSON, JSON array, or .smi)")
    parser.add_argument("--output", required=True, type=Path, help="where to write the OutputRecord JSON")
    parser.add_argument("--gpu", type=int, default=None, help="ignored (rdkit_crippen is CPU-only); present for the uniform CLI")
    args = parser.parse_args(argv)

    records, single = parse_inputs(args.input.read_text(encoding="utf-8"))
    outputs = [record_for(rec) for rec in records]
    payload: Any = outputs[0] if (single and len(outputs) == 1) else outputs

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
