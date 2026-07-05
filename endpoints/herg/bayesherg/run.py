#!/usr/bin/env python
"""bayesherg adapter - Bayesian graph neural network for hERG blocker probability + a native
aleatoric/epistemic uncertainty split (the hERG split-case adjudicator).

Uniform model CLI (CLAUDE.md 2, SETTLED 6):

    python run.py --input <path> --output <path> [--gpu N]

BayeshERG (GIST-CSBL/BayeshERG, Kim et al., Briefings in Bioinformatics 2022) is a concrete-dropout
Bayesian GNN. It is a PRIMARY hERG model: its ``score`` is P(hERG block) fed to the gate core average
(identity, UP = more likely blocker), and its MC-dropout uncertainty is decomposed into ``alea``
(aleatoric, irreducible/noise) and ``epis`` (epistemic, out-of-domain). That split is what makes
BayeshERG the split-case adjudicator (better than a single MC-dropout scalar), so we emit it faithfully
into the reserved ``uncertainty.aleatoric`` / ``uncertainty.epistemic`` fields (CLAUDE.md 3, F flags).

This runs in the model's ISOLATED, LEGACY pixi env (python 3.6 + pytorch 1.6.0 + dgl 0.4.3 +
rdkit 2021.03.5) and so CANNOT import ``core``; it emits plain JSON matching ``core.schemas.OutputRecord``
and the dispatcher validates that JSON on collection. Upstream code lives unmodified under
``vendor/BayeshERG`` (its ``model/BayeshERG_model.py`` + ``main.py``); we import the model class and
featurizers and run inference here rather than shelling out to ``main.py`` (see LANDMINE below).

NOTE (python 3.6): this module targets the legacy env's interpreter, so it uses ``typing`` aliases
(no PEP 585 ``list[...]`` / PEP 604 ``X | None`` / ``from __future__ import annotations`` - none of those
exist on 3.6). Keep it 3.6-clean.

LANDMINE (why we reimplement inference instead of calling upstream ``main.py``):
  Upstream ``main.py`` does ``atom_feats = bg.ndata.pop('h')`` inside its MC-sampling loop. In dgl
  0.4.3post2, ``dgl.batch`` of a SINGLE-graph list shares the node frame with the source graph, so the
  destructive ``.pop('h')`` strips features from the source; the SECOND sampling pass then raises
  ``KeyError: 'h'``. Upstream never hit this because their example CSVs always held many molecules
  (multi-graph batches are copied, not shared). A one-molecule input (e.g. the FTO-43 fixture) triggers
  it. We therefore read features with ``bg.ndata['h']`` / ``bg.edata['e']`` (NON-destructive) and never
  pop - correct for batches of any size. We also skip the per-molecule attention ``.svg`` rendering
  (upstream's ``attention_visulaizer``); that is not part of the bulk screening path.

LANDMINE (weights license): the trained weights ``model/model_weights.pth`` are CC-BY-NC-4.0 (academic /
individual use only, no commercial use) - the source code is MIT but the weights are NOT. Any hERG hit
found with them inherits the non-commercial restriction. See README. The weights are NOT committed to git
(binary; kept out of the tree); this adapter fetches them once, on first use, from the pinned upstream
commit into the gitignored ``vendor/BayeshERG/model/`` path and caches them there.

``requires_gpu=True`` but a CPU fallback is honored and is in fact the default here: the py3.6 + dgl 0.4.3
+ old-CUDA stack does not cooperate with the box's modern (575.x) driver, so inference runs on CPU
(acceptable for the shortlist). ``--gpu N`` selects ``cuda:N`` only if torch reports CUDA available;
otherwise it silently falls back to CPU.

Robustness: an unparseable / empty SMILES yields a per-record result with a null ``P_block`` and the
reason in ``raw`` (RDKit returns ``None`` for a bad parse) - one bad molecule never sinks a bulk batch.
"""

import argparse
import json
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Vendored upstream lives under vendor/BayeshERG; put it on the path so ``from model.BayeshERG_model
# import ...`` (upstream's flat layout) resolves. Weights land under vendor/BayeshERG/model/ (gitignored).
VENDOR = Path(__file__).resolve().parent / "vendor" / "BayeshERG"
WEIGHTS = VENDOR / "model" / "model_weights.pth"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

