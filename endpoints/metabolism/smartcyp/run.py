#!/usr/bin/env python
"""smartcyp adapter - per-atom site-of-metabolism (SoM) ranking (CYP soft spot).

Uniform model CLI (CLAUDE.md 0.2, SETTLED 6):

    python run.py --input <path> --output <path> [--gpu N]

WHAT THIS WRAPS (owner-directed override). The authentic SMARTCyp 3.0 (Python/RDKit) source is
unobtainable (KU server 503, no PyPI, no public source repo - see README). The owner has DIRECTED this
adapter to use the LEGACY SMARTCyp 2.4.2 Java engine (`vendor/smartcyp-2.4.2.jar`), run via `java -jar`
as a subprocess. That explicitly overrides the standing "metabolism endpoint is JVM-free" landmine in
CLAUDE.md 4 - the override is authorized. This is SMARTCyp 2.4.2 (the CDK/Java line), NOT the 3.0 Python
rewrite; the SoM science (DFT fragment energies + SMARTS reactivity rules) is the same method (Rydberg
2010), the packaging differs. run.py stamps the engine version onto every record so provenance is honest.

DIRECTION (landmine, CLAUDE.md 4, F-2): SMARTCyp `Score` is a kJ/mol-scale reactivity energy where a
LOWER Score (and `Ranking == 1`) = MORE likely site of metabolism. This is the OPPOSITE of FAME3R, whose
probability runs UP = more likely SoM. The two scales are never averaged; the metabolism aggregator
co-ranks the atoms ORDINALLY on atom index. This adapter therefore emits the raw per-atom Score/Ranking
verbatim and applies no binarization - harmonization is the aggregator's job, not this adapter's.

ATOM-INDEX ALIGNMENT (the load-bearing correctness point). The aggregator co-ranks SMARTCyp vs FAME3R on
`raw.atoms[].atom_index`, so both must use the SAME atom indexing (the RDKit atom index). SMARTCyp reads
molecule files in atom-file order and numbers heavy atoms 1..N in that order. So this adapter builds each
molecule with RDKit and writes an atom-ORDERED SDF; SMARTCyp then numbers atoms exactly in RDKit index
order, and `atom_index = (SMARTCyp Atom number) - 1`. Verified against a real 2.4.2 run: the element of
each SMARTCyp row matches the RDKit atom at that index (the adapter re-checks this per atom and flags any
divergence rather than silently mis-aligning).

RAW HEADER (verified against a real jar run, NOT hardcoded from the legacy template). The 2.4.2 `-printall`
CSV header observed on a live run is:

    Molecule,Atom,Ranking,Score,Energy,Relative Span,2D6ranking,2D6score,Span2End,N+Dist,2Cranking,2Cscore,COODist,2DSASA

The parser maps columns from whatever header the jar actually prints (it reads the header row), so a
future engine that reorders/renames columns is handled by name, not by position.

OUTPUT (core.schemas.OutputRecord):
  - `raw.atoms`: the per-atom table (the load-bearing SoM output the aggregator co-ranks). Each row carries
    `atom_index` (RDKit index), `element`, the general-3A4 `Score` (float, lower = SoM) and `Ranking`
    (int, 1 = top; null-not-ranked -> None), plus the isoform/geometry columns the jar emits
    (2D6ranking/2D6score, 2Cranking/2Cscore = 2C9, Energy, Relative Span, Span2End, N+Dist, COODist,
    2DSASA), plus the raw `atom_label` ("C.2") for audit.
  - `endpoint_values`: a top-site SUMMARY only (the Ranking==1 atom index + its Score + n_atoms). The
    authoritative per-atom detail stays in `raw.atoms` (a SoM table is inherently per-atom).
  - `uncertainty`: null. SMARTCyp emits no native per-atom uncertainty; the reserved envelope stays empty.
  - `raw.csv`: the verbatim CSV text (raw-output cache, CLAUDE.md 4a - reconstructible if the engine changes).
  - Invalid/unparseable SMILES -> a valid record with null values and the reason in `raw.error` (never
    crashes a bulk batch).

This runs in the model's ISOLATED pixi env (rdkit + openjdk) and so CANNOT import `core`; it emits plain
JSON matching `core.schemas.OutputRecord` and the dispatcher validates it on collection. `--gpu` is
accepted and ignored (`requires_gpu=False`); SMARTCyp is CPU-only.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path
from typing import Any

MODEL = "smartcyp"
ENGINE_VERSION = "2.4.2"

# The vendored engine (a BINARY jar - gitignored, fetched once per README, never committed). An override
# path is honored for flexibility; default is beside this file under vendor/.
_DEFAULT_JAR = Path(__file__).resolve().parent / "vendor" / f"smartcyp-{ENGINE_VERSION}.jar"

# The general-3A4 columns the metabolism aggregator keys on (must match aggregate.py exactly):
#   SMARTCYP_SCORE_KEY = "Score"    (lower = more likely SoM, kJ/mol scale)
#   SMARTCYP_RANKING_KEY = "Ranking" (1 = most likely SoM)
GENERAL_SCORE_COL = "Score"
GENERAL_RANKING_COL = "Ranking"

# Isoform / geometry columns carried through verbatim from the jar's real header (2C* == 2C9).
PASSTHROUGH_COLS = (
    "Energy",
    "Relative Span",
    "2D6ranking",
    "2D6score",
    "Span2End",
    "N+Dist",
    "2Cranking",
    "2Cscore",
    "COODist",
    "2DSASA",
)


def jar_path() -> Path:
    """Resolve the SMARTCyp jar: SMARTCYP_JAR override, else the packaged vendor/ default."""
    override = os.environ.get("SMARTCYP_JAR")
    return Path(override) if override else _DEFAULT_JAR


def _provenance() -> dict[str, Any]:
    """Provenance stamped onto every emitted record. Never fabricated; states the 2.4.2 caveat honestly."""
    return {
        "model": MODEL,
        "engine": f"SMARTCyp {ENGINE_VERSION} (legacy CDK/Java line, run via `java -jar`)",
        "engine_caveat": "This is SMARTCyp 2.4.2 (Java jar), NOT the 3.0 Python/RDKit rewrite. Same SoM "
        "method (DFT fragment reactivity energies + SMARTS rules, Rydberg 2010); different packaging. Used "
        "under an explicit owner-directed override of the CLAUDE.md JVM-free-metabolism landmine.",
        "method": "SMARTCyp -printall: general (3A4) Ranking/Score + 2D6 and 2C9 isoform corrections; "
        "atom order pinned to the RDKit atom index via an atom-ordered SDF.",
        "citation": "Rydberg P, Gloriam DE, Sharma J, Kaur P, Olsen L. SMARTCyp: A 2D method for "
        "prediction of cytochrome P450-mediated drug metabolism. ACS Med. Chem. Lett. 1(3):96-100 (2010). "
        "doi:10.1021/ml100016x.",
        "license": "Engine: University of Copenhagen SMARTCyp, free for academic/research use (cite "
        "Rydberg 2010). The MDStudio wrapper the jar is bundled with is Apache-2.0; the jar itself is the "
        "UCPH SMARTCyp program.",
        "direction": "lower Score / Ranking==1 = more likely site of metabolism (OPPOSITE of FAME3R)",
        "n_oxidation_correction": "empirical N-oxidation correction is ON (engine default, no -noempcorr); "
        "it folds a +penalty into the Score of tertiary-amine N (e.g. FTO-43's pyrrolidine N), down-ranking "
        "N-oxidation there. The aggregator REFLECTS this as emitted, it does not correct it (CLAUDE.md 4).",
    }


def _f(value: Any) -> float | None:
    """Coerce a CSV cell to a finite float, or None (handles the literal 'null' the jar prints)."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() == "null":
        return None
    try:
        f = float(s)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _i(value: Any) -> int | None:
    """Coerce a CSV cell to an int, or None (handles the literal 'null' the jar prints for non-ranked atoms)."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() == "null":
        return None
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


def _parse_atom_label(label: str) -> tuple[str | None, int | None]:
    """Split a SMARTCyp `Atom` label ('C.2', 'Cl.5', 'N.4') into (element, atom_index).

    SMARTCyp numbers heavy atoms 1..N in molecule-file order; because we feed an RDKit-ordered SDF, the
    number is (RDKit atom index + 1). Returns (element, zero-based atom_index).
    """
    s = (label or "").strip()
    if "." not in s:
        return (s or None, None)
    element, _, num = s.rpartition(".")
    try:
        n = int(num)
    except ValueError:
        return (element or None, None)
    return (element or None, n - 1)


def _read_csv(text: str) -> tuple[list[str], list[dict[str, str]]]:
    """Parse the jar's CSV into (header, rows-as-dicts) by header NAME (not fixed positions)."""
    import csv
    import io

    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return [], []
    header = [h.strip() for h in rows[0]]
    out: list[dict[str, str]] = []
    for r in rows[1:]:
        if not r or all(not c.strip() for c in r):
            continue
        out.append({header[i]: (r[i] if i < len(r) else "") for i in range(len(header))})
    return header, out


