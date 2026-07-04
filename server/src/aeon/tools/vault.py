"""Master Vault tools — strictly read-only, per the 2026-06-29 boundary
decision: the shared vault is context, not Aeon memory."""
from pathlib import Path
from typing import Dict

from aeon.core.config import Config
from aeon.core.shared_vault import is_available, search_shared_vault
from aeon.core.tools import ToolDefinition


def vault_search(arguments: Dict, config: Config) -> Dict:
    if not is_available(config):
        return {"error": "Master Vault is not configured (AEON_V1_MASTER_VAULT_PATH)"}
    results = search_shared_vault(
        arguments["query"], config, limit=int(arguments.get("limit", 5))
    )
    return {"query": arguments["query"], "results": results}


def vault_read(arguments: Dict, config: Config) -> Dict:
    if not is_available(config):
        return {"error": "Master Vault is not configured (AEON_V1_MASTER_VAULT_PATH)"}
    root = config.master_vault_path.resolve()
    target = (root / arguments["path"]).resolve()
    if not (target == root or target.is_relative_to(root)):
        raise PermissionError(f"Path escapes the Master Vault: {arguments['path']}")
    return {"path": arguments["path"], "text": target.read_text(encoding="utf-8")[:50_000]}


DEFINITIONS = [
    ToolDefinition(
        name="vault_search",
        description="Search the shared Master Vault (read-only cross-assistant context).",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "description": "Max results, default 5"},
            },
            "required": ["query"],
        },
        tags=["vault"],
        approval_required=False,
    ),
    ToolDefinition(
        name="vault_read",
        description="Read a note from the Master Vault by relative path (read-only).",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        tags=["vault"],
        approval_required=False,
    ),
]

HANDLERS = {"vault_search": vault_search, "vault_read": vault_read}
