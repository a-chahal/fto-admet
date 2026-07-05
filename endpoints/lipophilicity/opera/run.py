#!/usr/bin/env python
"""opera adapter - an OUT-OF-BAND (MATLAB MCR + Java) model, so this file is a PARSER/WRAPPER only.

OPERA is compiled MATLAB. It runs on the free MATLAB Compiler Runtime (MCR) plus a Java stack (PaDEL /
CDK for descriptors), which cannot live in a pixi env (CLAUDE.md §4: non-Python heavy runtimes isolate
OUTSIDE pixi). So this model has ``env_manifest = None`` in the registry and is NEVER driven through
``core.dispatch`` (dispatch refuses ``env_manifest is None``). Instead:

- the MCR/Java runtime is installed out-of-band on the box (recipe in ``README.md``),
- OPERA is invoked once via ``./run_OPERA.sh <MCR_path> -s in.smi -o preds.txt -e LogP LogD pKa FuB
  Clint Caco2 -v 1`` (the exact command is in the README), producing a CSV ``preds.txt``,
- and THIS file parses that ``preds.txt`` into ``core.schemas.OutputRecord``-shaped JSON records that are
  transcribed to the ledger by hand (the same shape every other adapter emits).

Uniform model CLI (CLAUDE.md §2), with an out-of-band twist:

    python run.py --input <path> --output <path> [--gpu N] [--preds <preds.txt>]
                  [--opera-home <dir>] [--mcr <dir>] [--endpoints LogP LogD ...]

Two modes:
- ``--preds <preds.txt>`` (the offline / transcription path, and what the unit test drives): parse an
  ALREADY-computed OPERA output file. No MCR needed - pure stdlib. This is the code deliverable.
- no ``--preds`` (the box path, only when the MCR runtime IS installed): write an OPERA input file from
  ``--input``, shell out to ``run_OPERA.sh`` under ``--opera-home`` / ``--mcr`` (or ``$OPERA_HOME`` /
  ``$MCR_ROOT``), then parse the ``preds.txt`` it produced.

This file is intentionally stdlib-only (``csv`` + ``json`` + ``argparse``): it has no pixi env, so it must
import nothing outside the standard library and it does NOT import ``core`` (a separate env, exactly like
every other adapter). The dispatcher validates the emitted JSON against the real schema when it is
collected; here we only reproduce that shape faithfully.

Output shape (one OutputRecord per molecule x endpoint - OPERA is genuinely multi-endpoint and each
endpoint carries its OWN applicability-domain + confidence, and the ``Uncertainty`` envelope has one set
of scalar AD fields, so a per-(molecule, endpoint) record is the faithful mapping):

    endpoint_values = {<X>: <X>_pred}          # X in {LogP, LogD, pKa_a, pKa_b, FuB, Clint, Caco2, ...}
    uncertainty = {
        "ad_in_domain": bool(AD_<X>),          # OPERA AD flag, 1 = inside applicability domain
        "ad_index":     AD_index_<X>,          # 0-1 continuous AD / similarity index
        "conf_index":   Conf_index_<X>,        # 0-1, UP = MORE reliable -> DIRECT uncertainty (landmine)
        "extra": {"pred_range": ...}           # only if a `_predRange` column is present (see below)
    }

Units are per endpoint (documented in README, not baked into the key because the parser is header-driven
and endpoint-agnostic): LogP (log Kow), LogD (log), pKa_a / pKa_b (acid / base), FuB (fraction unbound,
0-1), Clint (uL/min/10^6 cells), Caco2 (logPapp). Direction: LogP / LogD UP = more lipophilic.

Header-driven, version-robust parsing. The verified OPERA source version emits exactly four columns per
endpoint: ``<X>_pred``, ``AD_<X>``, ``AD_index_<X>``, ``Conf_index_<X>`` and NO ``_predRange`` column
(IO_SPEC §1 #21; CLAUDE.md §4 landmine). A different OPERA build has been observed to add a
``<X>_predRange`` column and, under higher verbosity, nearest-neighbour / descriptor columns. Rather than
hard-code one column list (which would silently drop or misread the other build), the parser classifies
each column by its prefix/suffix and routes it: ``_pred`` -> value, ``AD_`` / ``AD_index_`` /
``Conf_index_`` -> uncertainty, ``_predRange`` -> ``uncertainty.extra['pred_range']`` (kept, never
discarded), anything else -> ``raw['extra_columns']``. So it is correct on both builds and nothing native
is lost. Which build produced a given ``preds.txt`` is recorded per record in ``raw['header']``.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

MODEL = "opera"

# The endpoints this pipeline requests from OPERA (the `-e` arguments). Multi-endpoint: OPERA logD/pKa
# standardize SFI / BBB / CNS-MPO, Clint cross-checks metabolism, FuB cross-checks OCHEM PPB (IO_SPEC §2).
# pKa expands to two output endpoints (pKa_a acidic, pKa_b basic); the parser reads whatever the header
# actually contains, so this list only drives the `-e` command, never the parse.
DEFAULT_ENDPOINTS: tuple[str, ...] = ("LogP", "LogD", "pKa", "FuB", "Clint", "Caco2")

# Per-endpoint units + direction, for provenance/README cross-reference (VERIFIED, IO_SPEC §1 #21).
ENDPOINT_UNITS: dict[str, str] = {
    "LogP": "log Kow (UP = more lipophilic)",
    "LogD": "log (UP = more lipophilic)",
    "pKa_a": "acidic pKa",
    "pKa_b": "basic pKa",
    "FuB": "fraction unbound (0-1)",
    "Clint": "uL/min/10^6 cells",
    "Caco2": "logPapp",
}


def _provenance(header: list[str] | None = None) -> dict[str, Any]:
    """Provenance stamped onto every emitted record. No version is fabricated: OPERA's exact build is a
    box-run residue (the header of a real preds.txt is carried in ``raw`` so the source build is auditable).
    """
    prov: dict[str, Any] = {
        "model": MODEL,
        "method": "OPERA compiled-MATLAB QSAR consensus models (PaDEL 2D descriptors); out-of-band MCR + Java runtime, parser-only adapter",
        "runtime": "OUT-OF-BAND: MATLAB Compiler Runtime + Java (PaDEL/CDK); env_manifest=None, not driven through core.dispatch",
        "citation": "Mansouri K, et al. OPERA models for predicting physicochemical properties and environmental fate endpoints. J Cheminform 2018, 10:10. doi:10.1186/s13321-018-0263-1",
        "license": "OPERA source MIT (NIEHS/OPERA); MATLAB Compiler Runtime under the MathWorks MCR license (free redistribution)",
        "source": "github.com/NIEHS/OPERA",
    }
    if header is not None:
        prov["preds_header"] = list(header)
    return prov


# --------------------------------------------------------------------------------------------------
# Column classification (header-driven; robust to the _predRange build + verbose neighbour columns)
# --------------------------------------------------------------------------------------------------

def classify_column(col: str) -> tuple[str, str] | None:
    """Map one OPERA column name to ``(endpoint, kind)`` or ``None`` if it is not an endpoint column.

    Order matters: ``AD_index_`` and ``Conf_index_`` are checked before the bare ``AD_`` prefix (they all
    start with ``AD``/``Conf``), and ``_predRange`` is a distinct suffix from ``_pred``.
    """
    if col.startswith("AD_index_"):
        return col[len("AD_index_"):], "ad_index"
    if col.startswith("Conf_index_"):
        return col[len("Conf_index_"):], "conf_index"
    if col.startswith("AD_"):
        return col[len("AD_"):], "ad_in_domain"
    if col.endswith("_predRange"):
        return col[: -len("_predRange")], "pred_range"
    if col.endswith("_pred"):
        return col[: -len("_pred")], "pred"
    return None


def _f(value: Any) -> float | None:
    """Coerce an OPERA cell to a finite float, or ``None`` for missing / ``NaN`` / non-numeric (out of domain)."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in ("nan", "na", "null", "-"):
        return None
    try:
        f = float(s)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _to_bool(value: Any) -> bool | None:
    """OPERA's ``AD_<X>`` flag is 0/1 (1 = inside the applicability domain). Coerce to bool, ``None`` if absent."""
    f = _f(value)
    if f is None:
        return None
    return f != 0.0


