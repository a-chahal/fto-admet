"""Machine-path resolution: the single place that turns the environment into resolved paths.

Nothing else in the codebase hardcodes ``/zfs/sanjanp``. A collaborator clones the repo, copies
``.env.example`` to ``.env``, sets their own two paths, and every module reads them through here
(CLAUDE.md §0 storage discipline; SETTLED §2/§8b/§9). Pure path logic: no model imports, no network,
no subprocess, deterministic (same environment in -> same paths out).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# The two paths a machine must declare. Everything else derives from FTO_ADMET_ROOT.
REQUIRED_VARS = ("FTO_ADMET_ROOT", "FTO_ADMET_ENV_CACHE")


class ConfigError(RuntimeError):
    """Machine paths could not be resolved from the environment (missing var or unsafe location)."""


def _repo_root() -> Path:
    """Repo root, inferred from this file's location (<repo>/core/config.py)."""
    return Path(__file__).resolve().parent.parent


def _parse_dotenv(path: Path) -> dict[str, str]:
    """Minimal ``.env`` reader: ``KEY=VALUE`` lines, ``#`` comments, optional ``export`` and quotes.

    Returns a plain dict and never mutates ``os.environ``; the real environment always wins over the
    file (see ``load_config``). Kept dependency-free so the core env needs nothing beyond stdlib.
    """
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, sep, val = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            values[key] = val
    return values


def _resolve_var(name: str, env: Mapping[str, str], dotenv: Mapping[str, str]) -> str:
    """Look a required var up in the real environment first, then the ``.env`` file."""
    val = env.get(name) or dotenv.get(name)
    if not val:
        raise ConfigError(
            f"{name} is not set. Copy .env.example to .env at the repo root and set {name} "
            f"(a path on /zfs; see CLAUDE.md §0 storage discipline)."
        )
    return val


@dataclass(frozen=True)
class Config:
    """Immutable, resolved machine paths. Build it with :func:`load_config`.

    ``ledger``/``locks``/``outputs`` are the pipeline's write targets and are created on load;
    ``root`` and ``env_cache`` are declared by the collaborator's ``.env``.
    """

    root: Path
    env_cache: Path
    ledger: Path
    locks: Path
    outputs: Path


def _ensure_write_dirs(cfg: Config) -> None:
    """Create the dirs the pipeline writes to. Refuse to create anything under ``$HOME``.

    ``$HOME`` on the box is ~97% full and off-limits for project data (CLAUDE.md §0); a root that
    resolves inside it is a misconfiguration, not something to silently populate.
    """
    home = Path.home().resolve()
    for d in (cfg.ledger.parent, cfg.locks, cfg.outputs):
        resolved = d.resolve()
        if resolved == home or home in resolved.parents:
            raise ConfigError(
                f"refusing to create {d} under $HOME ({home}); project paths must live on /zfs, "
                f"not $HOME (CLAUDE.md §0). Check FTO_ADMET_ROOT in your .env."
            )
        d.mkdir(parents=True, exist_ok=True)


def load_config(
    *,
    env: Mapping[str, str] | None = None,
    dotenv_path: Path | None = None,
    create_dirs: bool = True,
) -> Config:
    """Resolve a :class:`Config` from the environment (and repo-root ``.env`` as a fallback).

    Args:
        env: environment mapping to read; defaults to ``os.environ``.
        dotenv_path: ``.env`` file to fall back on; defaults to ``<repo>/.env``.
        create_dirs: create the pipeline's write dirs (``ledger`` parent, ``locks``, ``outputs``).
    """
    env = os.environ if env is None else env
    if dotenv_path is None:
        dotenv_path = _repo_root() / ".env"
    dotenv = _parse_dotenv(dotenv_path)

    root = Path(_resolve_var("FTO_ADMET_ROOT", env, dotenv)).expanduser()
    env_cache = Path(_resolve_var("FTO_ADMET_ENV_CACHE", env, dotenv)).expanduser()

    cfg = Config(
        root=root,
        env_cache=env_cache,
        ledger=root / "ledger" / "runs.jsonl",
        locks=root / ".locks",
        outputs=root / "outputs",
    )
    if create_dirs:
        _ensure_write_dirs(cfg)
    return cfg


_CACHE: Config | None = None


def get_config() -> Config:
    """Cached process-wide accessor reading ``os.environ`` + repo ``.env``.

    Use this in the pipeline; use :func:`load_config` directly in tests for a hermetic, uncached read.
    """
    global _CACHE
    if _CACHE is None:
        _CACHE = load_config()
    return _CACHE


def reset_config_cache() -> None:
    """Drop the cached :class:`Config` (test hook; call after mutating the environment)."""
    global _CACHE
    _CACHE = None
