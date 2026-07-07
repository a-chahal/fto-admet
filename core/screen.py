"""Screen one or many molecules across every ADMET endpoint - the single entry point.

The whole point is SPEED. Each model is dispatched EXACTLY ONCE over the entire set of molecules (every
adapter accepts a batch and emits one record per input, in order), and its outputs are then reused across
every endpoint it feeds. So the expensive model-load cost is paid |models| times total, NOT
|models| x |endpoints| x |molecules|. A cross-cutting model like admet_ai loads once for the whole run
instead of ~10 times per molecule.

    python -m core.screen --smiles "CCO" [--mol-id ethanol] [--out card.json]
    python -m core.screen --input molecules.smi --out cards.json   # many molecules -> a list of cards

Output is a JSON card per molecule: for each endpoint, the models that ran, any failures, and the
aggregator's fused verdict.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from core import dispatch
from core.config import Config, get_config
from core.dispatch import DispatchError
from core.models import Endpoint
from core.run import aggregate_records, select_models


def _card_for(
    inp: dict[str, Any],
    endpoints_specs: dict[Endpoint, list],
    model_recs: dict[Any, list],
    index: int,
    failures_by_model: dict[Any, str],
) -> dict[str, Any]:
    """Assemble one molecule's ADMET card by reusing the already-dispatched batch records."""
    card: dict[str, Any] = {"smiles": inp["smiles"], "mol_id": inp.get("mol_id"), "endpoints": {}}
    for ep in Endpoint:
        recs: list = []
        ran: list[str] = []
        fails: list[dict[str, str]] = []
        for spec in endpoints_specs[ep]:
            if spec.name in failures_by_model:
                fails.append({"model": spec.name.value, "reason": failures_by_model[spec.name]})
                continue
            rec = model_recs[spec.name][index] if spec.name in model_recs else None
            if rec is not None:
                recs.append(rec)
                ran.append(spec.name.value)
        verdict, note = aggregate_records(ep, recs, mol_id=inp.get("mol_id") or f"mol_{index}")
        if hasattr(verdict, "model_dump"):
            verdict = verdict.model_dump(mode="json")
        card["endpoints"][ep.value] = {"models_run": ran, "failures": fails, "verdict": verdict, "note": note}
    return card


def screen_batch(
    molecules: list[dict[str, Any]],
    *,
    config: Config | None = None,
    out_dir: str | Path | None = None,
    max_workers: int | None = None,
    per_model_timeout: float | None = None,
) -> list[dict[str, Any]]:
    """Screen many molecules fast: dispatch each model ONCE over the batch, then aggregate per molecule.

    Models are independent, so they are dispatched CONCURRENTLY (``max_workers`` threads, each awaiting one
    model's subprocess): wall-clock is the slowest single model, not the sum. ``per_model_timeout`` (seconds)
    caps each model so one pathologically slow model is dropped instead of stalling the run.
    """
    cfg = config if config is not None else get_config()
    inputs = [{"smiles": str(m["smiles"]).strip(), "mol_id": m.get("mol_id")} for m in molecules]
    if not inputs:
        return []
    base = Path(out_dir) if out_dir is not None else Path(cfg.outputs)

    # Every endpoint's bulk-loop models, and the de-duplicated union to dispatch (each model exactly once).
    endpoints_specs = {ep: select_models(ep) for ep in Endpoint}
    unique: dict[Any, Any] = {}
    for ep in Endpoint:
        for spec in endpoints_specs[ep]:
            unique.setdefault(spec.name, spec)

    model_recs: dict[Any, list] = {}
    failures_by_model: dict[Any, str] = {}

    def _dispatch(name):
        return dispatch.run_model_batch(name, inputs, base / "batch", config=cfg, timeout=per_model_timeout)

    workers = max_workers or min(len(unique), (os.cpu_count() or 8))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_dispatch, name): name for name in unique}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                model_recs[name] = fut.result()
            except DispatchError as exc:
                # One model failing (web-only, missing env, timeout, bad batch) never sinks the run; it is
                # dropped and every endpoint it feeds records the failure. The rest of the card assembles.
                failures_by_model[name] = str(exc)
            except Exception as exc:  # defensive: an unexpected error in one model stays isolated
                failures_by_model[name] = f"{type(exc).__name__}: {exc}"

    return [_card_for(inp, endpoints_specs, model_recs, i, failures_by_model) for i, inp in enumerate(inputs)]


def screen(
    smiles: str,
    mol_id: str | None = None,
    *,
    config: Config | None = None,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Screen ONE molecule into one card. Delegates to :func:`screen_batch`, so each model dispatches once."""
    return screen_batch([{"smiles": smiles, "mol_id": mol_id}], config=config, out_dir=out_dir)[0]


def _read_molecules(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Resolve the molecule list from --smiles, or a --input .smi / InputRecord JSON (object or array)."""
    if args.smiles:
        return [{"smiles": args.smiles.strip(), "mol_id": args.mol_id}]
    text = Path(args.input).read_text(encoding="utf-8").strip()
    if text.startswith("[") or text.startswith("{"):
        data = json.loads(text)
        rows = data if isinstance(data, list) else [data]
        return [{"smiles": str(d["smiles"]).strip(), "mol_id": d.get("mol_id")} for d in rows]
    mols: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        mols.append({"smiles": parts[0], "mol_id": parts[1] if len(parts) > 1 else None})
    return mols


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m core.screen",
                                description="Screen one or many molecules across all ADMET endpoints "
                                            "(each model is dispatched once over the whole set).")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--smiles", help="a single molecule SMILES to screen")
    src.add_argument("--input", type=Path, help="a .smi file or InputRecord JSON (object or array) of molecules")
    p.add_argument("--mol-id", default=None, help="optional label when using --smiles")
    p.add_argument("--out", type=Path, default=None, help="write the card(s) JSON here (default: stdout)")
    p.add_argument("--timeout", type=float, default=None,
                   help="per-model seconds cap; a slower model is dropped and recorded as a failure")
    p.add_argument("--workers", type=int, default=None,
                   help="max concurrent model dispatches (default: cpu count)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    molecules = _read_molecules(args)
    cards = screen_batch(molecules, max_workers=args.workers, per_model_timeout=args.timeout)
    # --smiles -> a single card object; --input -> a list (even for one molecule), so batch output is stable.
    payload: Any = cards[0] if (args.smiles and len(cards) == 1) else cards
    text = json.dumps(payload, indent=2, default=str)
    if args.out is not None:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {len(cards)} card(s) -> {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
