#!/usr/bin/env python
"""sascore adapter - synthetic-accessibility score (synthesizability endpoint).

Uniform model CLI (CLAUDE.md §2, SETTLED §6):

    python run.py --input <path> --output <path> [--gpu N]

A CODE-PKG rule (no weights, no GPU) built on the **RDKit Contrib** ``sascorer.py`` (Ertl &
Schuffenhauer 2009). ``sascorer.py`` + ``fpscores.pkl.gz`` are NOT part of the importable ``rdkit``
package: they live in ``$RDBASE/Contrib/SA_Score`` and are **vendored** into ``vendor/`` (see README
provenance). This adapter prepends ``vendor/`` to ``sys.path`` and calls ``sascorer.calculateScore``.

It runs in this model's ISOLATED pixi env (rdkit + python only) and therefore CANNOT import ``core`` (a
separate env). So it emits plain JSON matching the shape of ``core.schemas.OutputRecord``; the
dispatcher validates that JSON against the real schema on collection. The exact keys are documented in
``README.md`` and mirrored here.

Endpoint: synthesizability. Emits one scalar (docs IO_SPEC §25):

    endpoint_values = {"SAscore": <float on 1..10>}

Direction (docs §25, the landmine - fixed here so a downstream reader never re-derives it):
- **SAscore** (``sascorer.calculateScore(mol)``): a synthetic-accessibility estimate on **1-10**;
  **LOWER = easier to synthesize**, higher = harder. This inverts the "higher = better" intuition. It is
  the **first rung** of the synthesizability tier ladder (SAscore -> RAscore -> AiZynthFinder, docs §2 /
  the t48 aggregator); the rungs have different scales and are reported as a tier, never averaged.

``uncertainty`` is ``None``: the score is a deterministic function of the molecular graph.

``--gpu`` is accepted and ignored (``requires_gpu=False``): the uniform CLI is identical for every model
so the dispatcher can build one command, but this is a pure CPU fragment-score lookup.

Robustness: an invalid or unparseable SMILES yields a per-record result with a null ``SAscore`` and the
reason in ``raw`` - it does not crash the run, so one bad molecule never sinks a bulk batch.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from rdkit import Chem, rdBase

# The RDKit-Contrib SA_Score files (sascorer.py + fpscores.pkl.gz) are vendored here, NOT pip-installed
# (they are not part of the importable rdkit package). Prepend vendor/ so `import sascorer` resolves to
# the vendored module; sascorer reads fpscores.pkl.gz from its own __file__ dir, i.e. this same vendor/.
VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
if str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))

import sascorer  # noqa: E402  (import after sys.path is set - vendored RDKit Contrib module)

MODEL = "sascore"

# SAscore is defined on this closed interval by Ertl & Schuffenhauer 2009; kept as named constants so the
# range and its sense (LOWER = easier) are auditable and never re-derived downstream.
SASCORE_MIN = 1.0
SASCORE_MAX = 10.0


def _provenance() -> dict[str, Any]:
    """Provenance stamped onto every emitted record. ``rdkit_version`` is read live, not fabricated."""
    return {
        "model": MODEL,
        "method": (
            "Synthetic-accessibility score via the RDKit Contrib sascorer.calculateScore(mol) "
            "(Ertl & Schuffenhauer 2009): a fragment-contribution score (fpscores.pkl.gz) plus a "
            "complexity penalty, mapped onto 1-10. LOWER = easier to synthesize, higher = harder. "
            "First rung of the synthesizability tier ladder (SAscore -> RAscore -> AiZynthFinder); "
            "reported as a tier, never averaged with the other rungs."
        ),
        "rdkit_version": rdBase.rdkitVersion,
        "citation": (
            "Ertl P, Schuffenhauer A. Estimation of synthetic accessibility score of drug-like "
            "molecules based on molecular complexity and fragment contributions. J Cheminform 2009, "
            "1:8. Implementation: RDKit Contrib/SA_Score (sascorer.py + fpscores.pkl.gz)."
        ),
        "license": "BSD-3-Clause (RDKit Contrib)",
    }


def parse_inputs(text: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse the ``--input`` payload into ``(records, single)``.

    Accepts the three forms the core may feed a model adapter (same as the t10/t19 template):
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

    A rule (deterministic), so ``uncertainty`` is ``None``. ``endpoint_values`` carries the single scalar
    ``SAscore`` (float on 1-10, lower = easier). An invalid or empty SMILES returns a valid record with a
    null value and the reason in ``raw`` rather than raising.
    """
    smiles = str(rec.get("smiles") or "").strip()
    mol_id = rec.get("mol_id")
    base: dict[str, Any] = {"model": MODEL, "uncertainty": None, "provenance": _provenance()}

    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return {
            **base,
            "endpoint_values": {"SAscore": None},
            "raw": {
                "error": "RDKit could not parse SMILES (invalid or empty)",
                "smiles": smiles,
                "mol_id": mol_id,
            },
        }

    sascore = float(sascorer.calculateScore(mol))
    return {
        **base,
        "endpoint_values": {"SAscore": sascore},
        "raw": {
            "smiles": smiles,
            "mol_id": mol_id,
            "scale": {"min": SASCORE_MIN, "max": SASCORE_MAX, "direction": "lower = easier to synthesize"},
            "tier": "synthesizability rung 1 of 3 (SAscore -> RAscore -> AiZynthFinder)",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Synthetic-accessibility score (RDKit Contrib SA_Score, Ertl & Schuffenhauer 2009) - uniform model CLI."
    )
    parser.add_argument("--input", required=True, type=Path, help="pipeline input (InputRecord JSON, JSON array, or .smi)")
    parser.add_argument("--output", required=True, type=Path, help="where to write the OutputRecord JSON")
    parser.add_argument("--gpu", type=int, default=None, help="ignored (sascore is CPU-only); present for the uniform CLI")
    args = parser.parse_args(argv)

    records, single = parse_inputs(args.input.read_text(encoding="utf-8"))
    outputs = [record_for(rec) for rec in records]
    payload: Any = outputs[0] if (single and len(outputs) == 1) else outputs

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
