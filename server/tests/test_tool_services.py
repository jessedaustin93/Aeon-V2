import subprocess

import pytest

from aeon.core.config import Config
from aeon.tools import services
from aeon.tools.services import service_status, service_control


@pytest.fixture
def config(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path))
    return Config()


def _fake_run(monkeypatch, active="active", rc=0):
    def run(args, capture_output, text, timeout):
        sub = args[2]  # ["systemctl", "--user", <sub>, ...]
        out = active if sub == "is-active" else f"status of {args[3] if len(args) > 3 else ''}"
        return subprocess.CompletedProcess(args, rc, stdout=out, stderr="")
    monkeypatch.setattr(services, "_systemctl",
                        lambda a: run(["systemctl", "--user", *a], True, True, 20))


def test_status_valid(config, monkeypatch):
    _fake_run(monkeypatch, active="active")
    r = service_status({"service": "aeon-server"}, config)
    assert r["active"] == "active"
    assert r["service"] == "aeon-server"


def test_status_rejects_bad_name(config):
    assert "error" in service_status({"service": "bad;name"}, config)
    assert "error" in service_status({"service": "a b"}, config)


def test_status_redirects_snifferops_to_t5810b(config, monkeypatch):
    called = False

    def fake_systemctl(args):
        nonlocal called
        called = True
        return subprocess.CompletedProcess(args, 0, stdout="disabled", stderr="")

    monkeypatch.setattr(services, "_systemctl", fake_systemctl)
    r = service_status({"service": "snifferops.service"}, config)

    assert called is False
    assert r["active"] == "not_applicable_on_this_host"
    assert r["host"] == "t5810b"
    assert "snifferops_telemetry" in r["message"]


def test_control_start(config, monkeypatch):
    _fake_run(monkeypatch, active="active", rc=0)
    r = service_control({"action": "restart", "service": "aeon-server"}, config)
    assert r["action"] == "restart"
    assert r["exit_code"] == 0


def test_control_rejects_bad_action(config):
    assert "error" in service_control({"action": "reboot", "service": "aeon-server"}, config)


def test_control_rejects_bad_service(config):
    assert "error" in service_control({"action": "start", "service": "../evil"}, config)


def test_status_free_control_gated(config):
    gated = {d.name: d.approval_required for d in services.DEFINITIONS}
    assert gated["service_status"] is False
    assert gated["service_control"] is True
