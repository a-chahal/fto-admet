"""Screen ONE molecule across every ADMET endpoint - the single-SMILES entry point.

This is the one place a user passes a SMILES. It runs each :class:`~core.models.Endpoint`'s bulk-loop
models (via :func:`core.run.run_endpoint`: dispatch each model, then hand the collected outputs to that
endpoint's aggregator) and assembles every endpoint's verdict into ONE consolidated ADMET card.

    python -m core.screen --smiles "CC(=O)O" --mol-id FTO-43
    python -m core.screen --input tests/fixtures/fto43.smi --out card.json

Model dispatch shells out to each model's isolated pixi env (box only; CLAUDE.md 0). An endpoint whose
models are absent / fail is still reported - its ``failures`` list is populated and its aggregator runs on
whatever collected, so the card always assembles. The card is JSON: per endpoint, the models that ran, any
failures, and the aggregator's fused verdict.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from core.config import Config, get_config
from core.models import Endpoint
from core.run import run_endpoint


def _read_smiles(args: argparse.Namespace) -> tuple[str, str | None]:
    """Resolve (smiles, mol_id) from --smiles or the first data line of a --input .smi / InputRecord JSON."""
    if args.smiles:
        return args.smiles.strip(), args.mol_id
    text = Path(args.input).read_text(encoding="utf-8").strip()
    if text.startswith("{"):
        d = json.loads(text)
        return str(d["smiles"]).strip(), d.get("mol_id", args.mol_id)
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        return parts[0], (parts[1] if len(parts) > 1 else args.mol_id)
    raise SystemExit("no SMILES found in --input")


def screen(smiles: str, mol_id: str | None = None, *, config: Config | None = None,
           out_dir: str | Path | None = None) -> dict[str, Any]:
    """Run every endpoint for one molecule and return the consolidated ADMET card (a plain dict)."""
    cfg = config if config is not None else get_config()
    payload = {"smiles": smiles, "mol_id": mol_id}
    card: dict[str, Any] = {"smiles": smiles, "mol_id": mol_id, "endpoints": {}}
    for ep in Endpoint:
        base = Path(out_dir) / ep.value if out_dir is not None else None
        result = run_endpoint(ep, payload, out=base, config=cfg)
        agg = result.aggregate
        if hasattr(agg, "model_dump"):
            agg = agg.model_dump(mode="json")
        card["endpoints"][ep.value] = {
            "models_run": [r.model.value for r in result.records],
            "failures": [{"model": m.value, "reason": reason} for m, reason in result.failures],
            "verdict": agg,
            "note": result.note,
        }
    return card


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m core.screen",
                                description="Screen one molecule across all ADMET endpoints (one SMILES in, "
                                            "one consolidated ADMET card out).")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--smiles", help="the molecule SMILES to screen")
    src.add_argument("--input", type=Path, help="a .smi file or an InputRecord JSON (first molecule is used)")
    p.add_argument("--mol-id", default=None, help="optional molecule id/label for the card")
    p.add_argument("--out", type=Path, default=None, help="write the card JSON here (default: stdout)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    smiles, mol_id = _read_smiles(args)
    card = screen(smiles, mol_id)
    text = json.dumps(card, indent=2, default=str)
    if args.out is not None:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote ADMET card for {smiles!r} -> {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
