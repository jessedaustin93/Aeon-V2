"""OpenAI-compatible chat client (LM Studio, Ollama, vLLM, ...).

Stdlib-only transport, matching aeon.core.llm's approach. Streaming uses
the SSE lines of /chat/completions; incremental tool-call argument chunks
are aggregated so consumers always receive complete tool calls.
"""
import json
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional

# Local inference (esp. a "thinking" model synthesizing a long report on a
# mid-range GPU) can take minutes. Default generously; override with the env var.
DEFAULT_TIMEOUT = float(os.environ.get("AEON_LLM_TIMEOUT", "300"))


def _request(url: str, data: Optional[bytes], timeout: float):
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if data is not None else "GET",
    )
    return urllib.request.urlopen(req, timeout=timeout)


def _get_json(url: str, timeout: float) -> Dict:
    with _request(url, None, timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_json(url: str, payload: Dict, timeout: float, stream: bool = False):
    """POST JSON. Returns a parsed dict, or an iterator of SSE line strings
    (without trailing newlines) when stream=True."""
    data = json.dumps(payload).encode("utf-8")
    resp = _request(url, data, timeout)
    if not stream:
        with resp:
            return json.loads(resp.read().decode("utf-8"))

    def _lines():
        with resp:
            for raw in resp:
                line = raw.decode("utf-8").strip()
                if line:
                    yield line

    return _lines()


@dataclass
class ChatDelta:
    kind: str  # "text" | "tool_call" | "finish"
    text: str = ""
    tool_calls: Optional[List[Dict]] = None
    finish_reason: Optional[str] = None


@dataclass
class _ToolCallBuffer:
    id: str = ""
    name: str = ""
    arguments: str = ""

    def to_call(self) -> Dict:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }


class ChatClient:
    """Minimal OpenAI-compatible client for one base URL."""

    def __init__(self, base_url: str, timeout: Optional[float] = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout if timeout is not None else DEFAULT_TIMEOUT

    def list_models(self) -> List[str]:
        data = _get_json(f"{self.base_url}/models", self.timeout)
        return [m.get("id", "") for m in data.get("data", [])]

    def embed(self, model: str, texts: List[str]) -> List[List[float]]:
        payload = {"model": model, "input": texts}
        data = _post_json(f"{self.base_url}/embeddings", payload, self.timeout)
        return [item.get("embedding", []) for item in data.get("data", [])]

    def chat(
        self,
        model: str,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
        stream: bool = False,
        temperature: Optional[float] = None,
    ) -> Iterator[ChatDelta]:
        payload: Dict = {"model": model, "messages": messages, "stream": stream}
        if tools:
            payload["tools"] = tools
        if temperature is not None:
            payload["temperature"] = temperature
        url = f"{self.base_url}/chat/completions"
        if stream:
            yield from self._chat_stream(url, payload)
        else:
            yield from self._chat_once(url, payload)

    # ------------------------------------------------------------- non-stream

    def _chat_once(self, url: str, payload: Dict) -> Iterator[ChatDelta]:
        data = _post_json(url, payload, self.timeout)
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content")
        if content:
            yield ChatDelta(kind="text", text=content)
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            yield ChatDelta(kind="tool_call", tool_calls=tool_calls)
        yield ChatDelta(kind="finish", finish_reason=choice.get("finish_reason"))

    # ----------------------------------------------------------------- stream

    def _chat_stream(self, url: str, payload: Dict) -> Iterator[ChatDelta]:
        buffers: Dict[int, _ToolCallBuffer] = {}
        finish_reason: Optional[str] = None
        for line in _post_json(url, payload, self.timeout, stream=True):
            if not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if body == "[DONE]":
                break
            try:
                chunk = json.loads(body)
            except json.JSONDecodeError:
                continue
            choice = (chunk.get("choices") or [{}])[0]
            delta = choice.get("delta") or {}
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]
            content = delta.get("content")
            if content:
                yield ChatDelta(kind="text", text=content)
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                buf = buffers.setdefault(idx, _ToolCallBuffer())
                if tc.get("id"):
                    buf.id = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    buf.name = fn["name"]
                if fn.get("arguments"):
                    buf.arguments += fn["arguments"]
        if buffers:
            calls = [buffers[i].to_call() for i in sorted(buffers)]
            yield ChatDelta(kind="tool_call", tool_calls=calls)
        yield ChatDelta(kind="finish", finish_reason=finish_reason)