warnings.filterwarnings("ignore")

MODEL = "bayesherg"

# Upstream pins (main.py): the trained checkpoint was built at these exact hyperparameters. A mismatch
# would fail to load the state dict. Do not change without re-verifying the checkpoint loads.
TRAIN_LEN = 14322
NODE_INPUT_DIM = 74
EDGE_INPUT_DIM = 12
NODE_HIDDEN_DIM = 128
EDGE_HIDDEN_DIM = 128
NUM_STEP_MESSAGE_PASSING = 7
NUM_STEP_MHA = 1

# MC-dropout sampling passes (upstream ``-t`` default is 30). Fixed here because the uniform CLI carries
# no ``-t``; the number of stochastic forward passes the score/alea/epis are averaged over.
MC_SAMPLES = 30
# Seed so the MC-dropout score/uncertainty are reproducible run-to-run (the smoke asserts shape/bands,
# not an exact value, but a stable number is friendlier for the ledger / audit trail).
MC_SEED = 0

# The trained weights are fetched once from this pinned upstream commit (CC-BY-NC-4.0; see README). The
# repo ships them under model/model_weights.pth (~513 KB); pinning the commit keeps provenance exact.
UPSTREAM_COMMIT = "25e9466499905a952f9d41cc6bc6886c3f247acb"
WEIGHTS_URL = (
    "https://raw.githubusercontent.com/GIST-CSBL/BayeshERG/"
    + UPSTREAM_COMMIT
    + "/model/model_weights.pth"
)


def _provenance(torch_version, dgl_version):
    # type: (str, str) -> Dict[str, Any]
    """Provenance stamped onto every emitted record (versions read live, never hardcoded)."""
    return {
        "model": MODEL,
        "method": "BayeshERG: concrete-dropout Bayesian D-MPNN + multi-head attention readout; "
        "MC-dropout at inference gives P(block) + an aleatoric/epistemic uncertainty split",
        "mc_samples": MC_SAMPLES,
        "torch_version": torch_version,
        "dgl_version": dgl_version,
        "upstream_commit": UPSTREAM_COMMIT,
        "citation": "Kim H, Park M, Lee I, Nam H. BayeshERG: a robust, reliable and interpretable "
        "deep learning model for predicting hERG channel blockers. Brief Bioinform 2022;23(4):bbac211. "
        "doi:10.1093/bib/bbac211",
        "license": "code: MIT (Hyunho Kim 2021); trained weights + any hits: CC-BY-NC-4.0 "
        "(academic/individual use only, no commercial use). Access CODE-PKG.",
    }


def parse_inputs(text):
    # type: (str) -> Tuple[List[Dict[str, Any]], bool]
    """Parse the ``--input`` payload into ``(records, single)`` (same contract as the t11/t23 template).

    Accepts a single ``InputRecord`` JSON object (``single=True``), a JSON array of them (a bulk batch),
    or a ``.smi`` file (``<SMILES><whitespace><title>`` per line, ``#`` comments).
    """
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        data = json.loads(stripped)
        if isinstance(data, dict):
            return [data], True
        if isinstance(data, list):
            return list(data), False
        raise ValueError("input JSON must be an object or an array of objects")

    records = []  # type: List[Dict[str, Any]]
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        mol_id = parts[1] if len(parts) > 1 else None
        records.append({"smiles": parts[0], "mol_id": mol_id})
    return records, False


def _ensure_weights():
    # type: () -> None
    """Fetch the CC-BY-NC-4.0 trained weights once (they are not committed to git; binary).

    Downloads the pinned-commit checkpoint into the gitignored ``vendor/BayeshERG/model/`` path and caches
    it there. Idempotent: a present, non-empty file is left untouched. Raises on failure so a missing
    weight is a loud error, never a silent wrong prediction.
    """
    if WEIGHTS.exists() and WEIGHTS.stat().st_size > 0:
        return
    WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
    import requests  # provided by the isolated env (requests==2.25.1)

    last_err = None  # type: Optional[Exception]
    for _ in range(3):
        try:
            resp = requests.get(WEIGHTS_URL, timeout=60)
            resp.raise_for_status()
            tmp = WEIGHTS.with_suffix(".pth.part")
            tmp.write_bytes(resp.content)
            tmp.replace(WEIGHTS)
            return
        except Exception as exc:  # noqa: BLE001 - retried; re-raised below if all attempts fail
            last_err = exc
    raise RuntimeError(
        "could not fetch BayeshERG weights from {0}: {1}: {2}".format(
            WEIGHTS_URL, type(last_err).__name__, last_err
        )
    )


