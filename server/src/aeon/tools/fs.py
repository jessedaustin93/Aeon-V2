"""Scoped filesystem tools.

Reads are limited to the Aeon data root plus any roots listed in the
AEON_TOOLS_FS_ROOTS env var (colon-separated). Everything else is refused.
"""
import os
from pathlib import Path
from typing import Dict

from aeon.core.config import Config
from aeon.core.tools import ToolDefinition

MAX_READ_BYTES = 50_000


def _allowed_roots(config: Config) -> list[Path]:
    roots = [config.base_path.resolve()]
    extra = os.environ.get("AEON_TOOLS_FS_ROOTS", "").strip()
    if extra:
        roots.extend(Path(p).expanduser().resolve() for p in extra.split(":") if p)
    return roots


def _check_scope(path: Path, config: Config) -> None:
    resolved = path.resolve()
    for root in _allowed_roots(config):
        if resolved == root or resolved.is_relative_to(root):
            return
    raise PermissionError(f"Path outside allowed roots: {path}")


def fs_read(arguments: Dict, config: Config) -> Dict:
    path = Path(arguments["path"]).expanduser()
    _check_scope(path, config)
    data = path.read_bytes()[:MAX_READ_BYTES]
    return {"path": str(path), "text": data.decode("utf-8", errors="replace")}


def fs_list(arguments: Dict, config: Config) -> Dict:
    path = Path(arguments["path"]).expanduser()
    _check_scope(path, config)
    entries = [
        {"name": p.name, "type": "dir" if p.is_dir() else "file"}
        for p in sorted(path.iterdir(), key=lambda p: p.name)
    ]
    return {"path": str(path), "entries": entries}


DEFINITIONS = [
    ToolDefinition(
        name="fs_read",
        description="Read a text file inside the allowed roots (data dir + AEON_TOOLS_FS_ROOTS).",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        tags=["fs"],
        approval_required=False,
    ),
    ToolDefinition(
        name="fs_list",
        description="List a directory inside the allowed roots.",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        tags=["fs"],
        approval_required=False,
    ),
]

HANDLERS = {"fs_read": fs_read, "fs_list": fs_list}
