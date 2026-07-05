import json

from aeon.mesh.client import MeshClient, MeshConfig


class FakeHttp:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def __call__(self, method, url, headers, body):
        parsed = json.loads(body.decode()) if body else None
        self.calls.append({"method": method, "url": url, "headers": headers, "body": parsed})
        return self.responses.get((method, url.split("?")[0]), None)


def _config():
    return MeshConfig(hub="http://hub:8787", token="secret", agent_id="aeon@t5810", machine="t5810")


def test_configured():
    assert MeshClient(_config()).configured is True
    assert MeshClient(MeshConfig(hub="", token="")).configured is False


def test_from_env(monkeypatch):
    monkeypatch.setenv("AEON_MESH_HUB", "http://hub:8787/")
    monkeypatch.setenv("AEON_MESH_TOKEN", "tok")
    monkeypatch.delenv("AEON_MESH_AGENT_ID", raising=False)
    monkeypatch.delenv("AEON_MESH_MACHINE", raising=False)
    cfg = MeshConfig.from_env()
    assert cfg.hub == "http://hub:8787"  # trailing slash stripped
    assert cfg.token == "tok"
    assert cfg.agent_id.startswith("aeon@")


def test_heartbeat():
    http = FakeHttp()
    MeshClient(_config(), http).heartbeat("running")
    call = http.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "http://hub:8787/api/heartbeat"
    assert call["body"] == {"agent_id": "aeon@t5810", "machine": "t5810", "status": "running"}
    assert call["headers"]["Authorization"] == "Bearer secret"


def test_inbox_list_and_dict_shapes():
    http = FakeHttp({("GET", "http://hub:8787/api/inbox/aeon@t5810"): [{"id": 1}]})
    assert MeshClient(_config(), http).inbox(after=0) == [{"id": 1}]
    http2 = FakeHttp({("GET", "http://hub:8787/api/inbox/aeon@t5810"): {"messages": [{"id": 2}]}})
    assert MeshClient(_config(), http2).inbox(after=5) == [{"id": 2}]
    assert "after=5" in http2.calls[0]["url"]


def test_post_message():
    http = FakeHttp({("POST", "http://hub:8787/api/messages"): {"id": 42}})
    result = MeshClient(_config(), http).post_message("thread-1", "claude@x1", "hello")
    assert result == {"id": 42}
    body = http.calls[0]["body"]
    assert body["thread_id"] == "thread-1"
    assert body["sender"] == "aeon@t5810"
    assert body["recipient"] == "claude@x1"
    assert body["content"] == "hello"


def test_ack():
    http = FakeHttp()
    MeshClient(_config(), http).ack(7)
    assert http.calls[0]["url"] == "http://hub:8787/api/messages/7/ack"
    assert http.calls[0]["method"] == "POST"
