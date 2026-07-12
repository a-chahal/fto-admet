"""CLI: train one feature's fusion spec from its recipe. `python -m training.train_endpoint --feature ep__feat`.

Orchestrates the flow (README): recipe -> clean data -> leakage subtraction -> box-screen features ->
split -> per-source calibration -> fusion weights -> normalized conformal -> write the committed spec.

The fit/conformal math (training.fit, training.conformal) is real and standalone. The data ingress
(training.datasets loaders, training.features box-screen, the exclusion index) is wired per source as we
download them - those are the only integration points left. Nothing here is ever hand-tuned into a spec.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from core.fusion.spec import (
    Fusion,
    FusionSpec,
    Provenance,
    SourceCalibration,
    Target,
    UncertaintySpec,
)
from training import conformal, features
from training import datasets as ds
from training import fit as fitmod

_REPO = Path(__file__).resolve().parent.parent
_RECIPES = _REPO / "training" / "recipes"
_SPECS = _REPO / "core" / "fusion" / "specs"


def _load_recipe(name: str) -> dict[str, Any]:
    path = _RECIPES / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no recipe at {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _git_sha() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=_REPO, capture_output=True, text=True).stdout.strip()


def _hash_df(df: pd.DataFrame) -> str:
    return "sha256:" + hashlib.sha256(pd.util.hash_pandas_object(df, index=True).values.tobytes()).hexdigest()[:16]


# Registry model name -> the name used in the exclusion index. ochem_ppb / bbb_score are GAPS (not in the
# index: OCHEM is behind a login wall, BBB Score behind an ACS paywall), so their training molecules cannot
# be subtracted - surfaced as a warning + stamped in the spec, never silently ignored.
INDEX_MODEL_NAME: dict[str, str] = {
    "admet_ai": "ADMET-AI_v2", "opera": "OPERA", "pksmart": "PKSmart",
    "bayesherg": "BayeshERG", "cardiotox_net": "CardioTox", "cardiogenai": "CardioGenAI",
    "boiled_egg": "BOILED-Egg",
}
INDEX_GAPS: frozenset[str] = frozenset({"ochem_ppb", "bbb_score"})


def _subtract_leakage(
    data: pd.DataFrame, exclude_models: list[str], index_path: Path
) -> tuple[pd.DataFrame, list[str]]:
    """Drop rows whose InChIKey is in any excluded model's training union. Returns (kept, unsubtractable_gaps).

    Model names are mapped registry -> index. A contributing model that is not in the index (OCHEM PPB,
    BBB Score) cannot be subtracted; it is returned in the gap list so the caller records the residual
    contamination risk on the spec rather than pretending the set is fully clean.
    """
    if not index_path.exists():
        raise FileNotFoundError(
            f"exclusion index not found at {index_path}; run the exclusion-index builder first."
        )
    idx = pd.read_parquet(index_path)
    index_names, gaps = [], []
    for m in exclude_models:
        if m in INDEX_MODEL_NAME:
            index_names.append(INDEX_MODEL_NAME[m])
        elif m in INDEX_GAPS:
            gaps.append(m)
        else:
            raise KeyError(f"no exclusion-index mapping for model {m!r} (add it to INDEX_MODEL_NAME)")
    if gaps:
        print(f"WARNING: cannot subtract training molecules for {gaps} (not in the exclusion index); "
              f"residual contamination possible - stamped on the spec.")
    tainted = set(idx.loc[idx["model"].isin(index_names), "inchikey"])
    kept = data[~data["inchikey"].isin(tainted)].copy()
    return kept, sorted(gaps)


def train(feature_key: str, *, root: Path, alpha_default: float = 0.1) -> FusionSpec:
    """Train one feature end to end and write ``core/fusion/specs/<feature_key>.json``. Returns the spec."""
    r = _load_recipe(feature_key)
    endpoint, feature = r["endpoint"], r["feature"]
    tgt, srcs = r["target"], r["sources"]
    unc_cfg = r.get("uncertainty", {})

    # 1-2. clean data (standardized, with inchikey + label), then 3. subtract leakage.
    data = ds.load(tgt["dataset"])
    data, gaps = _subtract_leakage(data, r.get("leakage", {}).get("exclude_models", []),
                                   root / "training" / "exclusion_index" / "index.parquet")
    if len(data) < 50:
        raise RuntimeError(f"{feature_key}: only {len(data)} clean molecules after subtraction; too few.")

    # 4. box-screen -> feature matrix X (one column per contributing model), joined to the label y.
    X = features.load_or_build_features(
        data, endpoint=endpoint, feature=feature,
        cache=root / "training" / "features" / f"{feature_key}.parquet",
    )
    models = [s["model"] for s in srcs]
    df = X.join(data.set_index("mol_id")[[tgt["label_column"], "inchikey"]], how="inner").dropna(subset=models)
    y = df[tgt["label_column"]].to_numpy(dtype=float)

    # 5. per-source calibration + fusion weights on a train split; conformal on a calibration split.
    rng = np.random.default_rng(0)
    perm = rng.permutation(len(df))
    cut = int(0.8 * len(df))
    tr, cal = perm[:cut], perm[cut:]

    calibrated_cols, source_specs = [], []
    for s in srcs:
        x = df[s["model"]].to_numpy(dtype=float)
        params = fitmod.calibrate_source(x[tr], y[tr], s["calibration"])
        gx = fitmod._apply_calibration(x, s["calibration"], params)
        calibrated_cols.append(gx)
        source_specs.append(SourceCalibration(model=s["model"], kind=s["calibration"], params=params,
                                              impute_value=float(np.mean(gx[tr]))))
    C = np.column_stack(calibrated_cols)
    weights, intercept = fitmod.fit_fusion(C[tr], y[tr], method=r["fusion"]["method"],
                                           regularization=r["fusion"].get("regularization") or 0.1)
    pred = C @ np.array([weights[i] for i in range(len(srcs))]) + intercept

    # normalized conformal on the calibration split (scale = calibrated disagreement std per row).
    scale = C.std(axis=1) if C.shape[1] > 1 else np.zeros(len(df))
    floor = unc_cfg.get("scale_floor", 0.0)
    Q = conformal.normalized_conformal_quantile(y[cal] - pred[cal], scale[cal],
                                                alpha=unc_cfg.get("alpha", alpha_default), floor=floor)
    coverage = conformal.empirical_coverage(y[cal] - pred[cal], scale[cal], Q, floor=floor)

    # 6. assemble + write the spec.
    spec = FusionSpec(
        feature=feature, endpoint=endpoint,
        target=Target(name=tgt["name"], units=tgt.get("units", ""), transform=tgt.get("transform", "identity")),
        sources=source_specs,
        fusion=Fusion(weights={srcs[i]["model"]: weights[i] for i in range(len(srcs))},
                      intercept=intercept, method=r["fusion"]["method"],
                      regularization=r["fusion"].get("regularization")),
        uncertainty=UncertaintySpec(method=unc_cfg.get("method", "none"), alpha=unc_cfg.get("alpha", alpha_default),
                                    quantile=Q, scale=unc_cfg.get("scale", "disagreement_std"),
                                    scale_floor=floor, constant_width=unc_cfg.get("constant_width")),
        provenance=Provenance(
            dataset=tgt["dataset"], dataset_hash=_hash_df(data),
            n_train=int(cut), n_calib=int(len(df) - cut),
            metrics={"mae": float(np.mean(np.abs(y[cal] - pred[cal]))), "conformal_coverage": coverage},
            git_sha=_git_sha(),
            notes=(f"unsubtractable contributors (not in exclusion index): {gaps}" if gaps else None),
        ),
    )
    _SPECS.mkdir(parents=True, exist_ok=True)
    (_SPECS / f"{feature_key}.json").write_text(spec.model_dump_json(indent=2), encoding="utf-8")
    return spec


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m training.train_endpoint")
    p.add_argument("--feature", required=True, help="recipe/spec key, e.g. solubility__aqueous_solubility")
    p.add_argument("--root", type=Path, default=None, help="FTO_ADMET_ROOT (/zfs) for data + index + features")
    args = p.parse_args(argv)
    root = args.root or Path(__import__("os").environ.get("FTO_ADMET_ROOT", "."))
    spec = train(args.feature, root=root)
    print(f"wrote core/fusion/specs/{args.feature}.json  coverage={spec.provenance.metrics.get('conformal_coverage')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