def _run_jar(jar: Path, sdf_path: Path, workdir: Path) -> str:
    """Run `java -jar <jar> -printall <sdf>` in workdir and return the CSV text it writes.

    -printall emits every atom (ranked + non-ranked). The empirical N-oxidation correction is left ON
    (engine default). The jar names its output SMARTCyp_Results_<timestamp>.csv in the cwd; an isolated
    workdir per molecule guarantees exactly one predictable CSV.
    """
    cmd = ["java", "-jar", str(jar), "-printall", str(sdf_path)]
    proc = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True, timeout=600)
    csvs = sorted(glob.glob(str(workdir / "*.csv")))
    if not csvs:
        detail = (proc.stderr or proc.stdout or "").strip()[:500]
        raise RuntimeError(f"SMARTCyp wrote no CSV (exit {proc.returncode}): {detail}")
    return Path(csvs[0]).read_text(encoding="utf-8")


def score_molecule(smiles: str, jar: Path) -> tuple[list[dict[str, Any]], str | None, str | None]:
    """Return (per-atom rows, error, raw_csv_text) for one SMILES.

    Builds the molecule with RDKit, writes an atom-ordered SDF (2D coords), runs the jar, parses the real
    CSV header by name, and maps each row to `atom_index = SMARTCyp number - 1` (RDKit index). Cross-checks
    the SMARTCyp element against the RDKit atom symbol and notes any divergence in the row.
    """
    from rdkit import Chem
    from rdkit.Chem import AllChem

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return [], "RDKit could not parse SMILES", None
    n = mol.GetNumAtoms()
    if n == 0:
        return [], "molecule has no atoms", None
    rdkit_symbols = [mol.GetAtomWithIdx(i).GetSymbol() for i in range(n)]

    with tempfile.TemporaryDirectory() as td:
        workdir = Path(td)
        sdf_path = workdir / "ligand.sdf"
        # 2D coords so the SDF is a valid molecule file; SMARTCyp regenerates what it needs internally.
        AllChem.Compute2DCoords(mol)
        writer = Chem.SDWriter(str(sdf_path))
        writer.write(mol)
        writer.close()

        csv_text = _run_jar(jar, sdf_path, workdir)

    header, csv_rows = _read_csv(csv_text)

    rows: list[dict[str, Any]] = []
    for cr in csv_rows:
        element, atom_index = _parse_atom_label(cr.get("Atom", ""))
        if atom_index is None or not (0 <= atom_index < n):
            # A row we cannot align to an RDKit atom: keep it visible but do not fabricate an index.
            continue
        rd_symbol = rdkit_symbols[atom_index]
        row: dict[str, Any] = {
            "atom_index": atom_index,
            # RDKit symbol is authoritative for the aggregator's `element`; it is what atom_index refers to.
            "element": rd_symbol,
            "atom_label": cr.get("Atom", "").strip(),
            # The two general-3A4 keys the aggregator reads (exact key names).
            GENERAL_SCORE_COL: _f(cr.get(GENERAL_SCORE_COL)),
            GENERAL_RANKING_COL: _i(cr.get(GENERAL_RANKING_COL)),
        }
        if element is not None and element != rd_symbol:
            row["element_mismatch"] = f"SMARTCyp element {element!r} != RDKit {rd_symbol!r} at index {atom_index}"
        # Carry the isoform (2D6, 2C9) and geometry columns through verbatim (numeric where possible).
        for col in PASSTHROUGH_COLS:
            if col not in cr:
                continue
            raw = cr[col]
            row[col] = _i(raw) if col.endswith("ranking") else _f(raw)
        rows.append(row)

    rows.sort(key=lambda r: r["atom_index"])
    if not rows:
        return [], "SMARTCyp produced no alignable atom rows", csv_text
    return rows, None, csv_text


