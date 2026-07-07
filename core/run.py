"""Run one endpoint end to end: enumerate its bulk-loop models, dispatch each, then aggregate.

This is the second of the two *generic and singular* drivers (CLAUDE.md §2, SETTLED §6): like
:mod:`core.dispatch`, it does not grow with the number of endpoints or models. The only endpoint
specific code in the whole pipeline is the N ``endpoints/<ep>/aggregate.py`` files; this module never
branches per endpoint. Adding an endpoint is a folder plus an aggregator, never an edit here.

The flow, per endpoint (SETTLED §6, line 182):

    select models  ->  dispatch each  ->  hand the collected outputs to that endpoint's aggregate.py

Selection is exactly the contract query::

    [spec for spec in REGISTRY.values() if endpoint in spec.endpoints and spec.in_bulk_loop]

``in_bulk_loop`` is what keeps the web-only / shortlist models (``watanabe_*``, ``protox``,
``ctoxpred2``, ``cardiogenai``, ``aizynthfinder``, ``pbpk``) out of the automatic enumeration; they are
run out of band and transcribed by hand. Cross-cutting models (``admet_ai``, ``admetlab3``,
``boiled_egg``, ``opera``, ``pgp``) carry several endpoints in their ``endpoints`` set, so the same
model is legitimately dispatched under each endpoint it feeds (IO_SPEC §2).

The aggregator runs in the **core** env on already-collected outputs, never on the models' mutually
incompatible deps (SETTLED §3). It is loaded dynamically by convention (``endpoints/<ep>/aggregate.py``
exposing ``aggregate(records: list[OutputRecord])``); an endpoint whose aggregator has not been built
yet is tolerated, and :func:`run_endpoint` returns the raw records with a note instead of crashing.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core import dispatch
from core.config import Config, get_config
from core.dispatch import DispatchError
from core.models import Endpoint, ModelName
from core.registry import REGISTRY, ModelSpec
from core.schemas import OutputRecord

# The aggregator convention: endpoints/<endpoint>/aggregate.py exposes a callable of this name taking
# the collected list[OutputRecord]. run_endpoint hands it every dispatched model's output; its return
# (an endpoint-specific fused object of any shape) is carried on EndpointResult.aggregate.
AGGREGATE_MODULE = "endpoints.{endpoint}.aggregate"
AGGREGATE_ENTRY = "aggregate"


@dataclass(frozen=True)
class EndpointResult:
    """The outcome of running one endpoint: the raw model outputs plus the aggregator's fused result.

    ``records`` is always populated (one :class:`OutputRecord` per model that dispatched successfully),
    independent of whether an aggregator exists, so a not-yet-built endpoint still returns useful data.
    ``aggregate`` is whatever that endpoint's ``aggregate.py`` returned, or ``None`` when no aggregator
    is present. ``failures`` records ``(model, reason)`` for any model whose dispatch raised, so one bad
    model never sinks the whole endpoint. ``note`` carries a human-readable status (e.g. the missing
    aggregator explanation).
    """

    endpoint: Endpoint
    records: list[OutputRecord]
    aggregate: Any = None
    failures: list[tuple[ModelName, str]] = field(default_factory=list)
    note: str | None = None

    def to_summary(self) -> dict[str, Any]:
        """A JSON-serializable summary for the CLI. ``aggregate`` is best-effort (may not be JSON-able)."""
        agg = self.aggregate
        if hasattr(agg, "model_dump"):
            agg = agg.model_dump(mode="json")  # a pydantic aggregator result
        return {
            "endpoint": self.endpoint.value,
            "models": [r.model.value for r in self.records],
            "num_records": len(self.records),
            "failures": [{"model": m.value, "reason": reason} for m, reason in self.failures],
            "aggregate": agg,
            "note": self.note,
        }


def select_models(endpoint: Endpoint) -> list[ModelSpec]:
    """The registry query that drives the bulk loop (SETTLED §6): endpoint members that opt into it.

    ``endpoint in spec.endpoints`` picks every model that feeds this endpoint (including the
    cross-cutting ones); ``spec.in_bulk_loop`` drops the web-only / shortlist models that are run out of
    band. Order follows ``REGISTRY`` insertion order so a run is deterministic.
    """
    return [
        spec
        for spec in REGISTRY.values()
        if endpoint in spec.endpoints and spec.in_bulk_loop
    ]


def load_aggregator(endpoint: Endpoint) -> Any | None:
    """Resolve ``endpoints/<endpoint>/aggregate.py``'s ``aggregate`` callable, or ``None`` if not built.

    A genuinely absent aggregator (module or its ``endpoints`` package not importable, or the module
    present but missing the ``aggregate`` entry) is *not* an error: the endpoint simply has not been
    built yet. An :class:`ImportError` raised from *inside* an existing aggregator module (a real bug in
    that code) is deliberately left to propagate, not masked as "not built".
    """
    module_name = AGGREGATE_MODULE.format(endpoint=endpoint.value)
    try:
        spec = importlib.util.find_spec(module_name)
    except ModuleNotFoundError:
        return None  # the endpoints package (or endpoints.<ep>) does not exist yet
    if spec is None:
        return None
    module = importlib.import_module(module_name)
    entry = getattr(module, AGGREGATE_ENTRY, None)
    return entry if callable(entry) else None


def run_endpoint(
    endpoint: Endpoint,
    input: Any,
    *,
    out: str | Path | None = None,
    config: Config | None = None,
) -> EndpointResult:
    """Run every bulk-loop model for ``endpoint`` and hand the collected outputs to its aggregator.

    Selects models via :func:`select_models`, dispatches each through :func:`core.dispatch.run_model`
    (which validates, resolves the env, claims a GPU when needed, shells out, and ledgers), then loads
    the endpoint's aggregator and calls ``aggregate(records)``. A model whose dispatch raises
    :class:`DispatchError` is recorded in ``failures`` and skipped - the failure is already on the ledger
    by then - so the remaining models still run. A missing aggregator yields the raw records plus an
    explanatory ``note`` rather than a crash.

    Args:
        endpoint: the screening endpoint to run.
        input: the input payload (dict or ``InputRecord``); dispatch validates it per model.
        out: directory for the per-model input/output files; defaults to ``<outputs>/<endpoint>``.
        config: injected machine paths; defaults to the process ``Config``.

    Returns:
        An :class:`EndpointResult` with the collected records, the aggregator's result (or ``None``),
        any per-model failures, and a status note.
    """
    if out is None:
        cfg = config if config is not None else get_config()
        out_dir = Path(cfg.outputs) / endpoint.value
    else:
        out_dir = Path(out)

    specs = select_models(endpoint)
    records: list[OutputRecord] = []
    failures: list[tuple[ModelName, str]] = []
    for spec in specs:
        try:
            records.append(dispatch.run_model(spec.name, input, out_dir, config=config))
        except DispatchError as exc:
            # The fail is already ledgered inside run_model; capture it and keep the endpoint going.
            failures.append((spec.name, str(exc)))

    mol_id = (input.get("mol_id") if isinstance(input, dict) else getattr(input, "mol_id", None)) or "mol"
    aggregate_result, note = aggregate_records(endpoint, records, mol_id=mol_id)
    return EndpointResult(endpoint=endpoint, records=records, aggregate=aggregate_result,
                          failures=failures, note=note)


def aggregate_records(
    endpoint: Endpoint,
    records: list[OutputRecord],
    *,
    mol_id: str = "mol",
) -> tuple[Any, str | None]:
    """Load ``endpoint``'s aggregator and run it over one molecule's ``records``; return ``(result, note)``.

    Shared by :func:`run_endpoint` (single molecule, just-dispatched) and the batch screen (which dispatches
    each model once and reuses the records). A missing aggregator returns ``(None, <note>)``. Every
    aggregator takes the one shared input contract (``{mol_id: records}``; see
    :func:`core.aggregate.normalize_molecules`) and returns a ``.molecules`` batch; for this single molecule
    the one per-molecule result is pulled out and returned.
    """
    aggregator = load_aggregator(endpoint)
    if aggregator is None:
        return None, (
            f"no aggregator for endpoint '{endpoint.value}' "
            f"(endpoints/{endpoint.value}/aggregate.py not built yet); returning raw records"
        )
    result = aggregator({mol_id: records})
    molecules = getattr(result, "molecules", None)
    if isinstance(molecules, list) and molecules:
        return molecules[0], None
    return result, None


# --------------------------------------------------------------------------- CLI

def _load_input(path: Path) -> Any:
    """Read the ``--input`` JSON payload; dispatch does the real (pydantic) validation per model."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _resolve_out(out: Path | None, config: Config | None = None) -> Path:
    """Default a missing ``--out`` to the configured outputs dir (real run: needs machine paths)."""
    if out is not None:
        return out
    cfg = config if config is not None else get_config()
    return Path(cfg.outputs)


