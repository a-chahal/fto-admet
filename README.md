# fto-admet

a modular admet / dmpk screening pipeline. pass one smiles and get back one consolidated
card across every endpoint: herg, lipophilicity, solubility, clearance, distribution,
permeability, plasma protein binding, metabolism, toxicity, druglikeness, synthesizability,
structural alerts, and a triage summary.

`core` is a thin, model-agnostic layer: a curated registry of models, a dispatcher that runs
each model in its own isolated environment, and per-endpoint aggregators that fuse the model
outputs into one verdict per endpoint. every model adapter hides its upstream code behind one
uniform interface (`run.py --input <path> --output <path> [--gpu N]`), so `core` never imports a
model, it shells out. adding a model is a registry entry plus a folder; adding an endpoint is a
folder plus an aggregator.

## setup

```bash
cp .env.example .env    # set the two storage paths (code + outputs, and envs + caches + weights)
pixi install            # solve the core environment (no gpu or model dependencies)
pip install -e .        # make `core` importable
```

## run

one smiles, full card:

```bash
python -m core.screen --smiles "CC(C)NCC(O)COc1cccc2ccccc12" --out card.json
```

one endpoint at a time:

```bash
python -m core.run --endpoint herg --input mol.smi
```

`--input` accepts a `.smi` file or an `InputRecord` json (`{"smiles": "...", "mol_id": "..."}`).
each model runs in its own environment; the first use of a model installs that environment from
its lockfile, then it is cached.

## how it works

models are grouped by endpoint in the registry. for each endpoint the runner selects its models,
dispatches each one in isolation, and passes the collected outputs to that endpoint's aggregator.
the aggregators never average across incompatible scales: they harmonize onto a common quantity,
surface cross-model spread as a confidence signal, and keep separate reads separate. every output
reserves uncertainty and applicability-domain fields, so native signals (bayesian variance,
fold-error, domain flags) are carried through rather than dropped.

## tests

```bash
pixi run pytest -m "not model" -q   # fast tier: core and aggregators, no gpu
pixi run pytest -m "model" -q       # opt-in: per-model smoke tests, each in its own environment
```

## note

the default input fixture is a placeholder smiles. swap in your target structure before a real
screen; the fast test tier passes either way.
