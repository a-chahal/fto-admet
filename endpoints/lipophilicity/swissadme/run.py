#!/usr/bin/env python
"""swissadme adapter - the SwissADME lipophilicity consensus, RECONSTRUCTED IN CODE.

Uniform model CLI (CLAUDE.md §2, SETTLED §6):

    python run.py --input <path> --output <path> [--gpu N]

SwissADME (swissadme.ch) is a **web-only** tool with no API, so it is NOT called in the bulk loop
(CLAUDE.md landmine + task t27). Its lipophilicity role is reconstructible in code: the site reports
five logP lenses plus their mean (`Consensus Log Po/w`; Daina 2017 Sci. Rep. 10.1038/srep42717). Three
lenses are open and reproduced here; two are proprietary/defunct and dropped:

    lens          reproducible?   how
    ----          -------------   ---
    WLOGP         yes             = RDKit Crippen MolLogP (the exact same lens as t10 rdkit_crippen)
    MLOGP         yes             Moriguchi 1992/1994 13-descriptor regression (implemented below)
    XLOGP3        yes, if binary  external XLOGP3 CLI v3.2.2 (licensed download); used ONLY if present
    iLOGP         NO              SwissADME-internal GB/SA solvation - proprietary, omitted
    Silicos-IT    NO              defunct FILTER-IT - omitted

`Consensus_logP` = mean of the reproduced lenses (2-lens WLOGP+MLOGP by default; 3-lens if an XLOGP3
binary is available on the box). We do NOT fabricate an XLOGP3 value when the binary is absent (task
t27 + CLAUDE.md §5 no-fabricate): the adapter degrades cleanly to a 2-lens consensus and records the
reduction (`raw.lenses_used`, `raw.xlogp3_available`). See README for the degradation note.

Uncertainty is INDIRECT: the spread across the reproduced lenses. Convergence between the lenses = a
trustworthy logP; scatter = lean on measured logD instead (task t27). The raw spread (range + sample
std + the per-lens values) is recorded in `uncertainty.extra`; turning that spread into a calibrated
confidence is the operational AD/calibration policy, which is DEFERRED (CLAUDE.md §4a), so the
first-class `Uncertainty` fields are left null rather than filled with a guessed threshold.

These are **logP** lenses, NOT logD (flag F-12). For the di-basic FTO series the logP->logD conversion
needs a pKa and is done DOWNSTREAM with the single shared pKa source (F-13); it is never silently
applied here (CLAUDE.md §4a).

`--gpu` is accepted and ignored (`requires_gpu=False`): SwissADME's reconstruction is pure CPU RDKit
(plus an optional external CLI). The uniform CLI is identical for every model so the dispatcher builds
one command.

Robustness: an invalid or unparseable SMILES yields a per-record result with null values and the reason
in `raw` rather than raising - one bad molecule never sinks a bulk batch (the uniform contract).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from rdkit import Chem, rdBase
from rdkit.Chem import Crippen

MODEL = "swissadme"


# --------------------------------------------------------------------------------------------------
# WLOGP lens - the RDKit Crippen atom-contribution logP (identical to the t10 rdkit_crippen lens).
# --------------------------------------------------------------------------------------------------
def _wlogp(mol: Chem.Mol) -> float:
    """SwissADME's WLOGP lens = Wildman-Crippen MolLogP (Wildman & Crippen 1999)."""
    return float(Crippen.MolLogP(mol))


