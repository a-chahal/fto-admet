#!/usr/bin/env python
"""aizynthfinder adapter - AiZynthFinder retrosynthesis route search (synthesizability endpoint; shortlist).

Uniform model CLI (CLAUDE.md 2, SETTLED 6):

    python run.py --input <path> --output <path> [--gpu N] [--config <config.yml>]

AiZynthFinder (MolecularAI/aizynthfinder, Genheden et al., J. Cheminform. 2020) is an open-source
computer-aided synthesis planning tool: a Monte-Carlo tree search over a neural template-expansion policy
that tries to find a synthetic route from a target molecule down to purchasable precursors (a "stock").
It is a REAL route search, not a classifier.

Role: the THIRD (top) rung of the synthesizability tier ladder (docs IO_SPEC 1 #26 / #27 / 2):

    SAscore (rung 1)  ->  RAscore (rung 2)  ->  AiZynthFinder (rung 3)
    1-10, lower=easier    P(route findable)     real route search (is_solved bool + routes)

The rungs use different scales and are reported as a tier, NEVER averaged. This is the confirmatory rung,
run on the SHORTLIST only (``in_bulk_loop = False``): it is expensive (a tree search per molecule), so it
confirms the cheap upstream rungs rather than scoring the bulk library.

Output (VERIFIED on the box from aizynthfinder.aizynthfinder.AiZynthFinder.extract_statistics(), which
folds in TreeAnalysis.tree_statistics(); docs IO_SPEC 1 #27):
    endpoint_values = {
        "is_solved": <bool>,                     # route to purchasable precursors found for the top route
        "top_score": <float in 0..1>,            # score of the top-ranked route ("state score"; UP=better)
        "number_of_steps": <int>,                # reaction steps in the top route
        "number_of_routes": <int>,               # distinct routes returned by the search
        "number_of_precursors": <int>,           # leaf precursors of the top route
        "number_of_precursors_in_stock": <int>,  # how many of those are purchasable
        "number_of_nodes": <int>,                # nodes explored in the search tree
    }
    uncertainty = None                            # a route search emits no native uncertainty signal
    raw.routes = [...]                            # full route trees (reaction_tree + scores) per route

LANDMINE (task t32, docs IO_SPEC 1 #27 / 3 F-11): the go/no-go key is ``is_solved``, NOT ``solved``.
``solved`` is an internal per-node key on the search tree; reading it instead of the aggregated
``is_solved`` statistic would silently report every target as unsolved. The go/no-go field is
``is_solved``; survivors are ranked by ``top_score`` and ``number_of_steps``.

LANDMINE (task t32): AiZynthFinder cannot solve anything WITHOUT a configured stock set + a downloaded
expansion policy model. Those (the public USPTO template policy + ZINC stock) are fetched once and CACHED
under /zfs - NEVER committed (CLAUDE.md 0). This adapter does NOT download them at run time: it resolves an
existing ``config.yml`` (see ``_resolve_config`` and the README for the exact cache location + the one-time
download command). If the config is missing it fails loudly rather than silently reporting "unsolved".

This runs in the model's ISOLATED pixi env and so CANNOT import ``core``; it emits plain JSON matching
``core.schemas.OutputRecord`` and the dispatcher validates that JSON on collection.

``--gpu`` is accepted and IGNORED: the shipped ONNX policy runs on onnxruntime (CPU). The uniform CLI is
identical for every model so the dispatcher builds one command.

Robustness: an unparseable / empty SMILES yields a per-record result with a null ``is_solved`` and the
reason in ``raw`` - one bad molecule never sinks a batch.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from pathlib import Path
from typing import Any, Optional

warnings.filterwarnings("ignore")

MODEL = "aizynthfinder"

# The default AiZynthFinder scorer ("state score") is a route score in [0, 1], higher = better.
TOP_SCORE_MIN = 0.0
TOP_SCORE_MAX = 1.0

# The stock + policy live in a config.yml that is CACHED on the box, never committed (CLAUDE.md 0). It is
# resolved (in order) from: --config, $AIZYNTH_CONFIG, then $FTO_ADMET_ENV_CACHE/aizynth-data/config.yml.
# See README for the one-time `download_public_data` step that produces it.
ENV_CACHE_VAR = "FTO_ADMET_ENV_CACHE"
CONFIG_ENV_VAR = "AIZYNTH_CONFIG"
DEFAULT_CONFIG_SUBPATH = "aizynth-data/config.yml"

# The public expansion policy + stock names as configured by upstream `download_public_data` (README).
EXPANSION_KEY = "uspto"
STOCK_KEY = "zinc"
FILTER_KEY = "uspto"


def _provenance(aizynth_version, rdkit_version, config_path):
    # type: (str, str, str) -> dict
    """Provenance stamped onto every emitted record (library versions read live, never hardcoded)."""
    return {
        "model": MODEL,
        "method": "AiZynthFinder: Monte-Carlo tree search retrosynthesis over a neural template-expansion "
        "policy (USPTO) down to a purchasable stock (ZINC). Real route search, not a classifier. Third "
        "(top) rung of the synthesizability tier ladder (SAscore -> RAscore -> AiZynthFinder); shortlist "
        "only, reported as a tier, never averaged. Statistics from AiZynthFinder.extract_statistics(); "
        "go/no-go key is is_solved (NOT solved).",
        "expansion_policy": EXPANSION_KEY,
        "stock": STOCK_KEY,
        "aizynthfinder_version": aizynth_version,
        "rdkit_version": rdkit_version,
        "config": config_path,
        "citation": "Genheden S, Thakkar A, Chadimova V, Reymond J-L, Engkvist O, Bjerrum E. "
        "AiZynthFinder: a fast, robust and flexible open-source software for retrosynthetic planning. "
        "J Cheminform 2020;12:70. doi:10.1186/s13321-020-00472-1",
        "license": "MIT (MolecularAI/aizynthfinder). Public USPTO policy + ZINC stock. Access CODE-PKG.",
    }


def parse_inputs(text):
    # type: (str) -> tuple
    """Parse the ``--input`` payload into ``(records, single)`` (same contract as the t11/t30/t31 template).

    Accepts a single ``InputRecord`` JSON object (``single=True``), a JSON array of them, or a ``.smi``
    file (``<SMILES><whitespace><title>`` per line, ``#`` comments). JSON is detected by trying to parse
    it, so a ``.smi`` line beginning with a bracket atom (e.g. ``[nH]``) is not misread.
    """
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            data = json.loads(stripped)
        except ValueError:
            data = None
        if isinstance(data, dict):
            return [data], True
        if isinstance(data, list):
            return list(data), False
        if data is not None:
            raise ValueError("input JSON must be an object or an array of objects")

    records = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        mol_id = parts[1] if len(parts) > 1 else None
        records.append({"smiles": parts[0], "mol_id": mol_id})
    return records, False


def _resolve_config(cli_config):
    # type: (Optional[Path]) -> Path
    """Resolve the AiZynthFinder config.yml (stock + policy), or raise a loud, actionable error.

    Order: --config, then $AIZYNTH_CONFIG, then $FTO_ADMET_ENV_CACHE/aizynth-data/config.yml. The config
    (and the ONNX policy + ZINC stock it points at) is cached on the box, never committed (CLAUDE.md 0).
    """
    candidates = []
    if cli_config is not None:
        candidates.append(Path(cli_config))
    env_config = os.environ.get(CONFIG_ENV_VAR)
    if env_config:
        candidates.append(Path(env_config))
    env_cache = os.environ.get(ENV_CACHE_VAR)
    if env_cache:
        candidates.append(Path(env_cache) / DEFAULT_CONFIG_SUBPATH)

    for cand in candidates:
        if cand.is_file():
            return cand

    tried = ", ".join(str(c) for c in candidates) or "(none)"
    raise RuntimeError(
        "AiZynthFinder config.yml not found (tried: {0}). It is the cached stock+policy config that is "
        "NEVER committed (CLAUDE.md 0). Produce it once on the box with `download_public_data "
        "$FTO_ADMET_ENV_CACHE/aizynth-data` (or set $AIZYNTH_CONFIG / pass --config). See README.".format(tried)
    )


def _build_finder(config_path):
    # type: (Path) -> Any
    """Instantiate AiZynthFinder from the config and select the public expansion policy + stock.

    The filter policy is OPTIONAL (route-feasibility filter); select it only if the config provides it.
    """
    from aizynthfinder.aizynthfinder import AiZynthFinder

    finder = AiZynthFinder(configfile=str(config_path))
    finder.stock.select(STOCK_KEY)
    finder.expansion_policy.select(EXPANSION_KEY)
    if FILTER_KEY in finder.filter_policy.items:
        finder.filter_policy.select(FILTER_KEY)
    return finder


def _null_record(smiles, mol_id, reason, provenance):
    # type: (str, Any, str, dict) -> dict
    """A valid OutputRecord for a molecule that could not be searched (null is_solved, reason in raw)."""
    return {
        "model": MODEL,
        "endpoint_values": {"is_solved": None, "top_score": None},
        "uncertainty": None,
        "raw": {"error": reason, "smiles": smiles, "mol_id": mol_id},
        "provenance": provenance,
    }


def _as_bool(value):
    # type: (Any) -> Optional[bool]
    """Coerce the aggregated is_solved statistic to a plain bool (it is a single node's bool by default)."""
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    # In multi-objective mode is_solved can be a "|"-joined string; the default single-objective run
    # returns a single value, so anything else is defensive.
    text = str(value).strip().lower()
    if text in ("true", "1"):
        return True
    if text in ("false", "0"):
        return False
    return None


def _as_int(value):
    # type: (Any) -> Optional[int]
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value):
    # type: (Any) -> Optional[float]
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def run(records, config_path):
    # type: (list, Path) -> list
    """Run a route search per record: parse SMILES, tree-search, extract statistics; keep input order."""
    import importlib.metadata as importlib_metadata

    from rdkit import Chem, rdBase

    aizynth_version = importlib_metadata.version("aizynthfinder")
    provenance = _provenance(aizynth_version, rdBase.rdkitVersion, str(config_path))

    finder = _build_finder(config_path)

    outputs = []
    for record in records:
        smiles = str(record.get("smiles") or "").strip()
        mol_id = record.get("mol_id")

        mol = Chem.MolFromSmiles(smiles) if smiles else None
        if mol is None:
            reason = "empty SMILES" if not smiles else "RDKit could not parse SMILES"
            outputs.append(_null_record(smiles, mol_id, reason, provenance))
            continue

        try:
            finder.target_smiles = smiles
            finder.tree_search()
            finder.build_routes()
            stats = finder.extract_statistics()
            routes = finder.routes.dict_with_scores()
        except Exception as exc:  # noqa: BLE001 - one failed search degrades to a null record, never a crash
            reason = "route search failed: {0}: {1}".format(type(exc).__name__, exc)
            outputs.append(_null_record(smiles, mol_id, reason, provenance))
            continue

        # LANDMINE: the go/no-go key is is_solved, NOT solved.
        is_solved = _as_bool(stats.get("is_solved"))
        top_score = _as_float(stats.get("top_score"))

        outputs.append(
            {
                "model": MODEL,
                "endpoint_values": {
                    "is_solved": is_solved,
                    "top_score": top_score,
                    "number_of_steps": _as_int(stats.get("number_of_steps")),
                    "number_of_routes": _as_int(stats.get("number_of_routes")),
                    "number_of_precursors": _as_int(stats.get("number_of_precursors")),
                    "number_of_precursors_in_stock": _as_int(stats.get("number_of_precursors_in_stock")),
                    "number_of_nodes": _as_int(stats.get("number_of_nodes")),
                },
                # A route search emits no native aleatoric/epistemic signal (schema rule CLAUDE.md 3: the
                # reserved uncertainty fields stay null rather than fabricated).
                "uncertainty": None,
                "raw": {
                    "smiles": smiles,
                    "mol_id": mol_id,
                    # The full per-target statistics dict (search_time, precursors_in_stock strings, ...).
                    "statistics": stats,
                    # Full route trees (reaction_tree + all_scores + route_metadata) for the raw-output cache.
                    "routes": routes,
                    "scale": {
                        "top_score": {
                            "min": TOP_SCORE_MIN,
                            "max": TOP_SCORE_MAX,
                            "direction": "higher = better route (default state score)",
                        },
                        "is_solved": "True = a route to purchasable precursors was found",
                    },
                    "tier": "synthesizability rung 3 of 3 (SAscore -> RAscore -> AiZynthFinder); shortlist only",
                },
                "provenance": provenance,
            }
        )
    return outputs


def main(argv=None):
    # type: (Optional[list]) -> int
    parser = argparse.ArgumentParser(
        description="AiZynthFinder retrosynthesis route-search adapter (uniform model CLI)."
    )
    parser.add_argument("--input", required=True, type=Path, help="pipeline input (InputRecord JSON, JSON array, or .smi)")
    parser.add_argument("--output", required=True, type=Path, help="where to write the OutputRecord JSON")
    parser.add_argument("--gpu", type=int, default=None, help="ignored (ONNX policy runs on CPU); present for the uniform CLI")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="AiZynthFinder config.yml (stock+policy); default resolves $AIZYNTH_CONFIG then $FTO_ADMET_ENV_CACHE/aizynth-data/config.yml",
    )
    args = parser.parse_args(argv)

    config_path = _resolve_config(args.config)

    records, single = parse_inputs(args.input.read_text(encoding="utf-8"))
    outputs = run(records, config_path)
    payload = outputs[0] if (single and len(outputs) == 1) else outputs

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
