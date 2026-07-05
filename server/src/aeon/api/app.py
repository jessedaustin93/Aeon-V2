"""Aeon-V2 FastAPI application.

Auth: when AEON_API_TOKEN is set, every /api/* request needs
`Authorization: Bearer <token>`. When unset, only loopback clients are
accepted (safe default for a tailnet-fronted box).

Chat streams AgentEvents as newline-delimited SSE (`data: {...}\n\n`).
"""
import hmac
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterator, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import aeon
from aeon.core.config import Config
from aeon.agent.approvals import ApprovalBroker
from aeon.agent.loop import AgentLoop
from aeon.models.router import ModelRouter
from aeon.skills import SkillStore
from aeon.skills.learn import propose_from_transcript
from aeon.research import ResearchStore, run_research
from aeon.mesh import MeshClient, MeshConfig

from .sessions import SessionStore


def _check_auth(request: Request) -> None:
    token = os.environ.get("AEON_API_TOKEN", "").strip()
    if token:
        header = request.headers.get("authorization", "")
        if not hmac.compare_digest(header, f"Bearer {token}"):
            raise HTTPException(status_code=401, detail="Invalid or missing token")
        return
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1"):
        raise HTTPException(
            status_code=401,
            detail="AEON_API_TOKEN is not set; remote connections are refused",
        )


