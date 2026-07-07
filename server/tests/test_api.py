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
    monkeypatch.delenv("AEON_MESH_HUB", raising=False)
    monkeypatch.delenv("AEON_MESH_TOKEN", raising=False)
    # Force API-only mode so these tests don't depend on a built web/dist.
    monkeypatch.setenv("AEON_WEB_DIST", str(tmp_path / "no-web"))
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


def test_skills_lifecycle(client):
    store = client.app.state.skill_store
    store.propose("mesh-health", "Check mesh", "steps")
    listing = client.get("/api/skills", headers=AUTH).json()
    assert listing["active"] == []
    assert [s["name"] for s in listing["proposals"]] == ["mesh-health"]

    approved = client.post("/api/skills/mesh-health/approve", headers=AUTH).json()
    assert approved["name"] == "mesh-health"
    listing = client.get("/api/skills", headers=AUTH).json()
    assert [s["name"] for s in listing["active"]] == ["mesh-health"]

    assert client.post("/api/skills/ghost/approve", headers=AUTH).status_code == 404


def test_skills_listing_includes_evidence(client):
    store = client.app.state.skill_store
    store.propose("forged", "d", "b", evidence={"ab": {"with_better": True}})
    proposals = client.get("/api/skills", headers=AUTH).json()["proposals"]
    forged = [p for p in proposals if p["name"] == "forged"][0]
    assert forged["evidence"]["ab"]["with_better"] is True


def test_forge_endpoint_streams(client, monkeypatch):
    from aeon.agent.loop import AgentEvent

    def fake_forge(topic, config, router, **kwargs):
        yield AgentEvent("text", {"text": "researching\n"})
        yield AgentEvent("done", {"skill": {"name": "x", "description": "d", "body": "b"},
                                  "evidence": {"ab": {"with_better": True}}})

    monkeypatch.setattr("aeon.api.app.forge_skill", fake_forge)
    resp = client.post("/api/skills/forge", headers=AUTH, json={"topic": "SDR"})
    assert resp.status_code == 200
    kinds = [json.loads(l[5:])["kind"] for l in resp.text.splitlines() if l.startswith("data:")]
    assert kinds == ["text", "done"]


def test_forge_requires_topic(client):
    assert client.post("/api/skills/forge", headers=AUTH, json={"topic": ""}).status_code == 422


def test_stream_emits_error_frame_on_exception(client, monkeypatch):
    def boom(topic, config, router, **kwargs):
        yield __import__("aeon.agent.loop", fromlist=["AgentEvent"]).AgentEvent(
            "text", {"text": "starting\n"})
        raise TimeoutError("timed out")

    monkeypatch.setattr("aeon.api.app.forge_skill", boom)
    resp = client.post("/api/skills/forge", headers=AUTH, json={"topic": "x"})
    assert resp.status_code == 200
    events = [json.loads(l[5:]) for l in resp.text.splitlines() if l.startswith("data:")]
    assert events[0]["kind"] == "text"
    # The stream must always end in a terminal error frame, never die silently.
    assert events[-1]["kind"] == "error"
    assert "TimeoutError" in events[-1]["data"]["error"]


def test_skill_reject(client):
    store = client.app.state.skill_store
    store.propose("junk", "d", "b")
    resp = client.post("/api/skills/junk/reject", headers=AUTH)
    assert resp.status_code == 200
    assert client.get("/api/skills", headers=AUTH).json()["proposals"] == []


def test_skill_propose_no_skill(client, monkeypatch):
    session = client.post("/api/sessions", headers=AUTH, json={}).json()
    client.app.state.sessions.append(session["id"], {"role": "user", "content": "hi"})
    monkeypatch.setattr("aeon.api.app.propose_from_transcript",
                        lambda messages, cfg, router: None)
    resp = client.post("/api/skills/propose", headers=AUTH,
                       json={"session_id": session["id"]})
    assert resp.status_code == 200
    assert resp.json() == {"skill": None}


