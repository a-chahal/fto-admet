#!/usr/bin/env python
"""boiled_egg adapter - the BOILED-Egg rule (distribution + permeability, ONE impl, two endpoints).

Uniform model CLI (CLAUDE.md §2, SETTLED §6):

    python run.py --input <path> --output <path> [--gpu N]

A CODE-ALGO rule (no weights, no GPU): pure RDKit + a point-in-polygon test. It runs in this model's
ISOLATED pixi env (rdkit + python only) and therefore CANNOT import ``core`` (a separate env). So it
emits plain JSON matching the shape of ``core.schemas.OutputRecord``; the dispatcher validates that JSON
against the real schema on collection. The exact keys are documented in ``README.md`` and mirrored here.

Mechanism (Daina & Zoete, ChemMedChem 2016, DOI 10.1002/cmdc.201600182; VERIFIED against the working
open implementation bfmilne/pyBOILEDegg): the "BOILED-Egg" is two closed regions in a 2-D physicochemical
plane whose axes are **x = TPSA, y = WLOGP**. Each region is an ellipse; membership is a point-in-polygon
test, NOT an inequality on a single axis:

    white region (the "egg white")  -> HIA  (passive gastro-intestinal absorption); True = absorbed
    yolk  region (the "egg yolk")   -> BBB  (passive blood-brain-barrier penetration); True = permeant

The yolk is the more restrictive INNER region (TPSA up to ~79, WLOGP ~0.4..6.0); the white extends much
further in TPSA (to ~142). One point can be in the white but not the yolk (absorbed, not brain-penetrant),
in both, or in neither.

Coordinate convention is load-bearing (CLAUDE.md §4, F-9): **TPSA on x, WLOGP on y**. Swapping the axes
silently inverts every call, so the region vertices in ``regions.json`` are stored as ``[tpsa, wlogp]`` and
the membership test feeds them in that order. The unit test pins this with a known in-yolk point.

Two descriptor choices match the original BOILED-Egg exactly (verified from pyBOILEDegg):

- **WLOGP = RDKit Crippen ``MolLogP``** (Wildman-Crippen 1999) - the SAME lens as t10 rdkit_crippen, not a
  different logP. (RDKit exposes it as ``MolLogP``; the BOILED-Egg paper calls the descriptor WLOGP.)
- **TPSA with S and P contributions included** (``CalcTPSA(..., includeSandP=True)``). The original
  BOILED-Egg was fit against TPSA-including-S-and-P, so the ellipse boundaries are only correct for that
  variant. RDKit's DEFAULT TPSA excludes S and P and would shift the x-coordinate for any S/P-containing
  molecule, silently misplacing it relative to the boundary. This adapter therefore forces
  ``includeSandP=True`` to reproduce the model faithfully.

Region boundaries: the two ~100-vertex polygons in ``regions.json`` are the verbatim ``gia_coords`` /
``bbb_coords`` vertex lists from bfmilne/pyBOILEDegg (which trace the Daina & Zoete 2016 supporting-info
ellipses). They were fetched and validated on the box (point count, closure, and TPSA/WLOGP extents all
match the published bounds: white TPSA up to ~142, yolk TPSA < ~79). Membership uses a self-contained
ray-casting point-in-polygon test, so this env needs ONLY rdkit (no shapely).

Direction / units (CLAUDE.md §4): both outputs are booleans (True = absorbed / permeant). BOILED-Egg is a
coarse passive-permeability screen; on the distribution side its BBB boolean is one incompatible-scale
signal among BBB Score / CNS MPO / BBB_Martins, reconciled ordinally downstream (F-4), never averaged.

``--gpu`` is accepted and ignored (``requires_gpu=False``): the uniform CLI is identical for every model so
the dispatcher can build one command, but BOILED-Egg is pure CPU geometry.

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
from rdkit.Chem import Crippen, rdMolDescriptors

MODEL = "boiled_egg"

# The two region polygons, loaded once at import from the committed sidecar (verbatim pyBOILEDegg
# gia_coords / bbb_coords, each an [tpsa, wlogp] vertex list). Kept out of this file so the numeric
# artifact is auditable on its own and this module stays readable.
REGIONS_PATH = Path(__file__).resolve().parent / "regions.json"
_REGIONS = json.loads(REGIONS_PATH.read_text(encoding="utf-8"))
GIA_COORDS: list[list[float]] = _REGIONS["gia_coords"]  # white / HIA
BBB_COORDS: list[list[float]] = _REGIONS["bbb_coords"]  # yolk / BBB


def _provenance() -> dict[str, Any]:
    """Provenance stamped onto every emitted record. ``rdkit_version`` is read live, not fabricated."""
    return {
        "model": MODEL,
        "method": (
            "BOILED-Egg (Daina & Zoete 2016): point-in-polygon in (x=TPSA, y=WLOGP) space. HIA = point in "
            "the white/GIA ellipse; BBB = point in the yolk ellipse (inner, more restrictive). "
            "WLOGP = RDKit Crippen MolLogP (Wildman-Crippen 1999, the t10 lens); "
            "TPSA = RDKit CalcTPSA(includeSandP=True) (original BOILED-Egg definition). "
            "Region vertices = pyBOILEDegg gia_coords/bbb_coords (verbatim); membership via ray-casting."
        ),
        "rdkit_version": rdBase.rdkitVersion,
        "citation": (
            "Daina A, Zoete V. \"A BOILED-Egg To Predict Gastrointestinal Absorption and Brain "
            "Penetration of Small Molecules.\" ChemMedChem 2016, 11(11):1117-1121, "
            "DOI 10.1002/cmdc.201600182 (open access). Reference implementation / vertex lists: "
            "github.com/bfmilne/pyBOILEDegg (PyBOILEDegg.py)."
        ),
        "license": "BSD-3-Clause (RDKit); boundary vertices from pyBOILEDegg (GPL-3.0), tracing the "
        "open-access Daina & Zoete 2016 model data.",
    }


def point_in_polygon(x: float, y: float, polygon: list[list[float]]) -> bool:
    """Ray-casting point-in-polygon test (even-odd rule). ``polygon`` is a list of ``[x, y]`` vertices.

    Casts a ray in +x from ``(x, y)`` and counts edge crossings; an odd count means inside. The BOILED-Egg
    polygons are closed (first vertex repeated as last); the algorithm treats each consecutive pair as an
    edge, so the degenerate closing edge is harmless. This replaces shapely's ``Point.within(Polygon)`` so
    the isolated env needs only rdkit.
    """
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i][0], polygon[i][1]
        xj, yj = polygon[j][0], polygon[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def boiled_egg(mol: Chem.Mol) -> dict[str, Any]:
    """Compute the two BOILED-Egg booleans + the (TPSA, WLOGP) coordinates for one RDKit molecule.

    Returns ``HIA`` / ``BBB`` booleans and the raw descriptor values so a reader can reconstruct and audit
    the point-in-polygon decision. TPSA uses ``includeSandP=True`` to match the original model.
    """
    wlogp = float(Crippen.MolLogP(mol))
    tpsa = float(rdMolDescriptors.CalcTPSA(mol, includeSandP=True))
    hia = point_in_polygon(tpsa, wlogp, GIA_COORDS)
    bbb = point_in_polygon(tpsa, wlogp, BBB_COORDS)
    return {"HIA": bool(hia), "BBB": bool(bbb), "WLOGP": wlogp, "TPSA": tpsa}


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


def record_for(rec: dict[str, Any]) -> dict[str, Any]:
    """Compute one ``OutputRecord``-shaped dict for a single input record.

    A rule (deterministic), so ``uncertainty`` is ``None``. The two endpoint values are the booleans HIA
    (permeability endpoint) and BBB (distribution endpoint); the same record feeds both endpoints (the
    aggregators query the registry by endpoint, not by folder). An invalid or empty SMILES returns a valid
    record with null ``endpoint_values`` and the reason in ``raw`` rather than raising.
    """
    smiles = str(rec.get("smiles") or "").strip()
    mol_id = rec.get("mol_id")
    base: dict[str, Any] = {"model": MODEL, "uncertainty": None, "provenance": _provenance()}

    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return {
            **base,
            "endpoint_values": {"HIA_boiled_egg": None, "BBB_boiled_egg": None},
            "raw": {
                "error": "RDKit could not parse SMILES (invalid or empty)",
                "smiles": smiles,
                "mol_id": mol_id,
            },
        }

    terms = boiled_egg(mol)
    return {
        **base,
        "endpoint_values": {"HIA_boiled_egg": terms["HIA"], "BBB_boiled_egg": terms["BBB"]},
        "raw": {
            "smiles": smiles,
            "mol_id": mol_id,
            "WLOGP": terms["WLOGP"],
            "TPSA": terms["TPSA"],
            "tpsa_includes_s_and_p": True,
            "in_white_gia": terms["HIA"],
            "in_yolk_bbb": terms["BBB"],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BOILED-Egg (Daina & Zoete 2016) rule adapter (uniform model CLI).")
    parser.add_argument("--input", required=True, type=Path, help="pipeline input (InputRecord JSON, JSON array, or .smi)")
    parser.add_argument("--output", required=True, type=Path, help="where to write the OutputRecord JSON")
    parser.add_argument("--gpu", type=int, default=None, help="ignored (boiled_egg is CPU-only); present for the uniform CLI")
    args = parser.parse_args(argv)

    records, single = parse_inputs(args.input.read_text(encoding="utf-8"))
    outputs = [record_for(rec) for rec in records]
    payload: Any = outputs[0] if (single and len(outputs) == 1) else outputs

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
