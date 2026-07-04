import json
import threading

import pytest

from aeon.core.config import Config
from aeon.agent.approvals import ApprovalBroker
from aeon.agent.loop import AgentLoop, AgentEvent
from aeon.models.client import ChatDelta
from aeon.models.router import ModelRouter


class FakeClient:
    """Yields scripted turns; each turn is a list of ChatDelta."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.base_url = "http://fake/v1"
        self.requests = []

    def chat(self, model, messages, tools=None, stream=False, temperature=None):
        self.requests.append({"messages": list(messages), "tools": tools})
        for delta in self.turns.pop(0):
            yield delta


@pytest.fixture
def config(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path / "data"))
    cfg = Config()
    cfg.memory_path.mkdir(parents=True, exist_ok=True)
    cfg.vault_path.mkdir(parents=True, exist_ok=True)
    return cfg


def make_loop(config, turns, **kwargs):
    router = ModelRouter(config)
    router.roles["chat"] = "fake-model"
    fake = FakeClient(turns)
    router.resolve = lambda role: (fake, "fake-model")  # type: ignore
    loop = AgentLoop(config=config, router=router, **kwargs)
    return loop, fake


def tool_call(name, args, call_id="c1"):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def test_text_only_turn(config):
    turns = [[ChatDelta("text", text="hi jesse"), ChatDelta("finish", finish_reason="stop")]]
    loop, _ = make_loop(config, turns)
    events = list(loop.run([{"role": "user", "content": "hello"}]))
    kinds = [e.kind for e in events]
    assert kinds == ["text", "done"]
    assert events[-1].data["text"] == "hi jesse"


def test_tool_roundtrip(config):
    note = config.base_path / "note.txt"
    note.write_text("secret contents", encoding="utf-8")
    turns = [
        [ChatDelta("tool_call", tool_calls=[tool_call("fs_read", {"path": str(note)})]),
         ChatDelta("finish", finish_reason="tool_calls")],
        [ChatDelta("text", text="the file says: secret contents"),
         ChatDelta("finish", finish_reason="stop")],
    ]
    loop, fake = make_loop(config, turns)
    events = list(loop.run([{"role": "user", "content": "read my note"}]))
    kinds = [e.kind for e in events]
    assert kinds == ["tool_call", "tool_result", "text", "done"]
    assert events[1].data["result"]["text"] == "secret contents"
    # The tool result was fed back to the model as a role:"tool" message.
    second_request = fake.requests[1]["messages"]
    assert any(m.get("role") == "tool" for m in second_request)
    # Journal recorded the execution.
    assert loop.journal.tail(5)[0]["tool"] == "fs_read"


def test_approval_gated_tool_denied(config):
    turns = [
        [ChatDelta("tool_call", tool_calls=[tool_call("shell_run", {"command": "ls"})]),
         ChatDelta("finish", finish_reason="tool_calls")],
        [ChatDelta("text", text="ok, not running it"), ChatDelta("finish", finish_reason="stop")],
    ]
    loop, _ = make_loop(config, turns, approval_timeout=0.05)
    events = list(loop.run([{"role": "user", "content": "run ls"}]))
    kinds = [e.kind for e in events]
    assert "approval_pending" in kinds
    result_event = next(e for e in events if e.kind == "tool_result")
    assert "denied" in result_event.data["result"]["error"]


def test_approval_gated_tool_approved(config):
    broker = ApprovalBroker(config)
    turns = [
        [ChatDelta("tool_call", tool_calls=[tool_call("shell_run", {"command": "echo hi"})]),
         ChatDelta("finish", finish_reason="tool_calls")],
        [ChatDelta("text", text="done"), ChatDelta("finish", finish_reason="stop")],
    ]
    loop, _ = make_loop(config, turns, broker=broker, approval_timeout=5.0)

    def approve_when_pending():
        import time
        for _ in range(100):
            pending = broker.pending()
            if pending:
                broker.resolve(pending[0].id, True)
                return
            time.sleep(0.02)

    t = threading.Thread(target=approve_when_pending)
    t.start()
    events = list(loop.run([{"role": "user", "content": "echo"}]))
    t.join()
    result_event = next(e for e in events if e.kind == "tool_result")
    assert result_event.data["result"]["exit_code"] == 0
    assert "hi" in result_event.data["result"]["stdout"]


def test_unknown_tool_is_error_result(config):
    turns = [
        [ChatDelta("tool_call", tool_calls=[tool_call("nope_tool", {})]),
         ChatDelta("finish", finish_reason="tool_calls")],
        [ChatDelta("text", text="sorry"), ChatDelta("finish", finish_reason="stop")],
    ]
    loop, _ = make_loop(config, turns)
    events = list(loop.run([{"role": "user", "content": "x"}]))
    result_event = next(e for e in events if e.kind == "tool_result")
    assert "unknown tool" in result_event.data["result"]["error"]


def test_handler_exception_becomes_error_result(config):
    turns = [
        [ChatDelta("tool_call", tool_calls=[tool_call("fs_read", {"path": "/etc/shadow"})]),
         ChatDelta("finish", finish_reason="tool_calls")],
        [ChatDelta("text", text="blocked"), ChatDelta("finish", finish_reason="stop")],
    ]
    loop, _ = make_loop(config, turns)
    events = list(loop.run([{"role": "user", "content": "x"}]))
    result_event = next(e for e in events if e.kind == "tool_result")
    assert "PermissionError" in result_event.data["result"]["error"]


def test_max_iterations_cap(config):
    note = config.base_path / "n.txt"
    note.write_text("x", encoding="utf-8")
    looping_turn = [
        ChatDelta("tool_call", tool_calls=[tool_call("fs_read", {"path": str(note)})]),
        ChatDelta("finish", finish_reason="tool_calls"),
    ]
    turns = [looping_turn] * 3
    loop, _ = make_loop(config, turns, max_iterations=3)
    events = list(loop.run([{"role": "user", "content": "loop forever"}]))
    assert events[-1].kind == "error"
    assert "max iterations" in events[-1].data["error"]


def test_system_prompt_injected(config):
    turns = [[ChatDelta("text", text="hi"), ChatDelta("finish", finish_reason="stop")]]
    loop, fake = make_loop(config, turns)
    list(loop.run([{"role": "user", "content": "hello"}]))
    first = fake.requests[0]["messages"][0]
    assert first["role"] == "system"
    assert "Aeon" in first["content"]