def _resolve_device(gpu):
    # type: (Optional[int]) -> Any
    """Pick the compute device: ``cuda:N`` only if torch reports CUDA available, else CPU.

    requires_gpu=True upstream, but this legacy stack does not cooperate with the box's modern driver, so
    this resolves to CPU in practice - the accepted CPU fallback for the shortlist.
    """
    import torch

    if gpu is not None and torch.cuda.is_available():
        return torch.device("cuda:{0}".format(gpu))
    return torch.device("cpu")


def _predict(smiles_list, device):
    # type: (List[str], Any) -> Tuple[List[float], List[float], List[float]]
    """Run BayeshERG MC-dropout inference on a list of PARSEABLE SMILES.

    Returns ``(score, alea, epis)`` aligned to ``smiles_list``. Implements upstream ``main.py``'s
    prediction math (mean of the softmax P(block) over MC passes; aleatoric = E[p(1-p)]; epistemic =
    Var[p]) but reads node/edge features NON-destructively (``bg.ndata['h']``, no ``.pop`` - see the
    module LANDMINE) so a single-molecule batch works.
    """
    import numpy as np
    import torch
    import dgl
    from dgl.data.chem.utils import smiles_to_bigraph
    from dgl.data.chem import CanonicalAtomFeaturizer, CanonicalBondFeaturizer
    from torch.utils.data import DataLoader

    from model.BayeshERG_model import BayeshERG, RegularizationAccumulator

    def collate(graphs):
        bg = dgl.batch(graphs)
        bg.set_n_initializer(dgl.init.zero_initializer)
        bg.set_e_initializer(dgl.init.zero_initializer)
        return bg

    atom_featurizer = CanonicalAtomFeaturizer()
    bond_featurizer = CanonicalBondFeaturizer()
    graphs = [
        smiles_to_bigraph(s, node_featurizer=atom_featurizer, edge_featurizer=bond_featurizer)
        for s in smiles_list
    ]

    # Build the model at the exact trained hyperparameters, then load the shipped checkpoint.
    wr = 1e-4 ** 2.0 / TRAIN_LEN
    dr = 2.0 / TRAIN_LEN
    reg_acc = RegularizationAccumulator()
    model = BayeshERG(
        reg_acc=reg_acc,
        node_input_dim=NODE_INPUT_DIM,
        edge_input_dim=EDGE_INPUT_DIM,
        node_hidden_dim=NODE_HIDDEN_DIM,
        edge_hidden_dim=EDGE_HIDDEN_DIM,
        num_step_message_passing=NUM_STEP_MESSAGE_PASSING,
        num_step_mha=NUM_STEP_MHA,
        wr=wr,
        dr=dr,
    )
    model.load_state_dict(torch.load(str(WEIGHTS), map_location=device))
    model = model.to(device)

    loader = DataLoader(list(graphs), batch_size=32, shuffle=False, collate_fn=collate, drop_last=False)

    torch.manual_seed(MC_SEED)
    # per_sample[t] = 1-D array of P(block) for every molecule on MC pass t.
    per_sample = []  # type: List[Any]
    with torch.no_grad():
        # eval() does NOT disable concrete dropout (it is a custom stochastic layer, not nn.Dropout), so
        # the forward passes stay stochastic - this is what yields the Bayesian uncertainty.
        model.eval()
        for _ in range(MC_SAMPLES):
            batch_probs = []  # type: List[Any]
            for bg in loader:
                atom_feats = bg.ndata["h"].to(device)   # NON-destructive read (no .pop) - LANDMINE
                bond_feats = bg.edata["e"].to(device)
                pred, _attn = model(bg, atom_feats, bond_feats)
                softmax = np.array(pred[1].detach().cpu().numpy()).reshape(-1, 2)
                batch_probs.append(softmax[:, 1])   # column 1 = P(block)
            per_sample.append(np.concatenate(batch_probs))

    sc = np.stack(per_sample, axis=1)          # shape [n_mol, MC_SAMPLES]
    score = sc.mean(axis=1)
    alea = (sc * (1.0 - sc)).mean(axis=1)      # aleatoric: E[p(1-p)]
    epis = ((sc - score.reshape(-1, 1)) ** 2).mean(axis=1)  # epistemic: Var[p]
    return [float(x) for x in score], [float(x) for x in alea], [float(x) for x in epis]