# --------------------------------------------------------------------------------------------------
# MLOGP lens - Moriguchi's 13-descriptor topological logP regression.
#   log P = -1.014 + 1.244*CX^0.6 - 1.017*NO^0.9 + 0.406*PRX - 0.145*UB^0.8 + 0.511*HB
#           + 0.268*POL - 2.215*AMP + 0.912*ALK - 0.392*RNG - 3.684*QN + 0.474*NO2
#           + 1.582*NCS + 0.773*BLM
#   Moriguchi I, et al. Chem. Pharm. Bull. 1992, 40(1):127-130; 1994, 42(4):976-978.
# The descriptor definitions below follow that paper (and Todeschini & Consonni's Handbook tabulation).
# Two descriptors are documented approximations (see README "MLOGP faithfulness"): HB (an intramolecular
# H-bond dummy that Moriguchi assigned by hand, not reproduced -> held at 0) and POL (aromatic polar
# substituents, counted as ring-attached heteroatoms). These, plus the fact that SwissADME's own MLOGP
# implementation is not open, are exactly why we cross-check against WLOGP/XLOGP3 and surface the spread.
# --------------------------------------------------------------------------------------------------

# Weighted carbon+halogen count (CX): C=1.0, F=0.5, Cl=1.0, Br=1.5, I=2.0 (all other atoms 0).
_CX_WEIGHT = {6: 1.0, 9: 0.5, 17: 1.0, 35: 1.5, 53: 2.0}

# SMARTS used by the descriptors, compiled once.
_SMARTS = {
    "amide": Chem.MolFromSmarts("[CX3](=[OX1])[NX3]"),
    "sulfonamide": Chem.MolFromSmarts("[SX4](=[OX1])(=[OX1])[NX3]"),
    "nitro": Chem.MolFromSmarts("[$([NX3](=O)=O),$([NX3+](=O)[O-])]"),
    "nquat": Chem.MolFromSmarts("[NX4+;!$([NX4+][OX1-])]"),
    "noxide": Chem.MolFromSmarts("[$([#7v4]=[OX1]),$([#7+][OX1-])]"),
    "isothiocyanate": Chem.MolFromSmarts("[NX2]=[CX2]=[SX1]"),
    "thiocyanate": Chem.MolFromSmarts("[SX2][CX2]#[NX1]"),
    "betalactam": Chem.MolFromSmarts("[NX3,NX4+]1[CX3](=[OX1])[#6][#6]1"),
    # amphoteric building blocks
    "alpha_amino_acid": Chem.MolFromSmarts("[NX3;!$([NX3][CX3]=[OX1]);!$([NX3+])][CX4][CX3](=[OX1])[OX2H1,OX1-]"),
    "aromatic_amine": Chem.MolFromSmarts("[c][NX3;H1,H2;!$([NX3][CX3]=[OX1])]"),
    "aromatic_cooh": Chem.MolFromSmarts("[c][CX3](=[OX1])[OX2H1,OX1-]"),
    "pyridine": Chem.MolFromSmarts("[nX2]"),
}


def _cx(mol: Chem.Mol) -> float:
    return sum(_CX_WEIGHT.get(a.GetAtomicNum(), 0.0) for a in mol.GetAtoms())


def _no(mol: Chem.Mol) -> int:
    return sum(1 for a in mol.GetAtoms() if a.GetAtomicNum() in (7, 8))


def _prx(mol: Chem.Mol) -> int:
    """Proximity effect of N/O: 1,3 (X-A-X, topological distance 2) = 2; 1,4 (distance 3) = 1.

    Correction -1 for each amide (-CON<) and sulfonamide (-SO2N<), per Moriguchi.
    """
    hetero = [a.GetIdx() for a in mol.GetAtoms() if a.GetAtomicNum() in (7, 8)]
    dm = Chem.GetDistanceMatrix(mol)
    prx = 0
    for i in range(len(hetero)):
        for j in range(i + 1, len(hetero)):
            d = dm[hetero[i]][hetero[j]]
            if d == 2:
                prx += 2
            elif d == 3:
                prx += 1
    prx -= len(mol.GetSubstructMatches(_SMARTS["amide"]))
    prx -= len(mol.GetSubstructMatches(_SMARTS["sulfonamide"]))
    return prx


