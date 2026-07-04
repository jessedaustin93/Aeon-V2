"""Chat session persistence: one JSON file per session under
<data>/memory/logs/sessions/."""
import json
import uuid
from typing import Dict, List, Optional

from aeon.core.config import Config
from aeon.core.time_utils import utc_now_iso


class SessionStore:
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.dir = self.config.memory_path / "logs" / "sessions"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str):
        return self.dir / f"{session_id}.json"

    def create(self, title: str = "") -> Dict:
        session = {
            "id": uuid.uuid4().hex[:12],
            "title": title or "New chat",
            "created_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
            "messages": [],
        }
        self._save(session)
        return session

    def get(self, session_id: str) -> Optional[Dict]:
        path = self._path(session_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def list(self) -> List[Dict]:
        sessions = []
        for path in self.dir.glob("*.json"):
            try:
                s = json.loads(path.read_text(encoding="utf-8"))
                sessions.append(
                    {
                        "id": s["id"],
                        "title": s.get("title", ""),
                        "updated_at": s.get("updated_at", ""),
                        "message_count": len(s.get("messages", [])),
                    }
                )
            except (OSError, json.JSONDecodeError, KeyError):
                continue
        return sorted(sessions, key=lambda s: s["updated_at"], reverse=True)

    def append(self, session_id: str, message: Dict) -> Dict:
        session = self.get(session_id)
        if session is None:
            raise KeyError(f"Unknown session: {session_id}")
        session["messages"].append(message)
        session["updated_at"] = utc_now_iso()
        if session["title"] == "New chat" and message.get("role") == "user":
            session["title"] = (message.get("content") or "")[:60] or "New chat"
        self._save(session)
        return session

    def _save(self, session: Dict) -> None:
        self._path(session["id"]).write_text(
            json.dumps(session, indent=2), encoding="utf-8"
        )
