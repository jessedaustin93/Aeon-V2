import json

import pytest
from fastapi.testclient import TestClient

from aeon.core.config import Config
from aeon.agent.loop import AgentEvent
from aeon.api.app import create_app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AEON_API_TOKEN", "test-token")
    cfg = Config()
    cfg.memory_path.mkdir(parents=True, exist_ok=True)
    cfg.vault_path.mkdir(parents=True, exist_ok=True)
    app = create_app(cfg)

    class FakeLoop:
        def run(self, messages, role="chat"):
            yield AgentEvent("text", {"text": "hello "})
            yield AgentEvent("text", {"text": "world"})
            yield AgentEvent("done", {"text": "hello world"})

    app.state.loop = FakeLoop()
    app.state.router.health_check = lambda: {"local": True}
    return TestClient(app)


AUTH = {"Authorization": "Bearer test-token"}


def test_requires_token(client):
    assert client.get("/api/health").status_code == 401
    assert client.get("/api/health", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_session_id_traversal_rejected(client):
    resp = client.get("/api/sessions/..%2F..%2Fetc%2Fpasswd", headers=AUTH)
    assert resp.status_code == 404
    resp = client.post("/api/chat", headers=AUTH,
                       json={"session_id": "../../escape", "message": "x"})
    assert resp.status_code == 404


def test_health(client):
    resp = client.get("/api/health", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["workers"] == {"local": True}


def test_models_endpoint(client):
    resp = client.get("/api/models", headers=AUTH)
    assert resp.status_code == 200
    assert "roles" in resp.json()
    assert "workers" in resp.json()


def test_sessions_crud(client):
    created = client.post("/api/sessions", headers=AUTH, json={"title": "Test"}).json()
    assert created["title"] == "Test"
    listed = client.get("/api/sessions", headers=AUTH).json()["sessions"]
    assert [s["id"] for s in listed] == [created["id"]]
    fetched = client.get(f"/api/sessions/{created['id']}", headers=AUTH).json()
    assert fetched["messages"] == []
    assert client.get("/api/sessions/nope", headers=AUTH).status_code == 404


def test_chat_streams_and_persists(client):
    session = client.post("/api/sessions", headers=AUTH, json={}).json()
    resp = client.post(
        "/api/chat",
        headers=AUTH,
        json={"session_id": session["id"], "message": "hi aeon"},
    )
    assert resp.status_code == 200
    events = [
        json.loads(line[5:].strip())
        for line in resp.text.splitlines()
        if line.startswith("data:")
    ]
    kinds = [e["kind"] for e in events]
    assert kinds == ["text", "text", "done"]

    stored = client.get(f"/api/sessions/{session['id']}", headers=AUTH).json()
    roles = [m["role"] for m in stored["messages"]]
    assert roles == ["user", "assistant"]
    assert stored["messages"][1]["content"] == "hello world"
    # First user message becomes the session title.
    assert stored["title"] == "hi aeon"


def test_chat_validation(client):
    session = client.post("/api/sessions", headers=AUTH, json={}).json()
    assert client.post("/api/chat", headers=AUTH,
                       json={"session_id": session["id"], "message": ""}).status_code == 422
    assert client.post("/api/chat", headers=AUTH,
                       json={"session_id": "nope", "message": "x"}).status_code == 404


def test_approvals_endpoints(client):
    broker = client.app.state.broker
    req = broker.create("shell_run", {"command": "ls"})
    pending = client.get("/api/approvals", headers=AUTH).json()["pending"]
    assert [p["id"] for p in pending] == [req.id]
    resolved = client.post(f"/api/approvals/{req.id}", headers=AUTH,
                           json={"approved": True}).json()
    assert resolved["status"] == "approved"
    assert client.post("/api/approvals/nope", headers=AUTH,
                       json={"approved": True}).status_code == 404
