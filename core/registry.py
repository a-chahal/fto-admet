"""The curated model registry: one ``ModelSpec`` per ``ModelName`` (CLAUDE.md §2).

``REGISTRY`` is the single source of truth the dispatcher and every aggregator key off. Dispatch
resolves a model's env + entrypoint here; each endpoint's ``aggregate.py`` selects its models by
*endpoint membership* (``ep in spec.endpoints``), never by folder layout. ``endpoints`` is therefore a
``frozenset`` and the cross-cutting models (``admet_ai``, ``boiled_egg``, ``opera``,
``pgp``) carry every endpoint their output feeds, not just their home folder (IO_SPEC §2).

Immutability is the point: specs are a reviewed contract, so ``ModelSpec`` and ``Provenance`` are
frozen dataclasses and ``REGISTRY`` is populated once at import. Counts are load-bearing: exactly 26
specs, one per ``ModelName`` (SETTLED §5; openadmet + admetlab3 removed - the first redundant with
admet_ai, the second a chronically-unstable web service); the dropped/replaced upstreams (deephit,
spielvogel, cardiodpi, fame3; CLAUDE.md §4) have no member and cannot appear.

Boundaries honored here:
- Web-only tools (``watanabe_renal``, ``watanabe_pgp_brain``, ``protox``) and the out-of-band native
  runtimes (``opera`` = MATLAB/Java, ``pbpk`` = R/.NET) never enter the bulk ``pixi run`` path, so they
  carry ``env_manifest = entrypoint = None``.
- Folder paths follow ``endpoints/<home_endpoint>/<model>/`` and *need not exist yet* (each folder is
  built by its own later task); the registry only declares where they will be.
- ``input_schema`` / ``output_schema`` point at the shared ``InputRecord`` / ``OutputRecord`` base for
  now; each per-model ``OutputRecord`` subclass lands with its model.
- Per-model provenance literals (upstream commit, citation, license) are filled from a real upstream
  checkout in each model's task (CLAUDE.md §5). Fabricating them here is forbidden, so only the known
  ``access_tag`` is set now; the rest stay ``None`` placeholders.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from core.models import Endpoint, ModelName
from core.schemas import InputRecord, OutputRecord

# Repo-root-anchored base for the (not-yet-existing) per-model folders: endpoints/<home>/<model>/.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENDPOINTS_DIR = _REPO_ROOT / "endpoints"


@dataclass(frozen=True)
class Provenance:
    """Upstream provenance for a model. ``access_tag`` is known now; the rest land with the model task.

    ``access_tag`` classifies how the model is obtained/run (e.g. ``CODE-PKG``, ``CODE-API``,
    ``WEB-ONLY``, ``CODE-ALGO``, ``CODE-STANDALONE``, ``WEB-SUBSTITUTABLE``, ``CODE (R/.NET)``) and is
    the one provenance literal the registry can state without a live upstream checkout. The remaining
    fields are filled from the real repo when each model is built (CLAUDE.md §5); they are ``None``
    placeholders here rather than fabricated values (the no-fabricate rule).
    """

    access_tag: str
    upstream_commit: str | None = None
    citation: str | None = None
    license: str | None = None


@dataclass(frozen=True)
class ModelSpec:
    """Immutable descriptor for one model adapter (CLAUDE.md §2). The registry's value type.

    ``endpoints`` is a ``frozenset`` because a model can feed several endpoints (the cross-cutting
    models) and aggregators query it by membership. ``env_manifest`` / ``entrypoint`` are ``None`` for
    web-only and out-of-band-runtime models that never enter the bulk ``pixi run`` path; for every other
    model they point at ``endpoints/<home>/<model>/pixi.toml`` and ``.../run.py`` respectively.
    """

    name: ModelName
    endpoints: frozenset[Endpoint]
    env_manifest: Path | None
    entrypoint: Path | None
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    requires_gpu: bool
    in_bulk_loop: bool
    provenance: Provenance


# Cross-cutting endpoint sets (IO_SPEC §2). A model here feeds every listed endpoint's aggregator, not
# just its home folder. Every other model is a single: endpoints = {home}.
_CROSS_CUTTING: dict[ModelName, frozenset[Endpoint]] = {
    ModelName.admet_ai: frozenset({
        Endpoint.triage, Endpoint.herg, Endpoint.metabolism, Endpoint.clearance, Endpoint.ppb,
        Endpoint.solubility, Endpoint.lipophilicity, Endpoint.permeability, Endpoint.distribution,
        Endpoint.toxicity,
    }),
    ModelName.boiled_egg: frozenset({Endpoint.distribution, Endpoint.permeability}),
    ModelName.opera: frozenset({Endpoint.lipophilicity, Endpoint.clearance, Endpoint.ppb}),
    ModelName.pgp: frozenset({Endpoint.distribution, Endpoint.permeability}),
}


# The authoritative spec table (t04 brief): model, home endpoint, requires_gpu, in_bulk_loop,
# access_tag, has_env. "opt" (optional GPU) collapses to requires_gpu=False - only a hard GPU
# requirement is True. has_env=False marks the web-only + out-of-band models (env_manifest/entrypoint
# stay None). endpoints default to {home} unless the model is listed in _CROSS_CUTTING.
_ROWS: tuple[tuple[ModelName, Endpoint, bool, bool, str, bool], ...] = (
    (ModelName.admet_ai, Endpoint.triage, False, True, "CODE-PKG", True),
    (ModelName.bayesherg, Endpoint.herg, True, True, "CODE-PKG", True),
    (ModelName.cardiotox_net, Endpoint.herg, True, True, "CODE-PKG", True),
    (ModelName.cardiogenai, Endpoint.herg, True, False, "CODE-PKG", True),
    (ModelName.smartcyp, Endpoint.metabolism, False, True, "CODE-PKG", True),
    (ModelName.fame3r, Endpoint.metabolism, False, True, "CODE-PKG", True),
    (ModelName.watanabe_renal, Endpoint.clearance, False, False, "WEB-ONLY", False),
    (ModelName.pksmart, Endpoint.clearance, False, True, "CODE-PKG", True),
    (ModelName.pbpk, Endpoint.clearance, False, False, "CODE (R/.NET)", False),
    (ModelName.bbb_score, Endpoint.distribution, False, True, "CODE-ALGO", True),
    (ModelName.boiled_egg, Endpoint.distribution, False, True, "CODE-ALGO", True),
    (ModelName.cns_mpo, Endpoint.distribution, False, True, "CODE-ALGO", True),
    (ModelName.pgp, Endpoint.distribution, False, True, "CODE", True),
    (ModelName.watanabe_pgp_brain, Endpoint.distribution, False, False, "WEB-ONLY", False),
    (ModelName.ochem_ppb, Endpoint.ppb, False, True, "CODE-API", True),
    (ModelName.sfi, Endpoint.solubility, False, True, "CODE-ALGO", True),
    (ModelName.rdkit_crippen, Endpoint.lipophilicity, False, True, "CODE-PKG", True),
    (ModelName.opera, Endpoint.lipophilicity, False, True, "CODE-STANDALONE", True),
    (ModelName.swissadme, Endpoint.lipophilicity, False, True, "WEB-SUBSTITUTABLE", True),
    (ModelName.pains_brenk, Endpoint.structural_alerts, False, True, "CODE-PKG", True),
    (ModelName.sascore, Endpoint.synthesizability, False, True, "CODE-PKG", True),
    (ModelName.rascore, Endpoint.synthesizability, False, True, "CODE-PKG", True),
    (ModelName.aizynthfinder, Endpoint.synthesizability, False, False, "CODE-PKG", True),
    (ModelName.toxicophores, Endpoint.toxicity, False, True, "CODE-PKG", True),
    (ModelName.protox, Endpoint.toxicity, False, False, "WEB-ONLY", False),
    (ModelName.lipinski_veber_qed, Endpoint.druglikeness, False, True, "CODE-PKG", True),
)


def _build_spec(
    name: ModelName,
    home: Endpoint,
    requires_gpu: bool,
    in_bulk_loop: bool,
    access_tag: str,
    has_env: bool,
) -> ModelSpec:
    """Assemble one ``ModelSpec`` from a spec-table row, resolving endpoints and folder paths."""
    endpoints = _CROSS_CUTTING.get(name, frozenset({home}))
    if has_env:
        model_dir = _ENDPOINTS_DIR / home.value / name.value
        env_manifest: Path | None = model_dir / "pixi.toml"
        entrypoint: Path | None = model_dir / "run.py"
    else:
        env_manifest = None
        entrypoint = None
    return ModelSpec(
        name=name,
        endpoints=endpoints,
        env_manifest=env_manifest,
        entrypoint=entrypoint,
        input_schema=InputRecord,
        output_schema=OutputRecord,
        requires_gpu=requires_gpu,
        in_bulk_loop=in_bulk_loop,
        provenance=Provenance(access_tag=access_tag),
    )


REGISTRY: dict[ModelName, ModelSpec] = {
    row[0]: _build_spec(*row) for row in _ROWS
}


class RegistryError(RuntimeError):
    """The registry is internally inconsistent (used by the core gate)."""


def registry_validate() -> None:
    """Assert the registry's structural invariants; raise ``RegistryError`` on any violation.

    Checks, in order: every ``ModelName`` has exactly one spec and vice versa; each spec's key matches
    its ``name``; ``endpoints`` is a non-empty subset of ``Endpoint``; the four cross-cutting sets match
    IO_SPEC §2 exactly; ``env_manifest`` and ``entrypoint`` are both set or both ``None`` together; and
    every provenance carries a non-empty ``access_tag``. This is what the core gate calls.
    """
    expected = set(ModelName)
    keys = set(REGISTRY)
    if keys != expected:
        missing = expected - keys
        extra = keys - expected
        raise RegistryError(f"REGISTRY keys != ModelName members (missing={missing}, extra={extra})")
    if len(REGISTRY) != 26:
        raise RegistryError(f"expected 26 specs, found {len(REGISTRY)}")

    all_endpoints = set(Endpoint)
    for name, spec in REGISTRY.items():
        if spec.name != name:
            raise RegistryError(f"spec keyed {name} carries name {spec.name}")
        if not isinstance(spec.endpoints, frozenset):
            raise RegistryError(f"{name}: endpoints must be a frozenset")
        if not spec.endpoints:
            raise RegistryError(f"{name}: endpoints is empty")
        if not spec.endpoints <= all_endpoints:
            raise RegistryError(f"{name}: endpoints {spec.endpoints - all_endpoints} not in Endpoint")
        if (spec.env_manifest is None) != (spec.entrypoint is None):
            raise RegistryError(f"{name}: env_manifest and entrypoint must both be set or both None")
        if not spec.provenance.access_tag:
            raise RegistryError(f"{name}: provenance.access_tag is empty")

    for name, endpoints in _CROSS_CUTTING.items():
        if REGISTRY[name].endpoints != endpoints:
            raise RegistryError(f"{name}: cross-cutting endpoint set does not match IO_SPEC §2")
