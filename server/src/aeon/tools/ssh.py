"""Approval-gated SSH command tool for known host aliases."""
import os
import subprocess
from pathlib import Path
from typing import Dict, Set

from aeon.core.config import Config
from aeon.core.tools import ToolDefinition

TIMEOUT_SECONDS = 90
MAX_OUTPUT = 20_000


def _configured_hosts() -> Set[str]:
    hosts: Set[str] = set()
    for raw in os.environ.get("AEON_SSH_HOSTS", "").split(","):
        host = raw.strip()
        if host:
            hosts.add(host)
    config_path = Path.home() / ".ssh" / "config"
    if config_path.is_file():
        try:
            for line in config_path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped.lower().startswith("host "):
                    continue
                for alias in stripped.split()[1:]:
                    if "*" not in alias and "?" not in alias and alias != "!":
                        hosts.add(alias)
        except OSError:
            pass
    return hosts


def ssh_run(arguments: Dict, config: Config) -> Dict:
    host = str(arguments.get("host") or "").strip()
    command = str(arguments.get("command") or "").strip()
    if not host:
        return {"error": "host is required"}
    if not command:
        return {"error": "command is required"}
    allowed = _configured_hosts()
    if host not in allowed:
        return {
            "error": f"host '{host}' is not in AEON_SSH_HOSTS or ~/.ssh/config",
            "allowed_hosts": sorted(allowed),
        }
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, command],
        cwd=str(config.base_path),
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
    )
    return {
        "host": host,
        "command": command,
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-MAX_OUTPUT:],
        "stderr": proc.stderr[-MAX_OUTPUT:],
    }


DEFINITIONS = [
    ToolDefinition(
        name="ssh_run",
        description=(
            "Run a command over SSH on a configured host alias. Requires human "
            "approval. Hosts must be listed in AEON_SSH_HOSTS or ~/.ssh/config."
        ),
        parameters={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "SSH host alias, e.g. t3610"},
                "command": {"type": "string", "description": "Remote command to run"},
            },
            "required": ["host", "command"],
        },
        tags=["ssh", "shell"],
        approval_required=True,
    ),
]

HANDLERS = {"ssh_run": ssh_run}
