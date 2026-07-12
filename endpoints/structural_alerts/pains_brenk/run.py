#!/usr/bin/env python
"""pains_brenk adapter - PAINS + BRENK structural-alert screen (structural_alerts endpoint).

Uniform model CLI (CLAUDE.md §2, SETTLED §6):

    python run.py --input <path> --output <path> [--gpu N]

A CODE-PKG rule (no weights, no GPU): pure RDKit substructure matching via ``rdkit.Chem.FilterCatalog``.
It runs in this model's ISOLATED pixi env (rdkit + python only) and therefore CANNOT import ``core`` (a
separate env). So it emits plain JSON matching the shape of ``core.schemas.OutputRecord``; the dispatcher
validates that JSON against the real schema on collection. The exact keys are documented in ``README.md``
and mirrored here.

Mechanism (docs IO_SPEC §24): two catalogs from RDKit's built-in ``FilterCatalog``:

- **PAINS** (Baell & Holloway 2010): the ``FilterCatalogs.PAINS`` catalog, which is the union of the
  three published sub-catalogs A/B/C. Pan-Assay INterference compoundS - substructures that recur as
  false positives across many assays.
- **BRENK** (Brenk et al. 2008): the ``FilterCatalogs.BRENK`` catalog - unwanted/reactive functionality
  to strip from lead-like screening libraries.

For each catalog this adapter reports, per the §24 output contract: a **match / no-match boolean**, the
**list of matched entries** (each entry's name/description), the **matched-atom indices** (the substructure
that triggered each alert), and a **count** of alerts.

Direction (CLAUDE.md §4, docs §24): **more alerts = more flagged.** This is a SOFT filter that OVER-flags:
a hit means "look closer", NOT auto-kill. It matters specifically here because the FTO assay is
fluorescence-based, and PAINS is enriched for assay-interfering (e.g. fluorescent / redox-cycling)
scaffolds - so a PAINS hit on an FTO series member is a flag to check for readout interference, not a
disqualification. The consuming policy is downstream; this adapter only emits the raw counts/flags.

``--gpu`` is accepted and ignored (``requires_gpu=False``): the uniform CLI is identical for every model so
the dispatcher can build one command, but this is pure CPU substructure matching.

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
from rdkit.Chem.FilterCatalog import FilterCatalog, FilterCatalogParams

MODEL = "pains_brenk"


def _build_catalog(*catalog_enums: Any) -> FilterCatalog:
    """Build one ``FilterCatalog`` from one or more ``FilterCatalogParams.FilterCatalogs`` members."""
    params = FilterCatalogParams()
    for cat in catalog_enums:
        params.AddCatalog(cat)
    return FilterCatalog(params)


# The two catalogs, built once at import (loading the SMARTS is not free). ``PAINS`` is the union of the
# published A/B/C sub-catalogs; ``BRENK`` is the Brenk et al. 2008 unwanted-functionality set.
_CATS = FilterCatalogParams.FilterCatalogs
PAINS_CATALOG = _build_catalog(_CATS.PAINS)
BRENK_CATALOG = _build_catalog(_CATS.BRENK)
# NIH: the NIH/MLSMR medicinal-chemistry alert set (reactive / assay-interfering motifs) as shipped in
# RDKit's FilterCatalog - a third catalog alongside PAINS and BRENK.
NIH_CATALOG = _build_catalog(_CATS.NIH)


def _provenance() -> dict[str, Any]:
    """Provenance stamped onto every emitted record. ``rdkit_version`` is read live, not fabricated."""
    return {
        "model": MODEL,
        "method": (
            "RDKit FilterCatalog substructure screen: PAINS (FilterCatalogs.PAINS = union of the "
            "published A/B/C sub-catalogs, Baell & Holloway 2010), BRENK (FilterCatalogs.BRENK, "
            "Brenk et al. 2008), and NIH (FilterCatalogs.NIH, the NIH/MLSMR medicinal-chemistry alert "
            "set). Per catalog: match boolean, matched-entry names, matched-atom indices, and an alert "
            "count. Soft filter (over-flags): more alerts = more flagged, look-closer not auto-kill."
        ),
        "rdkit_version": rdBase.rdkitVersion,
        "citation": (
            "Baell JB, Holloway GA. \"New Substructure Filters for Removal of Pan Assay Interference "
            "Compounds (PAINS) from Screening Libraries and for Their Exclusion in Bioassays.\" "
            "J Med Chem 2010, 53(7):2719-2740, DOI 10.1021/jm901137j. "
            "Brenk R et al. \"Lessons Learnt from Assembling Screening Libraries for Drug Discovery for "
            "Neglected Diseases.\" ChemMedChem 2008, 3(3):435-444, DOI 10.1002/cmdc.200700139. "
            "PAINS / BRENK / NIH alert SMARTS as shipped in RDKit's FilterCatalog."
        ),
        "license": "BSD-3-Clause (RDKit; the FilterCatalog SMARTS ship with RDKit).",
    }


def _screen(mol: Chem.Mol, catalog: FilterCatalog) -> dict[str, Any]:
    """Run one catalog against a molecule; return hit boolean, matched entries, atoms, and count.

    ``entries`` is a list of ``{"name": <description>, "atoms": [mol atom indices]}`` - one per matched
    filter entry. The matched-atom indices are the substructure that triggered the alert, taken from each
    ``FilterMatch.atomPairs`` (the second element of each pair is the atom index in ``mol``). Deduplicated
    and sorted so the substructure is stable and auditable.
    """
    matches = catalog.GetMatches(mol)
    entries: list[dict[str, Any]] = []
    for entry in matches:
        atom_ids: set[int] = set()
        for fmatch in entry.GetFilterMatches(mol):
            for _query_idx, mol_idx in fmatch.atomPairs:
                atom_ids.add(int(mol_idx))
        entries.append({"name": entry.GetDescription(), "atoms": sorted(atom_ids)})
    return {"hit": len(entries) > 0, "count": len(entries), "entries": entries}


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

    A rule (deterministic), so ``uncertainty`` is ``None``. ``endpoint_values`` carries the four scalar
    flags/counts; the matched-entry names and matched-atom substructures live in ``raw`` (non-scalar,
    per CLAUDE.md §3 / the schema note). An invalid or empty SMILES returns a valid record with null
    ``endpoint_values`` and the reason in ``raw`` rather than raising.
    """
    smiles = str(rec.get("smiles") or "").strip()
    mol_id = rec.get("mol_id")
    base: dict[str, Any] = {"model": MODEL, "uncertainty": None, "provenance": _provenance()}

    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return {
            **base,
            "endpoint_values": {
                "PAINS_hit": None,
                "PAINS_count": None,
                "BRENK_hit": None,
                "BRENK_count": None,
                "NIH_hit": None,
                "NIH_count": None,
            },
            "raw": {
                "error": "RDKit could not parse SMILES (invalid or empty)",
                "smiles": smiles,
                "mol_id": mol_id,
            },
        }

    pains = _screen(mol, PAINS_CATALOG)
    brenk = _screen(mol, BRENK_CATALOG)
    nih = _screen(mol, NIH_CATALOG)
    return {
        **base,
        "endpoint_values": {
            "PAINS_hit": pains["hit"],
            "PAINS_count": pains["count"],
            "BRENK_hit": brenk["hit"],
            "BRENK_count": brenk["count"],
            "NIH_hit": nih["hit"],
            "NIH_count": nih["count"],
        },
        "raw": {
            "smiles": smiles,
            "mol_id": mol_id,
            "PAINS_matches": pains["entries"],  # [{name, atoms}] - matched alert names + substructure
            "BRENK_matches": brenk["entries"],
            "NIH_matches": nih["entries"],
            "soft_filter": True,  # over-flags; look-closer, not auto-kill (docs §24)
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="PAINS + BRENK structural-alert screen (RDKit FilterCatalog) - uniform model CLI."
    )
    parser.add_argument("--input", required=True, type=Path, help="pipeline input (InputRecord JSON, JSON array, or .smi)")
    parser.add_argument("--output", required=True, type=Path, help="where to write the OutputRecord JSON")
    parser.add_argument("--gpu", type=int, default=None, help="ignored (pains_brenk is CPU-only); present for the uniform CLI")
    args = parser.parse_args(argv)

    records, single = parse_inputs(args.input.read_text(encoding="utf-8"))
    outputs = [record_for(rec) for rec in records]
    payload: Any = outputs[0] if (single and len(outputs) == 1) else outputs

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