def _null_record(smiles, mol_id, reason, provenance):
    # type: (str, Any, str, Dict[str, Any]) -> Dict[str, Any]
    """A valid OutputRecord for a molecule that could not be scored (null P_block, reason in raw)."""
    return {
        "model": MODEL,
        "endpoint_values": {"P_block": None},
        "uncertainty": None,
        "raw": {"error": reason, "smiles": smiles, "mol_id": mol_id},
        "provenance": provenance,
    }


def run(records, device):
    # type: (List[Dict[str, Any]], Any) -> List[Dict[str, Any]]
    """Score a batch: split parseable from unparseable SMILES, predict the valid ones, keep input order."""
    import torch
    import dgl
    from rdkit import Chem

    provenance = _provenance(getattr(torch, "__version__", "unknown"), getattr(dgl, "__version__", "unknown"))

    smiles_list = [str(r.get("smiles") or "").strip() for r in records]
    mol_ids = [r.get("mol_id") for r in records]

    valid_idx = [i for i, smi in enumerate(smiles_list) if smi and Chem.MolFromSmiles(smi) is not None]

    scores = []  # type: List[float]
    aleas = []   # type: List[float]
    episs = []   # type: List[float]
    if valid_idx:
        try:
            scores, aleas, episs = _predict([smiles_list[i] for i in valid_idx], device)
        except Exception as exc:  # noqa: BLE001 - a batch-level failure degrades to per-record nulls, never a crash
            reason = "prediction failed: {0}: {1}".format(type(exc).__name__, exc)
            return [_null_record(smiles_list[i], mol_ids[i], reason, provenance) for i in range(len(records))]

    outputs = []  # type: List[Dict[str, Any]]
    pos = 0
    for idx in range(len(records)):
        if idx in valid_idx:
            score, alea, epis = scores[pos], aleas[pos], episs[pos]
            pos += 1
            outputs.append(
                {
                    "model": MODEL,
                    # score is already P(block); identity into the gate core average (UP = more blocker).
                    "endpoint_values": {"P_block": score},
                    # the aleatoric/epistemic split - this is what makes BayeshERG the adjudicator.
                    "uncertainty": {
                        "aleatoric": alea,
                        "epistemic": epis,
                        "extra": {"mc_samples": MC_SAMPLES},
                    },
                    "raw": {
                        "smiles": smiles_list[idx],
                        "mol_id": mol_ids[idx],
                        "score": score,
                        "alea": alea,
                        "epis": epis,
                    },
                    "provenance": provenance,
                }
            )
        else:
            reason = "empty SMILES" if not smiles_list[idx] else "RDKit could not parse SMILES"
            outputs.append(_null_record(smiles_list[idx], mol_ids[idx], reason, provenance))
    return outputs


def main(argv=None):
    # type: (Optional[List[str]]) -> int
    parser = argparse.ArgumentParser(description="BayeshERG hERG blocker + uncertainty adapter (uniform model CLI).")
    parser.add_argument("--input", required=True, type=Path, help="pipeline input (InputRecord JSON, JSON array, or .smi)")
    parser.add_argument("--output", required=True, type=Path, help="where to write the OutputRecord JSON")
    parser.add_argument("--gpu", type=int, default=None, help="cuda:N if a CUDA build is available, else CPU (the default)")
    args = parser.parse_args(argv)

    _ensure_weights()
    device = _resolve_device(args.gpu)

    records, single = parse_inputs(args.input.read_text(encoding="utf-8"))
    outputs = run(records, device)
    payload = outputs[0] if (single and len(outputs) == 1) else outputs

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