def record_for(rec: dict[str, Any], jar: Path, provenance: dict[str, Any]) -> dict[str, Any]:
    """Compute one OutputRecord-shaped dict for a single input molecule.

    endpoint_values carries only the top-site SUMMARY (Ranking==1 atom + its Score); the full per-atom
    table lives in raw.atoms (the aggregator co-ranks that). uncertainty is null (no native signal).
    """
    smiles = str(rec.get("smiles") or "").strip()
    mol_id = rec.get("mol_id")
    base: dict[str, Any] = {"model": MODEL, "provenance": provenance}

    if not smiles:
        rows, err, csv_text = [], "empty SMILES", None
    else:
        try:
            rows, err, csv_text = score_molecule(smiles, jar)
        except Exception as exc:  # never crash a bulk batch on one molecule
            rows, err, csv_text = [], f"{type(exc).__name__}: {exc}", None

    if err is not None or not rows:
        return {
            **base,
            "endpoint_values": {"top_som_atom_index": None, "top_som_score": None, "n_atoms": 0},
            "uncertainty": None,
            "raw": {
                "error": err or "no atoms scored",
                "smiles": smiles,
                "mol_id": mol_id,
                "engine_version": ENGINE_VERSION,
                "csv": csv_text,
            },
        }

    # Top site of the general 3A4 model: prefer the atom the engine labels Ranking == 1; fall back to the
    # lowest Score (lower = more likely SoM) if the engine ranked nothing (all null).
    ranked = [r for r in rows if r.get(GENERAL_RANKING_COL) == 1]
    if ranked:
        top = ranked[0]
    else:
        scored = [r for r in rows if r.get(GENERAL_SCORE_COL) is not None]
        top = min(scored, key=lambda r: r[GENERAL_SCORE_COL]) if scored else None

    endpoint_values = {
        "top_som_atom_index": (top["atom_index"] if top else None),
        "top_som_score": (top[GENERAL_SCORE_COL] if top else None),
        "top_som_atom_label": (top.get("atom_label") if top else None),
        "n_atoms": len(rows),
    }

    return {
        **base,
        "endpoint_values": endpoint_values,
        "uncertainty": None,  # SMARTCyp emits no native per-atom uncertainty; reserved envelope stays empty.
        "raw": {
            "smiles": smiles,
            "mol_id": mol_id,
            "engine_version": ENGINE_VERSION,
            # The per-atom SoM table - the load-bearing output. atom_index is the RDKit index (pinned via
            # the atom-ordered SDF). Consumed by the metabolism aggregator via ORDINAL co-rank with FAME3R.
            "atoms": rows,
            "direction": "lower Score / Ranking==1 = more likely site of metabolism (OPPOSITE of FAME3R); "
            "co-ranked ORDINALLY at the aggregator, never averaged with FAME3R probability (F-2).",
            # Verbatim CSV (raw-output cache: reconstructible if the engine output ever changes).
            "csv": csv_text,
        },
    }


