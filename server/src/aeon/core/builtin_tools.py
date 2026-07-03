"""Built-in tool schema definitions for Aeon-V1 Layer 5.

Defines ToolDefinition records for the three core tool slots:
  FILE_READ       — describe reading a file
  FILE_WRITE      — describe writing a file
  COMMAND_PREVIEW — describe a shell command without running it

SAFETY GUARANTEE
================
This module NEVER imports or calls:
  subprocess, os.system, os.popen, shutil, exec, eval,
  PowerShell, bash, shell, or any network/execution primitive.

These are definition-only records. No file is read or written by this
module; no command is executed. vault/core/ is never touched.
"""
from typing import List

from .tools import ToolDefinition, ToolRegistry


FILE_READ = ToolDefinition(
    name="file_read",
    approval_required=True,
    description=(
        "Read the text contents of a file at a given path. "
        "Supports optional line offset and line limit for large files. "
        "This is a definition — no file is opened by the registry."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type":        "string",
                "description": "Absolute or relative path to the file to read.",
            },
            "encoding": {
                "type":        "string",
                "description": "Text encoding of the file.",
                "default":     "utf-8",
            },
            "offset": {
                "type":        "integer",
                "description": "1-based line number to start reading from.",
                "minimum":     1,
            },
            "limit": {
                "type":        "integer",
                "description": "Maximum number of lines to return.",
                "minimum":     1,
            },
        },
        "required": ["path"],
    },
    tags=["file", "read", "io"],
    layer=5,
)

FILE_WRITE = ToolDefinition(
    name="file_write",
    approval_required=True,
    description=(
        "Write text content to a file at a given path, creating it if it does "
        "not exist. Supports overwrite and append modes. "
        "This is a definition — no file is written by the registry."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type":        "string",
                "description": "Absolute or relative path to the file to write.",
            },
            "content": {
                "type":        "string",
                "description": "Text content to write to the file.",
            },
            "encoding": {
                "type":        "string",
                "description": "Text encoding to use when writing.",
                "default":     "utf-8",
            },
            "mode": {
                "type":        "string",
                "description": "Write mode: 'overwrite' replaces the file; 'append' adds to it.",
                "enum":        ["overwrite", "append"],
                "default":     "overwrite",
            },
        },
        "required": ["path", "content"],
    },
    tags=["file", "write", "io"],
    layer=5,
)

COMMAND_PREVIEW = ToolDefinition(
    name="command_preview",
    approval_required=True,
    description=(
        "Produce a structured, human-readable preview of a shell command and its "
        "expected effects — without executing it. The preview must be reviewed and "
        "approved by a human before any real execution takes place. "
        "This is a definition — no command is run by the registry."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type":        "string",
                "description": "The shell command to preview.",
            },
            "working_directory": {
                "type":        "string",
                "description": "Directory in which the command would run.",
            },
            "shell": {
                "type":        "string",
                "description": "Shell interpreter (e.g. 'bash', 'powershell', 'sh').",
                "default":     "bash",
            },
            "environment": {
                "type":        "object",
                "description": "Key/value pairs of environment variables the command would receive.",
            },
        },
        "required": ["command"],
    },
    tags=["command", "preview", "simulation"],
    layer=5,
)

BUILTIN_TOOLS: List[ToolDefinition] = [FILE_READ, FILE_WRITE, COMMAND_PREVIEW]


def register_builtin_tools(registry: ToolRegistry) -> List[ToolDefinition]:
    """Register all built-in tool definitions into a ToolRegistry.

    Skips any tool that is already registered (does not raise).
    Returns the list of tools that were newly registered.
    """
    from .exceptions import ToolAlreadyRegisteredError

    registered: List[ToolDefinition] = []
    for tool in BUILTIN_TOOLS:
        try:
            registry.register(tool)
            registered.append(tool)
        except ToolAlreadyRegisteredError:
            pass
    return registered