def parse_preds(text: str) -> list[dict[str, Any]]:
    """Parse an OPERA ``preds.txt`` (comma-delimited CSV) into per-(molecule, endpoint) OutputRecord dicts.

    THE code deliverable. Pure stdlib; no MCR needed. The first column is the molecule id (whatever OPERA
    names it - ``MoleculeID`` or ``Molecule ID``); every other column is classified by :func:`classify_column`
    and grouped by endpoint. Each (molecule, endpoint) with a ``_pred`` value becomes one record; its
    ``AD_`` / ``AD_index_`` / ``Conf_index_`` land in ``uncertainty`` (``Conf_index`` is a DIRECT
    uncertainty, populated not discarded - CLAUDE.md §4). A ``_predRange`` column, if the build emits one,
    is preserved in ``uncertainty.extra['pred_range']``; unrecognised columns go to ``raw['extra_columns']``.
    """
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if not rows:
        return []

    header = [h.strip() for h in rows[0]]
    if not header:
        return []
    id_col, value_cols = header[0], header[1:]

    # Pre-classify the header once: column index -> (endpoint, kind); collect the ordered endpoint list.
    classified: dict[int, tuple[str, str]] = {}
    endpoints: list[str] = []
    for offset, col in enumerate(value_cols, start=1):
        cls = classify_column(col)
        if cls is None:
            continue
        endpoint, kind = cls
        classified[offset] = (endpoint, kind)
        if kind == "pred" and endpoint not in endpoints:
            endpoints.append(endpoint)

    records: list[dict[str, Any]] = []
    for row in rows[1:]:
        if len(row) < len(header):  # pad short rows so index access is safe
            row = row + [""] * (len(header) - len(row))
        mol_id = row[0].strip()

        # Gather this molecule's cells grouped by endpoint.
        per_endpoint: dict[str, dict[str, Any]] = {ep: {} for ep in endpoints}
        extra_columns: dict[str, str] = {}
        for idx, col in enumerate(header):
            if idx == 0:
                continue
            cls = classified.get(idx)
            cell = row[idx].strip()
            if cls is None:
                if cell:
                    extra_columns[col] = cell
                continue
            endpoint, kind = cls
            per_endpoint.setdefault(endpoint, {})[kind] = cell

        for endpoint in endpoints:
            cells = per_endpoint.get(endpoint, {})
            pred = _f(cells.get("pred"))
            uncertainty: dict[str, Any] = {
                "ad_in_domain": _to_bool(cells.get("ad_in_domain")),
                "ad_index": _f(cells.get("ad_index")),
                "conf_index": _f(cells.get("conf_index")),
                "extra": {},
            }
            if "pred_range" in cells and cells["pred_range"]:
                uncertainty["extra"]["pred_range"] = cells["pred_range"]

            records.append(
                {
                    "model": MODEL,
                    "endpoint_values": {endpoint: pred},
                    "uncertainty": uncertainty,
                    "raw": {
                        "molecule_id": mol_id,
                        "endpoint": endpoint,
                        "units": ENDPOINT_UNITS.get(endpoint, "see README"),
                        "pred_raw": cells.get("pred", ""),
                        "header": id_col,
                        "extra_columns": extra_columns,
                    },
                    "provenance": _provenance(header),
                }
            )
    return records


