"""HTTP wrapper over the Agent Mesh hub protocol.

Endpoints (Bearer token auth), matching the existing agent-mesh bridge:
    POST /api/heartbeat            {agent_id, machine, status}
    GET  /api/inbox/{agent}?after= -> [ {id, thread_id, sender, content, ...} ]
    POST /api/messages            {thread_id, sender, recipient, kind, content}
    POST /api/messages/{id}/ack
"""
import json
import os
import socket
import urllib.request
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

HttpRequest = Callable[[str, str, Dict[str, str], Optional[bytes]], object]


def _default_http_request(
    method: str, url: str, headers: Dict[str, str], body: Optional[bytes]
) -> object:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else None


@dataclass
class MeshConfig:
    hub: str = ""
    token: str = ""
    agent_id: str = ""
    machine: str = ""

    @classmethod
    def from_env(cls) -> "MeshConfig":
        host = socket.gethostname()
        return cls(
            hub=os.environ.get("AEON_MESH_HUB", "").strip().rstrip("/"),
            token=os.environ.get("AEON_MESH_TOKEN", "").strip(),
            agent_id=os.environ.get("AEON_MESH_AGENT_ID", "").strip() or f"aeon@{host}",
            machine=os.environ.get("AEON_MESH_MACHINE", "").strip() or host,
        )


class MeshClient:
    def __init__(self, config: MeshConfig, http_request: Optional[HttpRequest] = None):
        self.config = config
        self._http = http_request or _default_http_request

    @property
    def configured(self) -> bool:
        return bool(self.config.hub and self.config.token)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.token}",
            "Content-Type": "application/json",
        }

    def _call(self, method: str, path: str, body: Optional[Dict] = None) -> object:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        url = self.config.hub + path
        return self._http(method, url, self._headers(), data)

    def get(self, path: str) -> object:
        return self._call("GET", path)

    def heartbeat(self, status: str = "idle") -> None:
        self._call("POST", "/api/heartbeat", {
            "agent_id": self.config.agent_id,
            "machine": self.config.machine,
            "status": status,
        })

    def inbox(self, after: int = 0) -> List[Dict]:
        result = self._call("GET", f"/api/inbox/{self.config.agent_id}?after={after}")
        if isinstance(result, dict):
            return result.get("messages", [])
        return result or []

    def post_message(self, thread_id, recipient: str, content: str, kind: str = "reply") -> Dict:
        result = self._call("POST", "/api/messages", {
            "thread_id": thread_id,
            "sender": self.config.agent_id,
            "recipient": recipient,
            "kind": kind,
            "content": content,
        })
        return result if isinstance(result, dict) else {}

    def ack(self, message_id) -> None:
        self._call("POST", f"/api/messages/{message_id}/ack")

    def agents(self) -> List[Dict]:
        result = self.get("/api/agents")
        return result if isinstance(result, list) else []

    def kernel_programs(self) -> List[Dict]:
        result = self.get("/api/kernel/programs")
        return result if isinstance(result, list) else []

    def kernel_status(self) -> Dict:
        result = self.get("/api/kernel/status")
        return result if isinstance(result, dict) else {}

    def stations(self) -> Dict:
        result = self.get("/api/stations")
        return result if isinstance(result, dict) else {}

    def telemetry(self) -> List[Dict]:
        result = self.get("/api/telemetry")
        return result if isinstance(result, list) else []