def test_research_endpoints(client, monkeypatch):
    from aeon.agent.loop import AgentEvent

    def fake_run(question, cfg, router, **kwargs):
        yield AgentEvent("text", {"text": "searching\n"})
        yield AgentEvent("done", {"run_id": "r1", "report_path": "/x.md", "sources": []})

    monkeypatch.setattr("aeon.api.app.run_research", fake_run)
    resp = client.post("/api/research", headers=AUTH, json={"question": "what is SDR?"})
    assert resp.status_code == 200
    kinds = [json.loads(l[5:])["kind"] for l in resp.text.splitlines() if l.startswith("data:")]
    assert kinds == ["text", "done"]

    assert client.post("/api/research", headers=AUTH, json={"question": ""}).status_code == 422
    assert client.get("/api/research", headers=AUTH).status_code == 200
    assert client.get("/api/research/nope", headers=AUTH).status_code == 404


def test_task_run_endpoints(client):
    class FakeTaskRunner:
        def __init__(self, store):
            self.store = store

        def start(self, prompt, title="", role="chat"):
            run = self.store.create(prompt=prompt, title=title, role=role)
            self.store.patch(run["id"], status="done", result="checked")
            return self.store.get(run["id"])

    client.app.state.task_runner = FakeTaskRunner(client.app.state.task_runs)
    created = client.post(
        "/api/tasks",
        headers=AUTH,
        json={"prompt": "check qbit", "title": "qbit", "role": "deep"},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "done"
    assert body["result"] == "checked"
    assert body["role"] == "deep"

    listed = client.get("/api/tasks", headers=AUTH).json()["tasks"]
    assert [t["id"] for t in listed] == [body["id"]]
    fetched = client.get(f"/api/tasks/{body['id']}", headers=AUTH).json()
    assert fetched["prompt"] == "check qbit"
    assert client.get("/api/tasks/nope", headers=AUTH).status_code == 404


def test_task_run_requires_prompt(client):
    assert client.post("/api/tasks", headers=AUTH, json={"prompt": ""}).status_code == 422


def test_spa_serving_and_api_precedence(monkeypatch, tmp_path):
    monkeypatch.setenv("AEON_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AEON_API_TOKEN", "tok")
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Aeon</title>", encoding="utf-8")
    (dist / "manifest.webmanifest").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("AEON_WEB_DIST", str(dist))
    cfg = Config()
    cfg.memory_path.mkdir(parents=True, exist_ok=True)
    cfg.vault_path.mkdir(parents=True, exist_ok=True)
    c = TestClient(create_app(cfg))

    # Deep link falls back to index.html.
    deep = c.get("/mesh")
    assert deep.status_code == 200
    assert "Aeon" in deep.text
    # Real static file is served directly.
    assert c.get("/manifest.webmanifest").status_code == 200
    # The SPA catch-all must NOT shadow the API (auth still enforced).
    assert c.get("/api/health").status_code == 401
    # Traversal outside dist/ falls back to index.html, never leaks a file.
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET", encoding="utf-8")
    resp = c.get("/../secret.txt")
    assert "TOPSECRET" not in resp.text
    resp2 = c.get("/%2e%2e%2fsecret.txt")
    assert "TOPSECRET" not in resp2.text


def test_mesh_status(client):
    resp = client.get("/api/mesh", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert "agent_id" in body
    assert "configured" in body
    assert isinstance(body["workers"], list)


def test_mesh_message_unconfigured_503(client):
    # No AEON_MESH_HUB/TOKEN set in this fixture -> not configured.
    resp = client.post("/api/mesh/message", headers=AUTH,
                       json={"recipient": "claude@x1", "content": "hi"})
    assert resp.status_code == 503


def test_mesh_message_posts_when_configured(client):
    posted = {}

    class FakeMeshClient:
        configured = True

        def post_message(self, thread_id, recipient, content, kind="reply"):
            posted.update(dict(recipient=recipient, content=content))
            return {"id": 7}

    client.app.state.mesh_client = FakeMeshClient()
    resp = client.post("/api/mesh/message", headers=AUTH,
                       json={"recipient": "claude@x1", "content": "status?"})
    assert resp.status_code == 200
    assert resp.json() == {"posted": True, "message_id": 7}
    assert posted["recipient"] == "claude@x1"


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
