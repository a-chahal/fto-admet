"""Unit tests for core.config (machine-path resolution).

Hermetic: every case passes an explicit ``env`` dict and ``dotenv_path`` so the tests never depend on
the developer's real environment or the repo's gitignored ``.env``. Gate: ``pytest tests/test_config.py``.
"""

import pytest

from core.config import Config, ConfigError, load_config


def _env(root, env_cache):
    return {"FTO_ADMET_ROOT": str(root), "FTO_ADMET_ENV_CACHE": str(env_cache)}


def test_resolves_paths_relative_to_root(tmp_path):
    root = tmp_path / "fto-admet"
    env_cache = tmp_path / "fto-admet-envs"
    cfg = load_config(env=_env(root, env_cache), dotenv_path=tmp_path / "nope.env")

    assert isinstance(cfg, Config)
    assert cfg.root == root
    assert cfg.env_cache == env_cache
    assert cfg.ledger == root / "ledger" / "runs.jsonl"
    assert cfg.locks == root / ".locks"
    assert cfg.outputs == root / "outputs"


def test_creates_write_dirs(tmp_path):
    root = tmp_path / "fto-admet"
    cfg = load_config(
        env=_env(root, tmp_path / "envs"),
        dotenv_path=tmp_path / "nope.env",
        create_dirs=True,
    )
    assert cfg.ledger.parent.is_dir()
    assert cfg.locks.is_dir()
    assert cfg.outputs.is_dir()
    # env_cache is declared, not owned by this machine's write path; not created here.


def test_create_dirs_false_leaves_filesystem_untouched(tmp_path):
    root = tmp_path / "fto-admet"
    cfg = load_config(env=_env(root, tmp_path / "envs"), dotenv_path=tmp_path / "nope.env", create_dirs=False)
    assert not cfg.outputs.exists()
    assert not cfg.locks.exists()


def test_missing_root_raises_and_names_var(tmp_path):
    with pytest.raises(ConfigError) as exc:
        load_config(
            env={"FTO_ADMET_ENV_CACHE": str(tmp_path / "envs")},
            dotenv_path=tmp_path / "nope.env",
        )
    assert "FTO_ADMET_ROOT" in str(exc.value)


def test_missing_env_cache_raises_and_names_var(tmp_path):
    with pytest.raises(ConfigError) as exc:
        load_config(
            env={"FTO_ADMET_ROOT": str(tmp_path / "fto-admet")},
            dotenv_path=tmp_path / "nope.env",
        )
    assert "FTO_ADMET_ENV_CACHE" in str(exc.value)


def test_empty_var_is_treated_as_missing(tmp_path):
    with pytest.raises(ConfigError) as exc:
        load_config(
            env={"FTO_ADMET_ROOT": "", "FTO_ADMET_ENV_CACHE": str(tmp_path / "envs")},
            dotenv_path=tmp_path / "nope.env",
        )
    assert "FTO_ADMET_ROOT" in str(exc.value)


def test_dotenv_file_is_read_when_env_absent(tmp_path):
    root = tmp_path / "fto-admet"
    env_cache = tmp_path / "envs"
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "# a comment\n"
        f'FTO_ADMET_ROOT="{root}"\n'
        f"export FTO_ADMET_ENV_CACHE={env_cache}\n"
    )
    cfg = load_config(env={}, dotenv_path=dotenv)
    assert cfg.root == root
    assert cfg.env_cache == env_cache


def test_real_environment_wins_over_dotenv(tmp_path):
    env_root = tmp_path / "from-env"
    file_root = tmp_path / "from-file"
    env_cache = tmp_path / "envs"
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"FTO_ADMET_ROOT={file_root}\nFTO_ADMET_ENV_CACHE={env_cache}\n")
    cfg = load_config(env=_env(env_root, env_cache), dotenv_path=dotenv)
    assert cfg.root == env_root


def test_expands_user_home_tilde(tmp_path):
    # ~ must expand so a labmate can point paths at their own home-relative mount if they must.
    cfg = load_config(
        env={"FTO_ADMET_ROOT": "~/fto-x", "FTO_ADMET_ENV_CACHE": "~/fto-envs"},
        dotenv_path=tmp_path / "nope.env",
        create_dirs=False,
    )
    assert "~" not in str(cfg.root)
    assert str(cfg.root).endswith("fto-x")


def test_refuses_to_create_dirs_under_home(tmp_path):
    from pathlib import Path

    root = Path.home() / "fto-admet-should-not-exist-xyz"
    with pytest.raises(ConfigError) as exc:
        load_config(
            env=_env(root, tmp_path / "envs"),
            dotenv_path=tmp_path / "nope.env",
            create_dirs=True,
        )
    assert "$HOME" in str(exc.value)
    assert not root.exists()


def test_deterministic(tmp_path):
    env = _env(tmp_path / "fto-admet", tmp_path / "envs")
    a = load_config(env=env, dotenv_path=tmp_path / "nope.env")
    b = load_config(env=env, dotenv_path=tmp_path / "nope.env")
    assert a == b


def test_config_is_immutable(tmp_path):
    cfg = load_config(env=_env(tmp_path / "r", tmp_path / "e"), dotenv_path=tmp_path / "nope.env")
    with pytest.raises(Exception):
        cfg.root = tmp_path  # frozen dataclass: assignment must fail
