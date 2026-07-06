import json

import pytest

from aeon.models import client as client_mod
from aeon.models.client import ChatClient, ChatDelta


def _nonstream_response(text="hello", tool_calls=None, finish="stop"):
    message = {"role": "assistant", "content": text}
    if tool_calls:
        message["tool_calls"] = tool_calls
        message["content"] = None
    return {
        "choices": [{"message": message, "finish_reason": finish}],
    }


def test_chat_nonstream_text(monkeypatch):
    captured = {}

    def fake_post(url, payload, timeout, stream=False):
        captured["url"] = url
        captured["payload"] = payload
        return _nonstream_response("hi there")

    monkeypatch.setattr(client_mod, "_post_json", fake_post)
    c = ChatClient("http://fake:1234/v1")
    deltas = list(c.chat("m1", [{"role": "user", "content": "hi"}]))
    kinds = [d.kind for d in deltas]
    assert kinds == ["text", "finish"]
    assert deltas[0].text == "hi there"
    assert captured["url"] == "http://fake:1234/v1/chat/completions"
    assert captured["payload"]["model"] == "m1"
    assert "tools" not in captured["payload"]


def test_chat_nonstream_tool_calls(monkeypatch):
    tc = [{"id": "call_1", "type": "function",
           "function": {"name": "fs_read", "arguments": '{"path": "x"}'}}]
    monkeypatch.setattr(
        client_mod, "_post_json",
        lambda *a, **k: _nonstream_response(None, tool_calls=tc, finish="tool_calls"),
    )
    c = ChatClient("http://fake:1234/v1")
    tools = [{"type": "function", "function": {"name": "fs_read", "parameters": {}}}]
    deltas = list(c.chat("m1", [{"role": "user", "content": "read"}], tools=tools))
    assert deltas[-1].kind == "finish"
    assert deltas[-1].finish_reason == "tool_calls"
    tool_deltas = [d for d in deltas if d.kind == "tool_call"]
    assert len(tool_deltas) == 1
    assert tool_deltas[0].tool_calls[0]["function"]["name"] == "fs_read"


def _sse(lines):
    for line in lines:
        yield f"data: {json.dumps(line)}"
    yield "data: [DONE]"


def test_chat_stream_text_and_tool_args_aggregate(monkeypatch):
    chunks = [
        {"choices": [{"delta": {"content": "He"}}]},
        {"choices": [{"delta": {"content": "llo"}}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_9", "type": "function",
             "function": {"name": "web_search", "arguments": '{"que'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": 'ry": "sdr"}'}}]}}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    ]

    monkeypatch.setattr(client_mod, "_post_json",
                        lambda *a, **k: _sse(chunks))
    c = ChatClient("http://fake:1234/v1")
    deltas = list(c.chat("m1", [{"role": "user", "content": "go"}], stream=True))
    text = "".join(d.text for d in deltas if d.kind == "text")
    assert text == "Hello"
    tool_deltas = [d for d in deltas if d.kind == "tool_call"]
    assert len(tool_deltas) == 1
    call = tool_deltas[0].tool_calls[0]
    assert call["id"] == "call_9"
    assert call["function"]["name"] == "web_search"
    assert json.loads(call["function"]["arguments"]) == {"query": "sdr"}
    assert deltas[-1].kind == "finish"


def test_timeout_defaults_from_env(monkeypatch):
    import importlib
    from aeon.models import client as cm
    monkeypatch.setenv("AEON_LLM_TIMEOUT", "42")
    importlib.reload(cm)
    try:
        assert cm.ChatClient("http://x/v1").timeout == 42.0
        assert cm.ChatClient("http://x/v1", timeout=5).timeout == 5.0
    finally:
        monkeypatch.delenv("AEON_LLM_TIMEOUT", raising=False)
        importlib.reload(cm)


def test_list_models(monkeypatch):
    monkeypatch.setattr(
        client_mod, "_get_json",
        lambda url, timeout: {"data": [{"id": "a"}, {"id": "b"}]},
    )
    assert ChatClient("http://fake/v1").list_models() == ["a", "b"]


def test_embed(monkeypatch):
    monkeypatch.setattr(
        client_mod, "_post_json",
        lambda url, payload, timeout, stream=False: {
            "data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]
        },
    )
    vecs = ChatClient("http://fake/v1").embed("emb", ["x", "y"])
    assert vecs == [[0.1, 0.2], [0.3, 0.4]]