# --------------------------------------------------------------------------------------------------
# Input side + out-of-band invocation (the MCR path; only runs where the runtime is installed)
# --------------------------------------------------------------------------------------------------

def parse_inputs(text: str) -> list[dict[str, Any]]:
    """Parse the ``--input`` payload (InputRecord JSON object, JSON array, or ``.smi``) into records."""
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        data = json.loads(stripped)
        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return list(data)
        raise ValueError("input JSON must be an object or an array of objects")
    records: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        mol_id = parts[1] if len(parts) > 1 else None
        records.append({"smiles": parts[0], "mol_id": mol_id})
    return records


def write_opera_input(records: list[dict[str, Any]], path: Path) -> None:
    """Write the OPERA ``.smi`` input (``<SMILES><TAB><MoleculeID>`` per line) from parsed input records."""
    lines = []
    for i, rec in enumerate(records):
        smiles = str(rec.get("smiles") or "").strip()
        mol_id = rec.get("mol_id") or f"MOL-{i + 1}"
        if smiles:
            lines.append(f"{smiles}\t{mol_id}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_opera_command(
    opera_home: Path, mcr: Path, in_smi: Path, out_preds: Path, endpoints: tuple[str, ...]
) -> list[str]:
    """Assemble the out-of-band ``run_OPERA.sh`` argv (documented in README; only used when MCR is installed).

    ``run_OPERA.sh <MCR_path> -s in.smi -o preds.txt -e <endpoints...> -v 1`` (IO_SPEC §1 #21). Pure so the
    command is unit-assertable without a runtime present.
    """
    cmd = [str(opera_home / "run_OPERA.sh"), str(mcr), "-s", str(in_smi), "-o", str(out_preds), "-e"]
    cmd += list(endpoints)
    cmd += ["-v", "1"]
    return cmd


