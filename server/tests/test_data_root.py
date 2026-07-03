from pathlib import Path

from aeon.core.config import Config
from aeon.cli import init_data, MEMORY_SUBDIRS


def test_config_uses_aeon_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path / "data"))
    cfg = Config()
    assert cfg.base_path == tmp_path / "data"
    assert cfg.memory_path == tmp_path / "data" / "memory"
    assert cfg.vault_path == tmp_path / "data" / "vault"


def test_config_explicit_base_path_beats_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path / "env-root"))
    cfg = Config(base_path=tmp_path / "explicit")
    assert cfg.base_path == tmp_path / "explicit"


def test_config_default_without_env(monkeypatch):
    monkeypatch.delenv("AEON_DATA_DIR", raising=False)
    cfg = Config()
    assert cfg.base_path == Path(".")


def test_init_data_scaffolds_tree(monkeypatch, tmp_path):
    root = tmp_path / "aeon-data"
    monkeypatch.setenv("AEON_DATA_DIR", str(root))
    rc = init_data([])
    assert rc == 0
    for sub in MEMORY_SUBDIRS:
        assert (root / "memory" / sub).is_dir(), sub
    assert (root / "vault").is_dir()
    assert (root / "skills").is_dir()


def test_init_data_is_idempotent(monkeypatch, tmp_path):
    root = tmp_path / "aeon-data"
    monkeypatch.setenv("AEON_DATA_DIR", str(root))
    assert init_data([]) == 0
    assert init_data([]) == 0