def _ub(mol: Chem.Mol) -> int:
    """Number of unsaturated bonds (double + triple), aromatic rings kekulized, minus NO2 double bonds."""
    work = Chem.Mol(mol)
    try:
        Chem.Kekulize(work, clearAromaticFlags=True)
    except Exception:  # noqa: BLE001 - a molecule that will not kekulize keeps its aromatic bonds counted below
        pass
    ub = 0
    for bond in work.GetBonds():
        bt = bond.GetBondType()
        if bt in (Chem.BondType.DOUBLE, Chem.BondType.TRIPLE, Chem.BondType.AROMATIC):
            ub += 1
    # Each nitro group carries one N=O double bond that Moriguchi excludes from UB.
    ub -= len(mol.GetSubstructMatches(_SMARTS["nitro"]))
    return max(ub, 0)


def _pol(mol: Chem.Mol) -> int:
    """Aromatic polar substituents: heteroatoms (N/O/S) attached exocyclically to an aromatic ring.

    Documented approximation (README): counts ring-attached heteroatom substituents; substituents bonded
    to the ring through a carbon (e.g. an aromatic -COOH) are not counted. POL is capped, as in the model.
    """
    pol = 0
    for atom in mol.GetAtoms():
        if not atom.GetIsAromatic():
            continue
        for nbr in atom.GetNeighbors():
            if nbr.GetIsAromatic():
                continue
            if nbr.GetAtomicNum() in (7, 8, 16):
                pol += 1
    return min(pol, 4)


def _amp(mol: Chem.Mol) -> float:
    """Amphoteric property: alpha-amino acid = 1.0; aminobenzoic / pyridinecarboxylic acid = 0.5."""
    if mol.HasSubstructMatch(_SMARTS["alpha_amino_acid"]):
        return 1.0
    has_ar_cooh = mol.HasSubstructMatch(_SMARTS["aromatic_cooh"])
    if has_ar_cooh and mol.HasSubstructMatch(_SMARTS["aromatic_amine"]):
        return 0.5
    if has_ar_cooh and mol.HasSubstructMatch(_SMARTS["pyridine"]):
        return 0.5
    return 0.0


def _alk(mol: Chem.Mol) -> int:
    """Hydrocarbon dummy: 1 if the molecule contains only C and H, else 0."""
    return int(all(a.GetAtomicNum() in (1, 6) for a in mol.GetAtoms()))


def _rng(mol: Chem.Mol) -> int:
    """Ring dummy: 1 if any ring is NOT a benzene (6-membered aromatic all-carbon) ring, else 0."""
    ri = mol.GetRingInfo()
    for ring in ri.AtomRings():
        is_benzene = len(ring) == 6 and all(
            mol.GetAtomWithIdx(idx).GetIsAromatic() and mol.GetAtomWithIdx(idx).GetAtomicNum() == 6
            for idx in ring
        )
        if not is_benzene:
            return 1
    return 0


def _qn(mol: Chem.Mol) -> float:
    """Quaternary nitrogen: >N+< = 1.0 each; N-oxide (amine/aromatic, not nitro) = 0.5 each."""
    return 1.0 * len(mol.GetSubstructMatches(_SMARTS["nquat"])) + 0.5 * len(
        mol.GetSubstructMatches(_SMARTS["noxide"])
    )


def _no2(mol: Chem.Mol) -> int:
    return len(mol.GetSubstructMatches(_SMARTS["nitro"]))


def _ncs(mol: Chem.Mol) -> float:
    """Isothiocyanato (-N=C=S) = 1.0 each; thiocyanato (-SCN) = 0.5 each."""
    return 1.0 * len(mol.GetSubstructMatches(_SMARTS["isothiocyanate"])) + 0.5 * len(
        mol.GetSubstructMatches(_SMARTS["thiocyanate"])
    )


def _blm(mol: Chem.Mol) -> int:
    return int(mol.HasSubstructMatch(_SMARTS["betalactam"]))