def run_opera(
    records: list[dict[str, Any]],
    opera_home: Path,
    mcr: Path,
    endpoints: tuple[str, ...],
    workdir: Path,
) -> str:
    """Run the out-of-band OPERA CLI and return the raw ``preds.txt`` text. Requires the MCR runtime.

    Only reached on the box path (no ``--preds``). It writes the ``.smi`` input, shells out to
    ``run_OPERA.sh``, and reads back the produced ``preds.txt``. The parser (:func:`parse_preds`) then
    turns that text into records - identical to the offline path, so both modes share one parser.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    in_smi = workdir / "opera_in.smi"
    out_preds = workdir / "opera_preds.txt"
    write_opera_input(records, in_smi)
    cmd = build_opera_command(opera_home, mcr, in_smi, out_preds, endpoints)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"run_OPERA.sh exited {proc.returncode}: {(proc.stderr or '').strip()[:500]}")
    if not out_preds.exists():
        raise RuntimeError(f"OPERA exited 0 but wrote no predictions at {out_preds}")
    return out_preds.read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OPERA out-of-band parser/wrapper (uniform model CLI).")
    parser.add_argument("--input", required=True, type=Path, help="pipeline input (InputRecord JSON, JSON array, or .smi)")
    parser.add_argument("--output", required=True, type=Path, help="where to write the OutputRecord JSON")
    parser.add_argument("--gpu", type=int, default=None, help="ignored (OPERA is CPU/MCR); present for the uniform CLI")
    parser.add_argument("--preds", type=Path, default=None, help="parse this already-computed OPERA preds.txt (offline/transcription path; no MCR)")
    parser.add_argument("--opera-home", type=Path, default=os.environ.get("OPERA_HOME"), help="OPERA install dir holding run_OPERA.sh (or $OPERA_HOME)")
    parser.add_argument("--mcr", type=Path, default=os.environ.get("MCR_ROOT"), help="MATLAB Compiler Runtime dir (or $MCR_ROOT)")
    parser.add_argument("--endpoints", nargs="+", default=list(DEFAULT_ENDPOINTS), help="OPERA -e endpoints to request")
    args = parser.parse_args(argv)

    if args.preds is not None:
        # Offline / transcription path: parse an existing preds.txt. No MCR, pure stdlib.
        preds_text = args.preds.read_text(encoding="utf-8")
    else:
        # Box path: needs the out-of-band MCR runtime installed (see README). Refuse clearly if it is not.
        if not args.opera_home or not args.mcr:
            parser.error(
                "no --preds given and OPERA runtime not located: pass --opera-home and --mcr (or set "
                "$OPERA_HOME / $MCR_ROOT), or supply a precomputed --preds preds.txt. OPERA is out-of-band "
                "(MATLAB MCR + Java); see README for the install recipe."
            )
        records = parse_inputs(args.input.read_text(encoding="utf-8"))
        preds_text = run_opera(records, args.opera_home, args.mcr, tuple(args.endpoints), args.output.parent)

    outputs = parse_preds(preds_text)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(outputs, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
