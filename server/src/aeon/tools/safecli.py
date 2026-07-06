"""Autonomous read-only shell: a curated allowlist Aeon can run without asking.

Anything that mutates state, or isn't on the list, still goes through the
approval-gated shell_run. Two defenses: (1) the command is rejected outright if
it contains any shell metacharacter, so it cannot chain/redirect/substitute into
something off-list; (2) the first token (and, where relevant, the subcommand)
must be explicitly allowlisted.
"""
import shlex
import subprocess
from typing import Dict, Optional, Set

from aeon.core.config import Config
from aeon.core.tools import ToolDefinition

# Characters that enable chaining, redirection, or substitution. Their presence
# means the input isn't a single simple command, so we refuse it.
_METACHARS = set(";|&<>`$()\n\\")

# None = the whole command is read-only; a set = only these subcommands are.
ALLOWLIST: Dict[str, Optional[Set[str]]] = {
    "df": None, "free": None, "uptime": None, "uname": None, "ps": None,
    "ip": None, "ss": None, "lsblk": None, "whoami": None, "hostname": None,
    "date": None, "nvidia-smi": None, "sensors": None, "journalctl": None,
    "lscpu": None, "lsusb": None, "lspci": None, "who": None, "id": None,
    "systemctl": {"status", "is-active", "is-enabled", "is-failed",
                  "list-units", "list-unit-files", "show", "cat"},
    "docker": {"ps", "images", "stats", "logs", "inspect", "version", "info", "top"},
    "git": {"status", "log", "diff", "show", "branch", "remote"},
}

MAX_OUTPUT = 20_000
TIMEOUT = 30


def _first_subcommand(tokens: list[str]) -> Optional[str]:
    # First token after the command that isn't a flag.
    for tok in tokens[1:]:
        if not tok.startswith("-"):
            return tok
    return None


def safe_shell(arguments: Dict, config: Config) -> Dict:
    command = arguments["command"]
    if any(ch in _METACHARS for ch in command):
        return {"error": "command contains shell metacharacters; use shell_run (approval-gated) instead"}
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return {"error": f"could not parse command: {exc}"}
    if not tokens:
        return {"error": "empty command"}

    cmd = tokens[0]
    if cmd not in ALLOWLIST:
        return {"error": f"'{cmd}' is not on the read-only allowlist; use shell_run for that"}
    allowed_subs = ALLOWLIST[cmd]
    if allowed_subs is not None:
        sub = _first_subcommand(tokens)
        if sub not in allowed_subs:
            return {
                "error": f"'{cmd} {sub}' is not allowed (read-only subcommands: "
                         f"{', '.join(sorted(allowed_subs))}); use shell_run for that"
            }

    try:
        proc = subprocess.run(
            tokens, capture_output=True, text=True, timeout=TIMEOUT,
            cwd=str(config.base_path),
        )
    except FileNotFoundError:
        return {"error": f"command not found: {cmd}"}
    except subprocess.TimeoutExpired:
        return {"error": f"timed out after {TIMEOUT}s"}
    return {
        "command": command,
        "exit_code": proc.returncode,
        "stdout": proc.stdout[:MAX_OUTPUT],
        "stderr": proc.stderr[:MAX_OUTPUT],
    }


DEFINITIONS = [
    ToolDefinition(
        name="safe_shell",
        description=(
            "Run a read-only inspection command (df, free, uptime, ps, ip, "
            "systemctl status, docker ps/logs, journalctl, git status/log, ...). "
            "No approval needed. For anything that changes state, use shell_run."
        ),
        parameters={"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
        tags=["shell", "readonly"],
        approval_required=False,
    ),
]

HANDLERS = {"safe_shell": safe_shell}