def _mlogp(mol: Chem.Mol) -> float:
    """Moriguchi 1992/1994 13-descriptor logP. HB (intramolecular H-bond dummy) is held at 0 (README)."""
    cx = _cx(mol)
    no = _no(mol)
    ub = _ub(mol)
    hb = 0.0  # intramolecular H-bond dummy: hand-assigned in the original model, not reconstructed
    value = (
        -1.014
        + 1.244 * (cx**0.6 if cx > 0 else 0.0)
        - 1.017 * (no**0.9 if no > 0 else 0.0)
        + 0.406 * _prx(mol)
        - 0.145 * (ub**0.8 if ub > 0 else 0.0)
        + 0.511 * hb
        + 0.268 * _pol(mol)
        - 2.215 * _amp(mol)
        + 0.912 * _alk(mol)
        - 0.392 * _rng(mol)
        - 3.684 * _qn(mol)
        + 0.474 * _no2(mol)
        + 1.582 * _ncs(mol)
        + 0.773 * _blm(mol)
    )
    return float(value)


# --------------------------------------------------------------------------------------------------
# XLOGP3 lens - external CLI (v3.2.2), a licensed download. Used ONLY if a binary is present; otherwise
# the consensus degrades to 2-lens (never fabricated). The exact CLI wiring is confirmed when the box
# has the licensed binary; today it is absent, so `_xlogp3` returns None and the README records 2-lens.
# --------------------------------------------------------------------------------------------------
def _xlogp3_binary() -> str | None:
    """Locate an XLOGP3 executable: the XLOGP3_BIN env var wins, else `xlogp3` on PATH. None if absent."""
    env = os.environ.get("XLOGP3_BIN")
    if env and Path(env).exists():
        return env
    return shutil.which("xlogp3")


