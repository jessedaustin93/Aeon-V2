"""Role → model → worker routing.

Roles ("chat", "deep", "embed") map to model names; workers are
OpenAI-compatible endpoints (local LM Studio, other mesh machines).
Configuration comes from <AEON_DATA_DIR>/models.json when present,
otherwise from environment variables, falling back to the aeon-v1
AEON_V1_LLM_* names so the existing T5810 .env keeps working.
"""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from aeon.core.config import Config

from .client import ChatClient

DEFAULT_BASE_URL = "http://localhost:1234/v1"

# role -> (v2 env var, v1 fallback env var)
ROLE_ENV = {
    "chat": ("AEON_LLM_CHAT_MODEL", "AEON_V1_LLM_MODEL"),
    "deep": ("AEON_LLM_DEEP_MODEL", "AEON_V1_LLM_DEEP_MODEL"),
    "embed": ("AEON_LLM_EMBED_MODEL", "AEON_V1_LLM_EMBEDDING_MODEL"),
}


def _env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


@dataclass
class Worker:
    name: str
    base_url: str
    models: List[str] = field(default_factory=lambda: ["*"])
    priority: int = 0
    healthy: bool = True

    def serves(self, model: str) -> bool:
        return "*" in self.models or model in self.models


class ModelRouter:
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.roles: Dict[str, str] = {}
        self.workers: List[Worker] = []
        self._clients: Dict[str, ChatClient] = {}
        self._load()

    def _load(self) -> None:
        path = self.config.base_path / "models.json"
        data: Dict = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
        self.roles = dict(data.get("roles") or {})
        for role, (v2, v1) in ROLE_ENV.items():
            env_model = _env(v2, v1)
            if env_model and role not in self.roles:
                self.roles[role] = env_model
        raw_workers = data.get("workers") or []
        if raw_workers:
            self.workers = [
                Worker(
                    name=w.get("name", f"worker{i}"),
                    base_url=w["base_url"].rstrip("/"),
                    models=list(w.get("models") or ["*"]),
                    priority=int(w.get("priority", 0)),
                )
                for i, w in enumerate(raw_workers)
            ]
        else:
            base_url = _env("AEON_LLM_BASE_URL", "AEON_V1_LLM_BASE_URL") or DEFAULT_BASE_URL
            self.workers = [Worker(name="local", base_url=base_url.rstrip("/"))]

    def _client(self, worker: Worker) -> ChatClient:
        if worker.base_url not in self._clients:
            self._clients[worker.base_url] = ChatClient(worker.base_url)
        return self._clients[worker.base_url]

    def resolve(self, role: str) -> Tuple[ChatClient, str]:
        model = self.roles.get(role, "")
        if not model:
            raise ValueError(
                f"No model configured for role '{role}'. "
                "Set it in models.json or AEON_LLM_*_MODEL."
            )
        candidates = [w for w in self.workers if w.healthy and w.serves(model)]
        if not candidates:
            raise ValueError(f"No healthy worker serves model '{model}' for role '{role}'")
        best = max(candidates, key=lambda w: w.priority)
        return self._client(best), model

    def health_check(self) -> Dict[str, bool]:
        status: Dict[str, bool] = {}
        for worker in self.workers:
            try:
                self._client(worker).list_models()
                worker.healthy = True
            except Exception:
                worker.healthy = False
            status[worker.name] = worker.healthy
        return status
