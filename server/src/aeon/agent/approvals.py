"""Human approval broker for gated tool executions.

Requests persist to <data>/memory/staging/approvals.json so pending
approvals survive a server restart and are visible to the API/UI.
Waiting is in-process (threading.Event); a request that times out is
marked expired and treated as a denial by callers.
"""
import json
import threading
import uuid
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

from aeon.core.config import Config
from aeon.core.time_utils import utc_now_iso


@dataclass
class ApprovalRequest:
    id: str
    tool: str
    arguments: Dict
    created_at: str
    status: str  # "pending" | "approved" | "denied" | "expired"


class ApprovalBroker:
    def __init__(self, config: Optional[Config] = None, ttl_seconds: float = 300.0):
        self.config = config or Config()
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._events: Dict[str, threading.Event] = {}
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def _path(self):
        return self.config.memory_path / "staging" / "approvals.json"

    # ------------------------------------------------------------ persistence

    def _load(self) -> Dict[str, Dict]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, records: Dict[str, Dict]) -> None:
        self._path.write_text(json.dumps(records, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------- api

    def create(self, tool: str, arguments: Dict) -> ApprovalRequest:
        req = ApprovalRequest(
            id=uuid.uuid4().hex[:12],
            tool=tool,
            arguments=arguments,
            created_at=utc_now_iso(),
            status="pending",
        )
        with self._lock:
            records = self._load()
            records[req.id] = asdict(req)
            self._save(records)
            self._events[req.id] = threading.Event()
        return req

    def resolve(self, request_id: str, approved: bool) -> ApprovalRequest:
        with self._lock:
            records = self._load()
            if request_id not in records:
                raise KeyError(f"Unknown approval request: {request_id}")
            records[request_id]["status"] = "approved" if approved else "denied"
            self._save(records)
            event = self._events.get(request_id)
            if event:
                event.set()
            return ApprovalRequest(**records[request_id])

    def wait(self, request_id: str, timeout: Optional[float] = None) -> str:
        event = self._events.get(request_id)
        if event:
            event.wait(timeout if timeout is not None else self.ttl_seconds)
        with self._lock:
            records = self._load()
            record = records.get(request_id)
            if record is None:
                return "expired"
            if record["status"] == "pending":
                record["status"] = "expired"
                self._save(records)
            return record["status"]

    def get(self, request_id: str) -> Optional[ApprovalRequest]:
        record = self._load().get(request_id)
        return ApprovalRequest(**record) if record else None

    def pending(self) -> List[ApprovalRequest]:
        return [
            ApprovalRequest(**r)
            for r in self._load().values()
            if r["status"] == "pending"
        ]
