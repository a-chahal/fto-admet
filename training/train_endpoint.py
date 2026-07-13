"""CLI: train one feature's fusion spec from its recipe. `python -m training.train_endpoint --feature ep__feat`.

Flow (README): recipe -> clean data -> leakage subtraction -> box-dispatch the contributing models ->
3-way split (train / calibration / test) -> per-source calibration + fusion weights (train) -> normalized
conformal (calibration) -> HONEST metrics on the held-out test set -> write the committed spec.

The fit/conformal math is real and standalone; the data ingress (datasets loaders, features dispatch, the
exclusion index) is wired here. A spec is never hand-tuned - only written by this trainer.
"""

from __future__ import annotations

import argparse
import hashlib
import os
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
from training import conformal, features, split
from training import datasets as ds
from training.datasets import biogen  # noqa: F401  (import registers the biogen loader)
from training.datasets import chembl_herg  # noqa: F401  (registers the temporal hERG loader)
from training.datasets import kpuu  # noqa: F401  (registers the Kp,uu,brain compilation loader)
from training.datasets import chembl_logd  # noqa: F401  (registers the ChEMBL logD loader)
from training.datasets import catmos  # noqa: F401  (registers the CATMoS LD50 loader)
from training.datasets import cpdb  # noqa: F401  (registers the CPDB carcinogenicity loader)
from training.datasets import dilirank  # noqa: F401  (registers the DILIrank loader)
from training.datasets import hansen_ames  # noqa: F401  (registers the Hansen Ames loader)
from training.datasets import niceatm_llna  # noqa: F401  (registers the NICEATM LLNA loader)
from training.datasets import tox21_original  # noqa: F401  (registers the Tox21 loader)
from training.datasets import fda_cl  # noqa: F401  (registers the FDA temporal CL loader)
from training import fit as fitmod

_REPO = Path(__file__).resolve().parent.parent
_RECIPES = _REPO / "training" / "recipes"
_SPECS = _REPO / "core" / "fusion" / "specs"

INDEX_MODEL_NAME: dict[str, str] = {
    "admet_ai": "ADMET-AI_v2", "opera": "OPERA", "pksmart": "PKSmart",
    "bayesherg": "BayeshERG", "cardiotox_net": "CardioTox", "cardiogenai": "CardioGenAI",
    "boiled_egg": "BOILED-Egg",
}
INDEX_GAPS: frozenset[str] = frozenset({"ochem_ppb", "bbb_score"})


def _load_recipe(name: str) -> dict[str, Any]:
    path = _RECIPES / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no recipe at {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _git_sha() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=_REPO, capture_output=True, text=True).stdout.strip()


def _hash_df(df: pd.DataFrame) -> str:
    return "sha256:" + hashlib.sha256(pd.util.hash_pandas_object(df, index=True).values.tobytes()).hexdigest()[:16]


def _subtract_leakage(
    data: pd.DataFrame, exclude_models: list[str], index_path: Path
) -> tuple[pd.DataFrame, list[str]]:
    """Drop rows whose InChIKey is in any excluded model's training union. Returns (kept, unsubtractable_gaps)."""
    if not index_path.exists():
        raise FileNotFoundError(f"exclusion index not found at {index_path}; build it first.")
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
        print(f"WARNING: cannot subtract {gaps} (not in the exclusion index); residual contamination possible.")
    tainted = set(idx.loc[idx["model"].isin(index_names), "inchikey"])
    kept = data[~data["inchikey"].isin(tainted)].copy()
    return kept, sorted(gaps)


def _scale(C: np.ndarray, unc_cfg: dict[str, Any]) -> np.ndarray:
    """Per-row conformal scale u(x): calibrated disagreement std (multi-source) or a constant (single)."""
    if unc_cfg.get("scale") == "constant" or C.shape[1] < 2:
        return np.full(C.shape[0], float(unc_cfg.get("constant_width", 1.0)))
    return C.std(axis=1)


