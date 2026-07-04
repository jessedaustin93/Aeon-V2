import threading
import time

import pytest

from aeon.core.config import Config
from aeon.agent.approvals import ApprovalBroker


@pytest.fixture
def broker(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path))
    return ApprovalBroker(Config())


def test_create_is_pending(broker):
    req = broker.create("shell_run", {"command": "ls"})
    assert req.status == "pending"
    assert req.tool == "shell_run"
    assert [r.id for r in broker.pending()] == [req.id]


def test_resolve_approved_and_wait(broker):
    req = broker.create("shell_run", {"command": "ls"})

    def approve_later():
        time.sleep(0.05)
        broker.resolve(req.id, True)

    t = threading.Thread(target=approve_later)
    t.start()
    status = broker.wait(req.id, timeout=2.0)
    t.join()
    assert status == "approved"
    assert broker.pending() == []


def test_resolve_denied(broker):
    req = broker.create("shell_run", {"command": "rm -rf /"})
    broker.resolve(req.id, False)
    assert broker.wait(req.id, timeout=0.1) == "denied"


def test_wait_timeout_expires(broker):
    req = broker.create("shell_run", {"command": "ls"})
    status = broker.wait(req.id, timeout=0.05)
    assert status == "expired"
    assert broker.pending() == []


def test_resolve_unknown_raises(broker):
    with pytest.raises(KeyError):
        broker.resolve("nope", True)


def test_persistence_across_instances(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path))
    b1 = ApprovalBroker(Config())
    req = b1.create("shell_run", {"command": "uptime"})
    b2 = ApprovalBroker(Config())
    assert [r.id for r in b2.pending()] == [req.id]
    b2.resolve(req.id, True)
    b3 = ApprovalBroker(Config())
    assert b3.pending() == []
