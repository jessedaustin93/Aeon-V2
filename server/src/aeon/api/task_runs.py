"""Background task runs for checks that should not occupy chat."""
import json
import re
import threading
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from aeon.agent.approvals import ApprovalBroker
from aeon.agent.loop import AgentLoop
from aeon.core.config import Config
from aeon.core.time_utils import utc_now_iso
from aeon.models.router import ModelRouter
from aeon.skills import SkillStore

_TASK_RUN_ID_RE = re.compile(r"^[a-f0-9]{12}$")


class TaskRunStore:
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.dir = self.config.memory_path / "logs" / "task-runs"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, run_id: str) -> Path:
        if not _TASK_RUN_ID_RE.match(run_id):
            raise ValueError(f"Invalid task run id: {run_id!r}")
        return self.dir / f"{run_id}.json"

    def create(self, prompt: str, title: str = "", role: str = "chat") -> Dict:
        now = utc_now_iso()
        run = {
            "id": uuid.uuid4().hex[:12],
            "title": title or prompt[:80] or "Background task",
            "prompt": prompt,
            "role": role or "chat",
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "result": "",
            "error": "",
            "events": [],
        }
        self.save(run)
        return run

    def get(self, run_id: str) -> Optional[Dict]:
        try:
            path = self._path(run_id)
        except ValueError:
            return None
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def list(self) -> List[Dict]:
        runs = []
        for path in self.dir.glob("*.json"):
            try:
                run = json.loads(path.read_text(encoding="utf-8"))
                runs.append({k: run.get(k, "") for k in (
                    "id", "title", "prompt", "role", "status", "created_at",
                    "updated_at", "result", "error",
                )})
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(runs, key=lambda r: r.get("updated_at", ""), reverse=True)

    def save(self, run: Dict) -> Dict:
        run["updated_at"] = utc_now_iso()
        with self._lock:
            self._path(run["id"]).write_text(json.dumps(run, indent=2), encoding="utf-8")
        return run

    def patch(self, run_id: str, **fields) -> Optional[Dict]:
        run = self.get(run_id)
        if run is None:
            return None
        run.update(fields)
        return self.save(run)

    def append_event(self, run_id: str, event: Dict) -> Optional[Dict]:
        run = self.get(run_id)
        if run is None:
            return None
        events = list(run.get("events") or [])
        events.append(event)
        run["events"] = events[-200:]
        return self.save(run)


class ThreadedTaskRunner:
    def __init__(
        self,
        config: Config,
        store: TaskRunStore,
        router: ModelRouter,
        broker: ApprovalBroker,
        skill_store: SkillStore,
    ):
        self.config = config
        self.store = store
        self.router = router
        self.broker = broker
        self.skill_store = skill_store

    def start(self, prompt: str, title: str = "", role: str = "chat") -> Dict:
        run = self.store.create(prompt=prompt, title=title, role=role)
        thread = threading.Thread(
            target=self._run,
            args=(run["id"], prompt, role),
            name=f"aeon-task-{run['id']}",
            daemon=True,
        )
        thread.start()
        return run

    def _run(self, run_id: str, prompt: str, role: str) -> None:
        self.store.patch(run_id, status="running")
        reply = ""
        loop = AgentLoop(
            config=self.config,
            router=self.router,
            broker=self.broker,
            skill_store=self.skill_store,
            approval_timeout=120.0,
        )
        try:
            for event in loop.run([{"role": "user", "content": prompt}], role=role):
                self.store.append_event(run_id, {"kind": event.kind, "data": event.data})
                if event.kind == "text":
                    reply += event.data.get("text", "")
                elif event.kind == "done":
                    if not reply:
                        reply = event.data.get("text", "")
                    self.store.patch(run_id, status="done", result=reply)
                    return
                elif event.kind == "error":
                    self.store.patch(
                        run_id,
                        status="error",
                        result=reply,
                        error=event.data.get("error", "unknown error"),
                    )
                    return
            self.store.patch(run_id, status="done", result=reply)
        except Exception as exc:  # noqa: BLE001 - task runner must persist failures
            self.store.patch(
                run_id,
                status="error",
                result=reply,
                error=f"{type(exc).__name__}: {exc}",
            )
