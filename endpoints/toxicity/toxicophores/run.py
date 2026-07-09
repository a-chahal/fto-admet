#!/usr/bin/env python
"""toxicophores adapter - toxicity structural-alert screen (toxicity endpoint).

Uniform model CLI (CLAUDE.md §2, SETTLED §6):

    python run.py --input <path> --output <path> [--gpu N]

A CODE-PKG rule (no weights, no GPU): pure RDKit substructure matching via ``rdkit.Chem.FilterCatalog``.
It runs in this model's ISOLATED pixi env (rdkit + python only) and therefore CANNOT import ``core`` (a
separate env). So it emits plain JSON matching the shape of ``core.schemas.OutputRecord``; the dispatcher
validates that JSON against the real schema on collection. The exact keys are documented in ``README.md``
and mirrored here.

Catalog choice (docs IO_SPEC §28, Provenance §B#30): "toxicophores" is **not one canonical RDKit
catalog**. The task requires picking and documenting exactly ONE alert source; this adapter uses the
**BRENK** catalog (``FilterCatalogs.BRENK``, Brenk et al. 2008 - unwanted / reactive functionality,
i.e. known reactive/toxic substructures), the documented default. It is exposed as the module constant
``CATALOG_NAME`` and echoed in every record's ``endpoint_values["catalog"]`` so a downstream reader
never has to guess which alert set produced the flag.

Intent vs t17 (the landmine): this is DISTINCT from the ``structural_alerts`` ``pains_brenk`` screen by
**intent** - toxicity (known toxic / reactive substructures) here, versus assay-interference (PAINS)
there - NOT by mechanism. Even though BRENK is reused, the endpoint, the framing, and the emitted fields
differ: this adapter reports a single ``tox_alert_*`` flag/count for the chosen toxicity catalog.

Direction (docs §28): **more alerts = more flagged.** This is a SOFT filter that OVER-flags: a hit means
"look closer", NOT auto-kill. The consuming policy (the toxicity aggregator, which later folds these
alerts together with the ADMET-AI tox heads into a per-endpoint P(toxic)) is downstream; this adapter
only emits the raw flag / count / matched names.

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

MODEL = "toxicophores"

# The single documented toxicity alert catalog (see the landmine above). One string, exposed as a
# constant so the exact catalog name is auditable and echoed into every emitted record.
CATALOG_NAME = "BRENK"


def _build_catalog(*catalog_enums: Any) -> FilterCatalog:
    """Build one ``FilterCatalog`` from one or more ``FilterCatalogParams.FilterCatalogs`` members."""
    params = FilterCatalogParams()
    for cat in catalog_enums:
        params.AddCatalog(cat)
    return FilterCatalog(params)


# Built once at import (loading the SMARTS is not free). BRENK = Brenk et al. 2008 unwanted/reactive
# functionality, the chosen single toxicity alert source.
_CATS = FilterCatalogParams.FilterCatalogs
TOX_CATALOG = _build_catalog(_CATS.BRENK)


def _provenance() -> dict[str, Any]:
    """Provenance stamped onto every emitted record. ``rdkit_version`` is read live, not fabricated."""
    return {
        "model": MODEL,
        "method": (
            "RDKit FilterCatalog substructure screen over a single documented toxicity alert catalog: "
            "BRENK (FilterCatalogs.BRENK, Brenk et al. 2008 - unwanted / reactive functionality, i.e. "
            "known reactive/toxic substructures). Reports a match boolean, an alert count, the matched "
            "alert names, and the matched-atom substructure. Soft filter (over-flags): more alerts = "
            "more flagged, look-closer not auto-kill. Toxicity intent (distinct from the PAINS/BRENK "
            "assay-interference screen at endpoints/structural_alerts/pains_brenk by intent, not "
            "mechanism)."
        ),
        "catalog": CATALOG_NAME,
        "rdkit_version": rdBase.rdkitVersion,
        "citation": (
            "Brenk R, Schipani A, James D, Krasowski A, Gilbert IH, Frearson J, Wyatt PG. \"Lessons "
            "Learnt from Assembling Screening Libraries for Drug Discovery for Neglected Diseases.\" "
            "ChemMedChem 2008, 3(3):435-444, DOI 10.1002/cmdc.200700139. Alert SMARTS as shipped in "
            "RDKit's FilterCatalog."
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

    A rule (deterministic), so ``uncertainty`` is ``None``. ``endpoint_values`` carries the three scalar
    fields (``tox_alert_hit``, ``tox_alert_count``, ``catalog``); the matched-alert names and matched-atom
    substructures live in ``raw`` (non-scalar, per CLAUDE.md §3 / the schema note). An invalid or empty
    SMILES returns a valid record with null flag/count (``catalog`` still carried, since it is a constant)
    and the reason in ``raw`` rather than raising.
    """
    smiles = str(rec.get("smiles") or "").strip()
    mol_id = rec.get("mol_id")
    base: dict[str, Any] = {"model": MODEL, "uncertainty": None, "provenance": _provenance()}

    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return {
            **base,
            "endpoint_values": {
                "tox_alert_hit": None,
                "tox_alert_count": None,
                "catalog": CATALOG_NAME,
            },
            "raw": {
                "error": "RDKit could not parse SMILES (invalid or empty)",
                "smiles": smiles,
                "mol_id": mol_id,
                "catalog": CATALOG_NAME,
            },
        }

    tox = _screen(mol, TOX_CATALOG)
    return {
        **base,
        "endpoint_values": {
            "tox_alert_hit": tox["hit"],
            "tox_alert_count": tox["count"],
            "catalog": CATALOG_NAME,
        },
        "raw": {
            "smiles": smiles,
            "mol_id": mol_id,
            "catalog": CATALOG_NAME,
            "tox_alert_matches": tox["entries"],  # [{name, atoms}] - matched alert names + substructure
            "tox_alert_names": [e["name"] for e in tox["entries"]],  # flat list of matched alert names
            "soft_filter": True,  # over-flags; look-closer, not auto-kill (docs §28)
            "intent": "toxicity",  # distinct from t17 pains_brenk (assay-interference) by intent
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Toxicity structural-alert screen (RDKit FilterCatalog, BRENK) - uniform model CLI."
    )
    parser.add_argument("--input", required=True, type=Path, help="pipeline input (InputRecord JSON, JSON array, or .smi)")
    parser.add_argument("--output", required=True, type=Path, help="where to write the OutputRecord JSON")
    parser.add_argument("--gpu", type=int, default=None, help="ignored (toxicophores is CPU-only); present for the uniform CLI")
    args = parser.parse_args(argv)

    records, single = parse_inputs(args.input.read_text(encoding="utf-8"))
    outputs = [record_for(rec) for rec in records]
    payload: Any = outputs[0] if (single and len(outputs) == 1) else outputs

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