def train(feature_key: str, *, root: Path) -> FusionSpec:
    """Train one feature end to end and write ``core/fusion/specs/<feature_key>.json``."""
    r = _load_recipe(feature_key)
    endpoint, feature = r["endpoint"], r["feature"]
    tgt, srcs, unc_cfg = r["target"], r["sources"], r.get("uncertainty", {})
    models = [s["model"] for s in srcs]

    # 1-3. clean data (standardized, label column) -> subtract leakage.
    data = ds.load(tgt["dataset"], **tgt.get("loader_kwargs", {}))
    data, gaps = _subtract_leakage(data, r.get("leakage", {}).get("exclude_models", []),
                                   root / "training" / "exclusion_index" / "index.parquet")
    if len(data) < 100:
        raise RuntimeError(f"{feature_key}: only {len(data)} clean molecules after subtraction; too few.")

    # 4. dispatch the contributing models -> harmonized feature matrix, joined to the label.
    X = features.load_or_build_features(
        data, endpoint=endpoint, feature=feature, models=models,
        cache=root / "training" / "features" / f"{feature_key}.parquet",
    )
    df = X.join(data.set_index("mol_id")["label"], how="inner").dropna(subset=models + ["label"])
    y = df["label"].to_numpy(dtype=float)
    n = len(df)
    if n < 100:
        raise RuntimeError(f"{feature_key}: only {n} rows after screening; too few.")

    # 5. 3-way split: train (fit) / calibration (conformal) / test (honest final metrics, never touched).
    #    Scaffold-holdout by DEFAULT (whole scaffolds never span splits) so analog leakage in contaminated
    #    public data does not inflate the metrics; a recipe may set `split: random`, and scaffold_split
    #    itself falls back to random for tiny/single-scaffold sets. See training/split.py.
    smiles_by_mol = data.drop_duplicates("mol_id").set_index("mol_id")["smiles"]
    row_smiles = [str(smiles_by_mol.get(mid, "")) for mid in df.index]
    if r.get("split", "scaffold") == "random":
        rng = np.random.default_rng(0)
        perm = rng.permutation(n)
        n_tr0, n_cal0 = int(0.6 * n), int(0.2 * n)
        tr, cal, te = perm[:n_tr0], perm[n_tr0:n_tr0 + n_cal0], perm[n_tr0 + n_cal0:]
    else:
        tr, cal, te = split.scaffold_split(row_smiles, seed=0)
    n_tr, n_cal = len(tr), len(cal)

    calibrated_cols, source_specs = [], []
    for s in srcs:
        x = df[s["model"]].to_numpy(dtype=float)
        params = fitmod.calibrate_source(x[tr], y[tr], s["calibration"])
        gx = fitmod._apply_calibration(x, s["calibration"], params)
        calibrated_cols.append(gx)
        source_specs.append(SourceCalibration(model=s["model"], kind=s["calibration"], params=params,
                                              impute_value=float(np.mean(gx[tr]))))
    C = np.column_stack(calibrated_cols)
    reg = r["fusion"].get("regularization")
    weights, intercept = fitmod.fit_fusion(C[tr], y[tr], method=r["fusion"]["method"],
                                           regularization=0.1 if reg is None else float(reg))
    w = np.array([weights[i] for i in range(len(srcs))])
    pred = C @ w + intercept

    scale = _scale(C, unc_cfg)
    floor = unc_cfg.get("scale_floor", 0.0)
    Q = conformal.normalized_conformal_quantile(y[cal] - pred[cal], scale[cal],
                                                alpha=unc_cfg.get("alpha", 0.1), floor=floor)

    # HONEST test-set metrics (held out from both the fit and the conformal calibration).
    from scipy.stats import spearmanr

    def _r2(true: np.ndarray, p: np.ndarray) -> float:
        return float(1 - np.sum((true - p) ** 2) / np.sum((true - true.mean()) ** 2))

    test_mae = float(np.mean(np.abs(y[te] - pred[te])))
    test_r2 = _r2(y[te], pred[te])
    test_cov = conformal.empirical_coverage(y[te] - pred[te], scale[te], Q, floor=floor)
    test_spearman = float(spearmanr(y[te], pred[te]).correlation)
    # best SINGLE source alone (its calibrated column = its standalone prediction) -> did fusion add value?
    best_single_r2 = max(_r2(y[te], C[te, j]) for j in range(C.shape[1]))
    fusion_uplift_r2 = test_r2 - best_single_r2

    spec = FusionSpec(
        feature=feature, endpoint=endpoint,
        target=Target(name=tgt["name"], units=tgt.get("units", ""), transform=tgt.get("transform", "identity")),
        sources=source_specs,
        fusion=Fusion(weights={srcs[i]["model"]: float(w[i]) for i in range(len(srcs))},
                      intercept=float(intercept), method=r["fusion"]["method"],
                      regularization=r["fusion"].get("regularization")),
        uncertainty=UncertaintySpec(method=unc_cfg.get("method", "none"), alpha=unc_cfg.get("alpha", 0.1),
                                    quantile=Q, scale=unc_cfg.get("scale", "disagreement_std"),
                                    scale_floor=floor, constant_width=unc_cfg.get("constant_width")),
        provenance=Provenance(
            dataset=tgt["dataset"], dataset_hash=_hash_df(data),
            n_train=int(n_tr), n_calib=int(n_cal),
            metrics={"test_mae": test_mae, "test_r2": test_r2, "test_spearman": test_spearman,
                     "best_single_source_r2": best_single_r2, "fusion_uplift_r2": fusion_uplift_r2,
                     "test_conformal_coverage": test_cov, "n_test": float(len(te))},
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
    root = args.root or Path(os.environ.get("FTO_ADMET_ROOT", "."))
    spec = train(args.feature, root=root)
    m = spec.provenance.metrics
    print(f"wrote {args.feature}.json | r2={m['test_r2']:.3f} spearman={m['test_spearman']:.3f} "
          f"mae={m['test_mae']:.3f} best_single_r2={m['best_single_source_r2']:.3f} "
          f"uplift={m['fusion_uplift_r2']:+.3f} coverage={m['test_conformal_coverage']:.3f} "
          f"(n_test={int(m['n_test'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
