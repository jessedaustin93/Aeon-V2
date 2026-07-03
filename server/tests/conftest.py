"""Pytest configuration for aeon-v1 test suite."""
import pytest
from aeon.core.bus import MessageBus
from aeon.core.approval_agent import CLIAuthProvider


@pytest.fixture(autouse=True)
def isolated_data_root(monkeypatch, tmp_path):
    """Point AEON_DATA_DIR at a per-test tmp dir.

    Tests that call Config() with no argument would otherwise write
    memory/ and vault/ into the repo working tree.
    """
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path / "aeon-data"))


@pytest.fixture(autouse=True)
def reset_message_bus():
    """Reset the MessageBus singleton between tests.

    Prevents handler accumulation from agents created in one test
    from leaking into subsequent tests.
    """
    MessageBus.reset()
    yield
    MessageBus.reset()


@pytest.fixture(autouse=True)
def auto_approve_writes(monkeypatch):
    """Auto-approve all DataWriteAgent write requests during tests.

    CLIAuthProvider blocks on stdin which is unusable in a test run.
    This fixture replaces request_approval with an always-approve stub
    for the duration of each test. Layer 7 tests that need controlled
    approval use MockAuthProvider directly and are unaffected.
    """
    monkeypatch.setattr(
        CLIAuthProvider,
        "request_approval",
        lambda self, prompt, context: (True, "auto-approved in test"),
    )
