"""Tool call record storage for Aeon-V1 Layer 5.

ToolCallStore persists every structured tool call produced by simulate_action()
as its own record, with bidirectional links back to the originating simulation
and task for full traceability.

SAFETY GUARANTEE
================
This module NEVER imports or calls:
  subprocess, os.system, os.popen, shutil, exec, eval,
  PowerShell, bash, shell, or any network/execution primitive.

Records are written to:
  memory/tool_calls/<id>.json   — machine-readable record
  vault/tool_calls/<id>.md      — Obsidian-readable note with wikilinks

vault/core/ is never touched.
"""
import json
from typing import Dict, List, Optional

from .config import Config
from .memory_store import _generate_id, _wikilink
from .time_utils import local_date_time_string, utc_now_iso


class ToolCallStore:
    """Persist and retrieve tool call records.

    Each record is the result of _match_tool_call() being run during
    simulate_action(). The record links back to the simulation that
    produced it and the task that drove the simulation.
    """

    def __init__(self, config: Config):
        self.config = config
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        (self.config.memory_path / "tool_calls").mkdir(parents=True, exist_ok=True)
        (self.config.vault_path  / "tool_calls").mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- write --

    def create(
        self,
        tool_call: Dict,
        simulation_id: str,
        task_id: str,
        task_title: str,
    ) -> Dict:
        """Build, persist, and return a new tool call record.

        Args:
            tool_call:     The tool_call dict from _match_tool_call().
            simulation_id: ID of the simulation that owns this call.
            task_id:       ID of the source task.
            task_title:    Human-readable title of the source task.

        Returns:
            The complete persisted record dict.
        """
        call_id   = _generate_id()
        now       = utc_now_iso()
        sim_link  = _wikilink("simulations", simulation_id, simulation_id)
        task_link = _wikilink("tasks",       task_id,       task_title)

        record: Dict = {
            "id":                call_id,
            "tool_name":         tool_call["tool"],
            "arguments":         tool_call.get("arguments", {}),
            "matched_by":        tool_call.get("matched_by", "keyword"),
            "simulation_id":     simulation_id,
            "task_id":           task_id,
            "task_title":        task_title,
            "status":            "pending_review",
            "approval_required": tool_call.get("approval_required", True),
            "created_at":        now,
            "source_links":      [sim_link, task_link],
        }

        (self.config.memory_path / "tool_calls" / f"{call_id}.json").write_text(
            json.dumps(record, indent=2), encoding="utf-8"
        )
        self._write_markdown(record)
        return record

    # ----------------------------------------------------------------- read --

    def get(self, call_id: str) -> Optional[Dict]:
        """Return a record by ID, or None if not found."""
        path = self.config.memory_path / "tool_calls" / f"{call_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def list_tool_calls(
        self,
        status:    Optional[str] = None,
        tool_name: Optional[str] = None,
    ) -> List[Dict]:
        """Return all tool call records, with optional filters.

        Args:
            status:    Keep only records whose status matches this value.
            tool_name: Keep only records whose tool_name matches this value.
        """
        call_dir = self.config.memory_path / "tool_calls"
        if not call_dir.exists():
            return []
        records: List[Dict] = []
        for f in call_dir.glob("*.json"):
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if status    is not None and r.get("status")    != status:
                continue
            if tool_name is not None and r.get("tool_name") != tool_name:
                continue
            records.append(r)
        return sorted(records, key=lambda r: r.get("created_at", ""))

    # ------------------------------------------------------------ markdown --

    def _write_markdown(self, record: Dict) -> None:
        md_path = self.config.vault_path / "tool_calls" / f"{record['id']}.md"
        fm_lines = [
            "---",
            f"id: {record['id']}",
            f"type: tool_call",
            f"tool_name: {record['tool_name']}",
            f"status: {record['status']}",
            f"simulation_id: {record['simulation_id']}",
            f"task_id: {record['task_id']}",
            f"created_at: {record['created_at']}",
            "---",
        ]

        args_json = json.dumps(record.get("arguments", {}), indent=2)
        local_ts  = local_date_time_string(record["created_at"], self.config.display_timezone)
        sim_link  = _wikilink("simulations", record["simulation_id"], record["simulation_id"])
        task_link = _wikilink("tasks",       record["task_id"],       record["task_title"])

        body = (
            f"# Tool Call — {record['tool_name']}\n\n"
            f"**Created:** {local_ts}\n\n"
            f"**Tool:** `{record['tool_name']}`  |  "
            f"**Status:** `{record['status']}`  |  "
            f"**Approval Required:** `{record['approval_required']}`\n\n"
            f"## Arguments\n\n```json\n{args_json}\n```\n\n"
            f"## Traceability\n\n"
            f"**Simulation:** {sim_link}\n\n"
            f"**Task:** {task_link}\n\n"
            "> **PENDING REVIEW** — this call has not been approved or executed.\n"
            "> Human approval is required before any action can be taken.\n\n"
            "[[Tool Calls]] | [[Simulations]] | [[Tasks]]"
        )
        md_path.write_text("\n".join(fm_lines) + "\n\n" + body, encoding="utf-8")