def build_parser() -> argparse.ArgumentParser:
    """The ``python -m core.run`` argument parser: run a whole endpoint, or a single model with --model."""
    parser = argparse.ArgumentParser(
        prog="python -m core.run",
        description="Run an ADMET endpoint (enumerate its bulk-loop models, dispatch, aggregate), "
                    "or a single model with --model.",
    )
    parser.add_argument("--endpoint", type=Endpoint, choices=list(Endpoint),
                        help="endpoint to run (enumerate + dispatch + aggregate its bulk-loop models)")
    parser.add_argument("--model", type=ModelName, choices=list(ModelName),
                        help="run just this one model via dispatch (bypasses endpoint enumeration)")
    parser.add_argument("--input", required=True, type=Path,
                        help="path to the input JSON payload (an InputRecord)")
    parser.add_argument("--out", type=Path, default=None,
                        help="output directory for per-model input/output files "
                             "(default: the configured outputs dir)")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code: non-zero on any failure.

    ``--model`` runs a single model through :func:`core.dispatch.run_model`; otherwise ``--endpoint``
    runs the whole endpoint. Results are printed as JSON to stdout (the per-model outputs are also
    persisted under ``--out`` by dispatch).
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.endpoint is None and args.model is None:
        parser.error("one of --endpoint or --model is required")

    payload = _load_input(args.input)

    if args.model is not None:
        out_dir = _resolve_out(args.out)
        try:
            record = dispatch.run_model(args.model, payload, out_dir)
        except DispatchError as exc:
            print(json.dumps({"model": args.model.value, "status": "fail", "error": str(exc)}), file=sys.stderr)
            return 1
        print(json.dumps(record.model_dump(mode="json"), indent=2))
        return 0

    result = run_endpoint(args.endpoint, payload, out=args.out)
    print(json.dumps(result.to_summary(), indent=2, default=str))
    return 1 if result.failures else 0


if __name__ == "__main__":
    sys.exit(main())
