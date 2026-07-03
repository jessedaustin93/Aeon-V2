"""Tool registry for Aeon-V1 Layer 5.

ToolRegistry stores tool *definitions* only — names, descriptions, and
parameter schemas. No tool is ever called, scheduled, or executed here.

SAFETY GUARANTEE
================
This module NEVER imports or calls:
  subprocess, os.system, os.popen, shutil, exec, eval,
  PowerShell, bash, shell, or any network/execution primitive.

Tools are persisted as JSON in memory/schemas/tools/ and as Markdown in
vault/agents/. vault/core/ is never touched.
"""
import json
from typing import Dict, List, Optional

from .config import Config
from .exceptions import ToolAlreadyRegisteredError
from .time_utils import local_date_time_string, utc_now_iso


def _validate_parameters(schema: Dict) -> None:
    if not isinstance(schema, dict):
        raise ValueError("parameters must be a dict (JSON Schema object)")
    declared_type = schema.get("type")
    if declared_type is not None and declared_type != "object":
        raise ValueError(
            f"parameters.type must be 'object' or omitted, got '{declared_type}'"
        )


class ToolDefinition:
    """Immutable description of a single tool.

    Parameters follow JSON Schema conventions: an object with optional
    ``properties`` and ``required`` keys. The ``type`` field, if present,
    must be ``"object"``.
    """

    __slots__ = (
        "name", "description", "parameters",
        "tags", "layer", "enabled", "approval_required", "registered_at",
    )

    def __init__(
        self,
        name: str,
        description: str,
        parameters: Optional[Dict] = None,
        tags: Optional[List[str]] = None,
        layer: int = 0,
        enabled: bool = True,
        approval_required: bool = True,
        registered_at: Optional[str] = None,
    ):
        if not name or not name.strip():
            raise ValueError("Tool name must be a non-empty string")
        if not description or not description.strip():
            raise ValueError("Tool description must be a non-empty string")
        params = parameters if parameters is not None else {}
        _validate_parameters(params)
        self.name: str = name.strip()
        self.description: str = description.strip()
        self.parameters: Dict = params
        self.tags: List[str] = list(tags or [])
        self.layer: int = layer
        self.enabled: bool = enabled
        self.approval_required: bool = approval_required
        self.registered_at: str = registered_at or utc_now_iso()

    def to_dict(self) -> Dict:
        return {
            "name":              self.name,
            "description":       self.description,
            "parameters":        self.parameters,
            "tags":              self.tags,
            "layer":             self.layer,
            "enabled":           self.enabled,
            "approval_required": self.approval_required,
            "registered_at":     self.registered_at,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "ToolDefinition":
        return cls(
            name=data["name"],
            description=data["description"],
            parameters=data.get("parameters", {}),
            tags=data.get("tags", []),
            layer=data.get("layer", 0),
            enabled=data.get("enabled", True),
            approval_required=data.get("approval_required", True),
            registered_at=data.get("registered_at"),
        )


class ToolRegistry:
    """Store and retrieve tool definitions.

    JSON records live in  memory/schemas/tools/<name>.json.
    Markdown notes live in vault/agents/<name>.md.
    No tool is ever invoked by this class.
    """

    def __init__(self, config: Config):
        self.config = config
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        (self.config.memory_path / "schemas" / "tools").mkdir(parents=True, exist_ok=True)
        (self.config.vault_path / "agents").mkdir(parents=True, exist_ok=True)

    def _json_path(self, name: str):
        return self.config.memory_path / "schemas" / "tools" / f"{name}.json"

    def _md_path(self, name: str):
        return self.config.vault_path / "agents" / f"{name}.md"

    # ---------------------------------------------------------------- write --

    def register(self, tool: ToolDefinition) -> ToolDefinition:
        """Persist a tool definition to disk.

        Raises ToolAlreadyRegisteredError if a tool with that name already
        exists and config.allow_tool_override is False.
        """
        if self._json_path(tool.name).exists() and not self.config.allow_tool_override:
            raise ToolAlreadyRegisteredError(
                f"Tool '{tool.name}' is already registered. "
                "Set config.allow_tool_override = True to replace it."
            )
        self._json_path(tool.name).write_text(
            json.dumps(tool.to_dict(), indent=2), encoding="utf-8"
        )
        self._write_markdown(tool)
        return tool

    def unregister(self, name: str) -> bool:
        """Delete a tool definition. Returns True if the tool existed."""
        json_path = self._json_path(name)
        md_path   = self._md_path(name)
        removed   = json_path.exists()
        if json_path.exists():
            json_path.unlink()
        if md_path.exists():
            md_path.unlink()
        return removed

    # ----------------------------------------------------------------- read --

    def get(self, name: str) -> Optional[ToolDefinition]:
        """Return a ToolDefinition by name, or None if not registered."""
        path = self._json_path(name)
        if not path.exists():
            return None
        return ToolDefinition.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list_tools(
        self,
        tag:     Optional[str]  = None,
        layer:   Optional[int]  = None,
        enabled: Optional[bool] = None,
    ) -> List[ToolDefinition]:
        """Return all registered tools, with optional filters.

        Args:
            tag:     Keep only tools whose tags list includes this value.
            layer:   Keep only tools whose layer matches exactly.
            enabled: Keep only tools matching this enabled state.
        """
        tool_dir = self.config.memory_path / "schemas" / "tools"
        if not tool_dir.exists():
            return []
        tools: List[ToolDefinition] = []
        for f in tool_dir.glob("*.json"):
            try:
                td = ToolDefinition.from_dict(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                continue
            if tag     is not None and tag     not in td.tags:
                continue
            if layer   is not None and td.layer   != layer:
                continue
            if enabled is not None and td.enabled != enabled:
                continue
            tools.append(td)
        return sorted(tools, key=lambda t: t.registered_at)

    # ------------------------------------------------------------ markdown --

    def _write_markdown(self, tool: ToolDefinition) -> None:
        fm_lines = [
            "---",
            f"name: {tool.name}",
            f"type: tool_definition",
            f"layer: {tool.layer}",
            f"enabled: {str(tool.enabled).lower()}",
            f"approval_required: {str(tool.approval_required).lower()}",
            f"registered_at: {tool.registered_at}",
            "tags:",
        ]
        for t in tool.tags:
            fm_lines.append(f"  - {t}")
        fm_lines.append("---")

        params_json = json.dumps(tool.parameters, indent=2) if tool.parameters else "{}"
        local_ts = local_date_time_string(tool.registered_at, self.config.display_timezone)

        body = (
            f"# Tool: {tool.name}\n\n"
            f"**Registered:** {local_ts}\n\n"
            f"**Layer:** {tool.layer}  |  **Enabled:** `{tool.enabled}`  |  "
            f"**Approval Required:** `{tool.approval_required}`\n\n"
            f"## Description\n\n{tool.description}\n\n"
            f"## Parameters\n\n```json\n{params_json}\n```\n\n"
            "> **DEFINITION ONLY** — this registry never calls or executes tools.\n\n"
            "[[Agents]] | [[Tasks]] | [[Simulations]]"
        )
        self._md_path(tool.name).write_text(
            "\n".join(fm_lines) + "\n\n" + body, encoding="utf-8"
        )