def parse_inputs(text: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse ``--input`` into ``(records, single)`` - same contract as the other adapters.

    Accepts a single InputRecord object (single=True), a JSON array of them, or a ``.smi`` file
    (``<SMILES><whitespace><title>`` per line, ``#`` comments).
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


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore")  # keep stdout clean; the real output is the JSON file
    parser = argparse.ArgumentParser(description="SMARTCyp per-atom site-of-metabolism adapter (uniform model CLI).")
    parser.add_argument("--input", required=True, type=Path, help="pipeline input (InputRecord JSON, JSON array, or .smi)")
    parser.add_argument("--output", required=True, type=Path, help="where to write the OutputRecord JSON")
    parser.add_argument("--gpu", type=int, default=None, help="ignored (SMARTCyp is CPU-only); present for the uniform CLI")
    args = parser.parse_args(argv)

    jar = jar_path()
    if not jar.exists():
        raise FileNotFoundError(
            f"missing SMARTCyp engine {jar}. It is a vendored binary (gitignored); fetch it once per the "
            f"README (clone MD-Studio/MDStudio_SMARTCyp, copy mdstudio_smartcyp/bin/smartcyp-{ENGINE_VERSION}.jar "
            f"into vendor/), or set SMARTCYP_JAR."
        )

    provenance = _provenance()
    records, single = parse_inputs(args.input.read_text(encoding="utf-8"))
    outputs = [record_for(rec, jar, provenance) for rec in records]
    payload: Any = outputs[0] if (single and len(outputs) == 1) else outputs

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
