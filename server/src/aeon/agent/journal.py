"""Append-only journal of live tool executions.

One JSON object per line in <data>/memory/logs/tool_journal.jsonl.
(ToolCallStore in aeon.core is simulation-review oriented; this journal
records what the live agent actually executed.)
"""
import json
from typing import Dict, List, Optional

from aeon.core.config import Config
from aeon.core.time_utils import utc_now_iso


class ToolJournal:
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.path = self.config.memory_path / "logs" / "tool_journal.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, tool: str, arguments: Dict, result: Dict, status: str) -> Dict:
        entry = {
            "at": utc_now_iso(),
            "tool": tool,
            "arguments": arguments,
            "status": status,
            "result_preview": json.dumps(result)[:2000],
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        return entry

    def tail(self, limit: int = 50) -> List[Dict]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()[-limit:]
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