def _xlogp3(mol: Chem.Mol) -> float | None:
    """Run the external XLOGP3 CLI on one molecule if a binary exists; None on absence or any failure.

    XLOGP3 (Cheng et al. 2007) consumes a structure file. We hand it an SDF and parse the trailing float
    from its output. Any deviation from the expected CLI (a different flag set on a given build) is caught
    and degrades to None rather than guessing a value (CLAUDE.md §5 no-fabricate). The precise invocation
    is finalized against the licensed binary when it lands on the box; until then this path is inert.
    """
    binary = _xlogp3_binary()
    if not binary:
        return None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            sdf = Path(tmp) / "mol.sdf"
            block = Chem.MolToMolBlock(mol)
            sdf.write_text(block, encoding="utf-8")
            proc = subprocess.run(
                [binary, "-i", str(sdf)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode != 0:
                return None
            tokens = proc.stdout.replace("\n", " ").split()
            for tok in reversed(tokens):
                try:
                    return float(tok)
                except ValueError:
                    continue
            return None
    except Exception:  # noqa: BLE001 - any XLOGP3 failure degrades to 2-lens, never a fabricated value
        return None


# --------------------------------------------------------------------------------------------------
# Adapter plumbing.
# --------------------------------------------------------------------------------------------------
def _provenance(xlogp3_available: bool) -> dict[str, Any]:
    """Provenance stamped onto every record. Versions read live; the lens count reflects the real run."""
    lenses = ["WLOGP", "MLOGP"] + (["XLOGP3"] if xlogp3_available else [])
    return {
        "model": MODEL,
        "method": (
            "In-code SwissADME lipophilicity consensus (Daina 2017). "
            "WLOGP=RDKit Crippen MolLogP; MLOGP=Moriguchi 1992/1994 13-descriptor regression; "
            "XLOGP3=external CLI v3.2.2 (used only if a licensed binary is present). "
            "iLOGP + Silicos-IT are proprietary/defunct and omitted."
        ),
        "lenses_reproduced": lenses,
        "rdkit_version": rdBase.rdkitVersion,
        "citation": (
            "Daina A, Michielin O, Zoete V. SwissADME. Sci. Rep. 2017, 7:42717 (10.1038/srep42717); "
            "Wildman & Crippen, J Chem Inf Comput Sci 1999, 39:868 (WLOGP); "
            "Moriguchi et al., Chem. Pharm. Bull. 1992, 40:127 & 1994, 42:976 (MLOGP)."
        ),
        "license": "code: BSD-3-Clause (RDKit); methods: published formulae. Access: WEB-SUBSTITUTABLE.",
    }


def parse_inputs(text: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse the ``--input`` payload into ``(records, single)`` (identical contract to the t10 template).

    Accepts the three forms core may feed an adapter:
    - a single ``InputRecord`` JSON object -> ``single=True``,
    - a JSON array of ``InputRecord`` objects (a bulk batch) -> ``single=False``,
    - a ``.smi`` file (``<SMILES><whitespace><title>`` per line, ``#`` comments) -> ``single=False``.
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

    Reproduces the open SwissADME lenses, means them into ``Consensus_logP``, and records the lens spread
    as the (INDIRECT) uncertainty. An invalid/empty SMILES returns a valid null record with the reason in
    ``raw`` rather than raising (the uniform per-record error behavior).
    """
    smiles = str(rec.get("smiles") or "").strip()
    mol_id = rec.get("mol_id")

    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return {
            "model": MODEL,
            "endpoint_values": {"WLOGP": None, "MLOGP": None, "Consensus_logP": None},
            "uncertainty": None,
            "provenance": _provenance(xlogp3_available=False),
            "raw": {
                "error": "RDKit could not parse SMILES (invalid or empty)",
                "smiles": smiles,
                "mol_id": mol_id,
            },
        }

    wlogp = _wlogp(mol)
    mlogp = _mlogp(mol)
    xlogp3 = _xlogp3(mol)
    xlogp3_available = xlogp3 is not None

    lenses: dict[str, float] = {"WLOGP": wlogp, "MLOGP": mlogp}
    if xlogp3_available:
        lenses["XLOGP3"] = float(xlogp3)

    values = list(lenses.values())
    consensus = float(statistics.fmean(values))
    spread_range = float(max(values) - min(values))
    spread_std = float(statistics.stdev(values)) if len(values) > 1 else 0.0

    endpoint_values: dict[str, Any] = dict(lenses)
    endpoint_values["Consensus_logP"] = consensus

    # INDIRECT uncertainty: the scatter across lenses. Raw spread lives in extra; mapping it to a
    # calibrated confidence is the DEFERRED AD/calibration policy (CLAUDE.md §4a), so the first-class
    # Uncertainty fields stay null - convergence = trust, scatter = lean on measured logD (task t27).
    uncertainty = {
        "extra": {
            "lens_values": lenses,
            "spread_range": spread_range,
            "spread_std": spread_std,
            "n_lenses": len(values),
            "xlogp3_available": xlogp3_available,
            "note": "INDIRECT: spread across reproduced logP lenses; calibrated confidence is DEFERRED (AD policy).",
        }
    }

    return {
        "model": MODEL,
        "endpoint_values": endpoint_values,
        "uncertainty": uncertainty,
        "provenance": _provenance(xlogp3_available),
        "raw": {
            "smiles": smiles,
            "mol_id": mol_id,
            "lenses": lenses,
            "lenses_used": list(lenses.keys()),
            "xlogp3_available": xlogp3_available,
            "consensus_logP": consensus,
            "spread_range": spread_range,
            "spread_std": spread_std,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SwissADME lipophilicity consensus (reconstructed; uniform model CLI).")
    parser.add_argument("--input", required=True, type=Path, help="pipeline input (InputRecord JSON, JSON array, or .smi)")
    parser.add_argument("--output", required=True, type=Path, help="where to write the OutputRecord JSON")
    parser.add_argument("--gpu", type=int, default=None, help="ignored (swissadme reconstruction is CPU-only); present for the uniform CLI")
    args = parser.parse_args(argv)

    records, single = parse_inputs(args.input.read_text(encoding="utf-8"))
    outputs = [record_for(rec) for rec in records]
    payload: Any = outputs[0] if (single and len(outputs) == 1) else outputs

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
