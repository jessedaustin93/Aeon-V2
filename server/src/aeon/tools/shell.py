"""Shell execution tool — always approval-gated."""
import subprocess
from typing import Dict

from aeon.core.config import Config
from aeon.core.tools import ToolDefinition

TIMEOUT_SECONDS = 60


def shell_run(arguments: Dict, config: Config) -> Dict:
    command = arguments["command"]
    cwd = arguments.get("cwd") or str(config.base_path)
    proc = subprocess.run(
        command,
        shell=True,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
    )
    return {
        "command": command,
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-20_000:],
        "stderr": proc.stderr[-20_000:],
    }


DEFINITIONS = [
    ToolDefinition(
        name="shell_run",
        description=(
            "Run a shell command on the Aeon server. Requires human approval "
            "before every execution."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string", "description": "Working directory (optional)"},
            },
            "required": ["command"],
        },
        tags=["shell"],
        approval_required=True,
    ),
]

HANDLERS = {"shell_run": shell_run}