def create_app(config: Optional[Config] = None) -> FastAPI:
    app = FastAPI(title="Aeon-V2", version=aeon.__version__)
    cfg = config or Config()
    router = ModelRouter(cfg)
    broker = ApprovalBroker(cfg)
    skill_store = SkillStore(cfg)
    loop = AgentLoop(config=cfg, router=router, broker=broker, skill_store=skill_store)
    sessions = SessionStore(cfg)
    research_store = ResearchStore(cfg)
    mesh_client = MeshClient(MeshConfig.from_env())
    app.state.config = cfg
    app.state.router = router
    app.state.broker = broker
    app.state.skill_store = skill_store
    app.state.loop = loop
    app.state.sessions = sessions
    app.state.research_store = research_store
    app.state.mesh_client = mesh_client

    auth = Depends(_check_auth)

    @app.get("/api/health", dependencies=[auth])
    def health() -> Dict:
        return {
            "status": "ok",
            "version": aeon.__version__,
            "workers": router.health_check(),
        }

    @app.get("/api/models", dependencies=[auth])
    def models() -> Dict:
        return {
            "roles": router.roles,
            "workers": [
                {
                    "name": w.name,
                    "base_url": w.base_url,
                    "models": w.models,
                    "priority": w.priority,
                    "healthy": w.healthy,
                }
                for w in router.workers
            ],
        }

    @app.get("/api/sessions", dependencies=[auth])
    def list_sessions() -> Dict:
        return {"sessions": sessions.list()}

    @app.post("/api/sessions", dependencies=[auth])
    def create_session(body: Optional[Dict] = None) -> Dict:
        return sessions.create((body or {}).get("title", ""))

    @app.get("/api/sessions/{session_id}", dependencies=[auth])
    def get_session(session_id: str) -> Dict:
        session = sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Unknown session")
        return session

    @app.post("/api/chat", dependencies=[auth])
    def chat(body: Dict) -> StreamingResponse:
        session_id = body.get("session_id", "")
        message = (body.get("message") or "").strip()
        role = body.get("role", "chat")
        if not message:
            raise HTTPException(status_code=422, detail="message is required")
        session = sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Unknown session")
        sessions.append(session_id, {"role": "user", "content": message})
        history = [
            {"role": m["role"], "content": m["content"]}
            for m in sessions.get(session_id)["messages"]
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]

        def stream() -> Iterator[str]:
            reply = ""
            for event in app.state.loop.run(history, role=role):
                if event.kind == "text":
                    reply += event.data.get("text", "")
                elif event.kind == "done" and not reply:
                    reply = event.data.get("text", "")
                yield f"data: {json.dumps(asdict(event))}\n\n"
            if reply:
                sessions.append(session_id, {"role": "assistant", "content": reply})

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/api/skills", dependencies=[auth])
    def list_skills() -> Dict:
        return {
            "active": [asdict(s) for s in skill_store.list_active()],
            "proposals": [asdict(s) for s in skill_store.list_proposals()],
        }

    @app.post("/api/skills/propose", dependencies=[auth])
    def propose_skill(body: Dict) -> Dict:
        session = sessions.get(body.get("session_id", ""))
        if session is None:
            raise HTTPException(status_code=404, detail="Unknown session")
        skill = propose_from_transcript(session["messages"], cfg, router)
        return {"skill": asdict(skill) if skill else None}

    @app.post("/api/skills/{name}/approve", dependencies=[auth])
    def approve_skill(name: str) -> Dict:
        try:
            skill = skill_store.approve(name)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown proposal")
        except FileExistsError:
            raise HTTPException(status_code=409, detail="Active skill already exists")
        return asdict(skill)

    @app.post("/api/skills/{name}/reject", dependencies=[auth])
    def reject_skill(name: str) -> Dict:
        try:
            skill_store.reject(name)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown proposal")
        return {"status": "rejected", "name": name}

    @app.post("/api/research", dependencies=[auth])
    def research(body: Dict) -> StreamingResponse:
        question = (body.get("question") or "").strip()
        if not question:
            raise HTTPException(status_code=422, detail="question is required")

        def stream() -> Iterator[str]:
            for event in run_research(question, cfg, router):
                yield f"data: {json.dumps(asdict(event))}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/api/research", dependencies=[auth])
    def list_research() -> Dict:
        return {"runs": research_store.list()}

    @app.get("/api/research/{run_id}", dependencies=[auth])
    def get_research(run_id: str) -> Dict:
        run = research_store.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Unknown research run")
        return run

    @app.get("/api/memory/search", dependencies=[auth])
    def memory_search(q: str = "") -> Dict:
        from aeon.tools.memory import memory_search as _search
        if not q.strip():
            return {"query": q, "results": []}
        return _search({"query": q, "limit": 20}, cfg)

    @app.get("/api/mesh", dependencies=[auth])
    def mesh_status() -> Dict:
        return {
            "agent_id": mesh_client.config.agent_id,
            "machine": mesh_client.config.machine,
            "configured": mesh_client.configured,
            "workers": [
                {"name": w.name, "base_url": w.base_url, "healthy": w.healthy}
                for w in router.workers
            ],
        }

    @app.post("/api/mesh/message", dependencies=[auth])
    def mesh_message(body: Dict) -> Dict:
        if not app.state.mesh_client.configured:
            raise HTTPException(status_code=503, detail="Mesh not configured")
        if not body.get("recipient") or not body.get("content"):
            raise HTTPException(status_code=422, detail="recipient and content required")
        result = app.state.mesh_client.post_message(
            thread_id=body.get("thread_id"),
            recipient=body["recipient"],
            content=body["content"],
            kind=body.get("kind", "message"),
        )
        return {"posted": True, "message_id": result.get("id")}

    @app.get("/api/approvals", dependencies=[auth])
    def approvals() -> Dict:
        return {"pending": [asdict(r) for r in broker.pending()]}

    @app.post("/api/approvals/{approval_id}", dependencies=[auth])
    def resolve_approval(approval_id: str, body: Dict) -> Dict:
        if "approved" not in body:
            raise HTTPException(status_code=422, detail="approved is required")
        try:
            request = broker.resolve(approval_id, bool(body["approved"]))
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown approval")
        return asdict(request)

    _mount_web(app)
    return app


def _web_dist() -> Optional[Path]:
    """Locate the built web app. AEON_WEB_DIST overrides; otherwise look for
    web/dist relative to the repo (…/server/src/aeon/api/app.py -> repo root)."""
    override = os.environ.get("AEON_WEB_DIST", "").strip()
    if override:
        path = Path(override).expanduser()
        return path if (path / "index.html").exists() else None
    repo_root = Path(__file__).resolve().parents[4]
    candidate = repo_root / "web" / "dist"
    return candidate if (candidate / "index.html").exists() else None


def _mount_web(app: FastAPI) -> None:
    dist = _web_dist()
    if dist is None:
        return  # API-only mode when the web app hasn't been built
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    dist_root = dist.resolve()

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        # Serve real files (favicon, manifest, sw.js, icons); everything else
        # falls back to index.html so client-side routes deep-link correctly.
        index = dist_root / "index.html"
        if full_path:
            candidate = (dist_root / full_path).resolve()
            # Confine to dist_root: reject any ../ traversal escaping it.
            if (candidate == dist_root or dist_root in candidate.parents) and candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(index)


def main() -> None:
    import uvicorn

    host = os.environ.get("AEON_API_HOST", "0.0.0.0")
    port = int(os.environ.get("AEON_API_PORT", "8900"))
    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    main()
