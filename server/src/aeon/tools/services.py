"""Control systemd --user services on this host.

Reading state (status/is-active) is free. Mutating state (start/stop/restart)
is a separate, approval-gated tool — Aeon can watch the lab autonomously but
changing it still asks. Cross-machine control is out of scope here (that needs
the mesh executor).
"""
import re
import subprocess
from typing import Dict

from aeon.core.config import Config
from aeon.core.tools import ToolDefinition

_SERVICE_RE = re.compile(r"^[A-Za-z0-9@._-]+$")
_ACTIONS = {"start", "stop", "restart"}
TIMEOUT = 20
REMOTE_SERVICE_HINTS = {
    "snifferops": {
        "host": "t5810b",
        "active": "not_applicable_on_this_host",
        "message": (
            "Ethrox Detect runs on T5810B, not on the local Aeon/T5810 host. "
            "Use ethrox_detect_telemetry for hub health, or ssh_run with "
            "host='t5810b' for ethrox-detect.service checks."
        ),
    },
    "snifferops.service": {
        "host": "t5810b",
        "active": "not_applicable_on_this_host",
        "message": (
            "Ethrox Detect replaced the old SnifferOps service on T5810B. "
            "Use ethrox_detect_telemetry for hub health, or ssh_run with "
            "host='t5810b' for ethrox-detect.service checks."
        ),
    },
    "ethrox-detect": {
        "host": "t5810b",
        "active": "not_applicable_on_this_host",
        "message": (
            "Ethrox Detect runs on T5810B, not on the local Aeon/T5810 host. "
            "Use ethrox_detect_telemetry for hub health, or ssh_run with "
            "host='t5810b' for ethrox-detect.service checks."
        ),
    },
    "ethrox-detect.service": {
        "host": "t5810b",
        "active": "not_applicable_on_this_host",
        "message": (
            "Ethrox Detect runs on T5810B, not on the local Aeon/T5810 host. "
            "Use ethrox_detect_telemetry for hub health, or ssh_run with "
            "host='t5810b' for ethrox-detect.service checks."
        ),
    },
}


def _valid_service(name: str) -> bool:
    return bool(name) and bool(_SERVICE_RE.match(name))


def _systemctl(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True, text=True, timeout=TIMEOUT,
    )


def service_status(arguments: Dict, config: Config) -> Dict:
    service = arguments["service"]
    if not _valid_service(service):
        return {"error": f"invalid service name: {service!r}"}
    remote_hint = REMOTE_SERVICE_HINTS.get(service.lower())
    if remote_hint:
        return {"service": service, **remote_hint}
    active = _systemctl(["is-active", service])
    status = _systemctl(["status", service, "--no-pager", "--lines", "10"])
    return {
        "service": service,
        "active": active.stdout.strip(),
        "detail": status.stdout[:8000],
    }


def service_control(arguments: Dict, config: Config) -> Dict:
    action = arguments["action"]
    service = arguments["service"]
    if action not in _ACTIONS:
        return {"error": f"action must be one of {sorted(_ACTIONS)}"}
    if not _valid_service(service):
        return {"error": f"invalid service name: {service!r}"}
    proc = _systemctl([action, service])
    active = _systemctl(["is-active", service]).stdout.strip()
    return {
        "service": service,
        "action": action,
        "exit_code": proc.returncode,
        "active": active,
        "stderr": proc.stderr[:4000],
    }


DEFINITIONS = [
    ToolDefinition(
        name="service_status",
        description="Check a systemd --user service on this host (active state + recent status).",
        parameters={"type": "object", "properties": {"service": {"type": "string"}}, "required": ["service"]},
        tags=["services"],
        approval_required=False,
    ),
    ToolDefinition(
        name="service_control",
        description="Start, stop, or restart a systemd --user service on this host. Requires approval.",
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["start", "stop", "restart"]},
                "service": {"type": "string"},
            },
            "required": ["action", "service"],
        },
        tags=["services"],
        approval_required=True,
    ),
]

HANDLERS = {"service_status": service_status, "service_control": service_control}
