"""Aeon-V2 FastAPI application.

Auth: when AEON_API_TOKEN is set, every /api/* request needs
`Authorization: Bearer <token>`. When unset, only loopback clients are
accepted (safe default for a tailnet-fronted box).

Chat streams AgentEvents as newline-delimited SSE (`data: {...}\n\n`).
"""
import json
import os
from dataclasses import asdict
from typing import Dict, Iterator, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

import aeon
from aeon.core.config import Config
from aeon.agent.approvals import ApprovalBroker
from aeon.agent.loop import AgentLoop
from aeon.models.router import ModelRouter

from .sessions import SessionStore


def _check_auth(request: Request) -> None:
    token = os.environ.get("AEON_API_TOKEN", "").strip()
    if token:
        header = request.headers.get("authorization", "")
        if header != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="Invalid or missing token")
        return
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1", "testclient"):
        raise HTTPException(
            status_code=401,
            detail="AEON_API_TOKEN is not set; remote connections are refused",
        )


def create_app(config: Optional[Config] = None) -> FastAPI:
    app = FastAPI(title="Aeon-V2", version=aeon.__version__)
    cfg = config or Config()
    router = ModelRouter(cfg)
    broker = ApprovalBroker(cfg)
    loop = AgentLoop(config=cfg, router=router, broker=broker)
    sessions = SessionStore(cfg)
    app.state.config = cfg
    app.state.router = router
    app.state.broker = broker
    app.state.loop = loop
    app.state.sessions = sessions

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

    return app


def main() -> None:
    import uvicorn

    host = os.environ.get("AEON_API_HOST", "0.0.0.0")
    port = int(os.environ.get("AEON_API_PORT", "8900"))
    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    main()
