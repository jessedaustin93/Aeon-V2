"""Mesh tools: read Grid Kernel state and post to Agent Mesh threads."""
import json
from datetime import datetime, timezone
from typing import Dict, List

from aeon.core.config import Config
from aeon.core.tools import ToolDefinition
from aeon.mesh import MeshClient, MeshConfig


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_seconds(value: str) -> int | None:
    ts = _parse_time(value)
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - ts).total_seconds()))


def _detail(detail: str) -> Dict:
    try:
        data = json.loads(detail or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _station_names(stations: Dict) -> Dict[str, str]:
    names: Dict[str, str] = {}
    for key, value in stations.items():
        if key.startswith("_") or not isinstance(value, dict):
            continue
        names[key] = value.get("label") or key
    return names


def _machine_aliases(stations: Dict) -> Dict[str, str]:
    aliases: Dict[str, str] = {}
    def add_alias(value: str, key: str) -> None:
        cleaned = value.strip()
        if not cleaned:
            return
        aliases[cleaned] = key
        aliases[cleaned.lower()] = key
        aliases[cleaned.lower().replace("_", "-")] = key
        aliases[cleaned.lower().replace("-", "_")] = key

    hosts = stations.get("_hosts") if isinstance(stations.get("_hosts"), dict) else {}
    for key, host in hosts.items():
        for variant in (key, str(host), str(host).split(".")[0]):
            add_alias(variant, key)
    for key, value in stations.items():
        if key.startswith("_") or not isinstance(value, dict):
            continue
        variants = {
            key,
            key.lower(),
            str(value.get("label") or ""),
            str(value.get("label") or "").split("·")[0].strip(),
            str(value.get("host") or ""),
        }
        for variant in variants:
            add_alias(variant, key)
            add_alias(variant.split(".")[0], key)
    return aliases


def _canonical_machine(machine: str, aliases: Dict[str, str]) -> str:
    if not machine:
        return "unknown"
    return aliases.get(machine) or aliases.get(machine.lower()) or machine


def _by_machine(items: List[Dict], aliases: Dict[str, str]) -> Dict[str, List[Dict]]:
    grouped: Dict[str, List[Dict]] = {}
    for item in items:
        machine = _canonical_machine(str(item.get("machine") or item.get("sector") or ""), aliases)
        grouped.setdefault(machine, []).append(item)
    return grouped


def _summarize_services(telemetry: List[Dict]) -> Dict[str, Dict]:
    summary: Dict[str, Dict] = {}
    for item in telemetry:
        machine = str(item.get("machine") or "unknown")
        entry = summary.setdefault(machine, {"host": None, "services": [], "counts": {}})
        kind = item.get("kind")
        state = item.get("state") or "unknown"
        age = _age_seconds(str(item.get("ts") or ""))
        if kind == "host":
            entry["host"] = {
                "state": state,
                "ts": item.get("ts", ""),
                "age_seconds": age,
                "metrics": _detail(str(item.get("detail") or "")),
            }
        elif kind == "service":
            counts = entry["counts"]
            counts[state] = counts.get(state, 0) + 1
            entry["services"].append({
                "key": item.get("key", ""),
                "state": state,
                "ts": item.get("ts", ""),
                "age_seconds": age,
                "detail": _detail(str(item.get("detail") or "")),
            })
    for entry in summary.values():
        entry["services"] = sorted(entry["services"], key=lambda s: str(s.get("key", "")))
    return summary


def mesh_map(arguments: Dict, config: Config) -> Dict:
    """Read the live Grid Kernel map: machines, agents, programs, services."""
    client = MeshClient(MeshConfig.from_env())
    if not client.configured:
        return {"error": "mesh not configured (set AEON_MESH_HUB and AEON_MESH_TOKEN)"}

    include_raw = bool(arguments.get("include_raw"))
    include_services = bool(arguments.get("include_services"))
    stale_after = int(arguments.get("stale_after_seconds") or 300)
    stations = client.stations()
    telemetry = client.telemetry()
    agents = client.agents()
    programs = client.kernel_programs()
    kernel = client.kernel_status()

    services = _summarize_services(telemetry)
    station_names = _station_names(stations)
    aliases = _machine_aliases(stations)
    services = {
        _canonical_machine(machine, aliases): entry
        for machine, entry in services.items()
    }
    agents_by_machine = _by_machine(agents, aliases)
    programs_by_machine = _by_machine(programs, aliases)
    machines = []
    machine_keys = sorted(set(station_names) | set(services) | set(agents_by_machine) | set(programs_by_machine))
    for machine in machine_keys:
        service_entry = services.get(machine, {"host": None, "services": [], "counts": {}})
        machine_agents = sorted(agents_by_machine.get(machine, []), key=lambda a: str(a.get("id", "")))
        machine_programs = sorted(programs_by_machine.get(machine, []), key=lambda p: str(p.get("id", "")))
        program_health: Dict[str, int] = {}
        for program in machine_programs:
            health = str(program.get("health") or "unknown")
            program_health[health] = program_health.get(health, 0) + 1
        stale = []
        host = service_entry.get("host")
        if host and host.get("age_seconds") is not None and host["age_seconds"] > stale_after:
            stale.append(f"host telemetry stale: {host['age_seconds']}s")
        for service in service_entry.get("services", []):
            age = service.get("age_seconds")
            if age is not None and age > stale_after:
                stale.append(f"{service.get('key')} stale: {age}s")
        down_services = [
            str(service.get("key", ""))
            for service in service_entry.get("services", [])
            if service.get("state") not in ("up", "ok")
        ]
        stale_services = [
            str(service.get("key", ""))
            for service in service_entry.get("services", [])
            if service.get("age_seconds") is not None and service["age_seconds"] > stale_after
        ]
        machines.append({
            "machine": machine,
            "label": station_names.get(machine, machine),
            "host": host,
            "service_counts": service_entry.get("counts", {}),
            "down_services": down_services,
            "stale_services": stale_services,
            "agent_ids": [str(a.get("id", "")) for a in machine_agents if a.get("id")],
            "agent_status_counts": {
                status: sum(1 for a in machine_agents if str(a.get("status") or "unknown") == status)
                for status in sorted({str(a.get("status") or "unknown") for a in machine_agents})
            },
            "program_ids": [str(p.get("id", "")) for p in machine_programs if p.get("id")],
            "program_health_counts": program_health,
            "stale": stale,
        })
        if include_services:
            machines[-1]["services"] = service_entry.get("services", [])

    summary_lines = [
        (
            f"Kernel: {kernel.get('programs', len(programs))} programs, "
            f"{kernel.get('offline_programs', 0)} offline, "
            f"{kernel.get('unreplayed_dead_letters', 0)} unreplayed dead letters, "
            f"{kernel.get('latest_event_sequence', kernel.get('events', 0))} latest event."
        ),
        f"Grid: {len(machines)} machines, {len(agents)} agents, {len(programs)} programs, {len(telemetry)} telemetry records.",
    ]
    for machine in machines:
        host = machine.get("host") or {}
        host_state = host.get("state", "no-host-telemetry")
        host_age = host.get("age_seconds")
        host_part = f"host {host_state}"
        if host_age is not None:
            host_part += f" age {host_age}s"
        counts = machine.get("service_counts") or {}
        service_part = ", ".join(f"{count} {state}" for state, count in sorted(counts.items())) or "no services"
        stale_count = len(machine.get("stale") or [])
        summary_lines.append(
            f"{machine['machine']} ({machine['label']}): {host_part}; "
            f"services {service_part}; agents {len(machine['agent_ids'])}; "
            f"programs {len(machine['program_ids'])}; stale flags {stale_count}."
        )

    result = {
        "hub": client.config.hub,
        "kernel": kernel,
        "summary_text": "\n".join(summary_lines),
        "machines": machines,
        "totals": {
            "machines": len(machines),
            "agents": len(agents),
            "programs": len(programs),
            "telemetry_items": len(telemetry),
        },
    }
    if include_raw:
        result["raw"] = {
            "stations": stations,
            "telemetry": telemetry,
            "agents": agents,
            "programs": programs,
        }
    return result


def mesh_post(arguments: Dict, config: Config) -> Dict:
    client = MeshClient(MeshConfig.from_env())
    if not client.configured:
        return {"error": "mesh not configured (set AEON_MESH_HUB and AEON_MESH_TOKEN)"}
    result = client.post_message(
        thread_id=arguments.get("thread_id"),
        recipient=arguments["recipient"],
        content=arguments["content"],
        kind=arguments.get("kind", "message"),
    )
    return {"posted": True, "message_id": result.get("id")}


DEFINITIONS = [
    ToolDefinition(
        name="mesh_map",
        description=(
            "Read the live Grid Kernel map: current machines, agents, programs, "
            "service telemetry, host metrics, kernel status, and stale data flags."
        ),
        parameters={
            "type": "object",
            "properties": {
                "include_raw": {
                    "type": "boolean",
                    "description": "Include raw stations/telemetry/agents/programs payloads.",
                },
                "include_services": {
                    "type": "boolean",
                    "description": "Include per-service telemetry rows; default false.",
                },
                "stale_after_seconds": {
                    "type": "integer",
                    "description": "Age threshold for stale telemetry flags; default 300.",
                },
            },
        },
        tags=["mesh", "grid", "services"],
        approval_required=False,
    ),
    ToolDefinition(
        name="mesh_post",
        description="Post a message to an Agent Mesh thread (reach another agent/machine).",
        parameters={
            "type": "object",
            "properties": {
                "recipient": {"type": "string", "description": "e.g. claude@x1"},
                "content": {"type": "string"},
                "thread_id": {"type": "string", "description": "Existing thread id (optional)"},
            },
            "required": ["recipient", "content"],
        },
        tags=["mesh"],
        # Outward-facing: posting to another machine is an exfiltration sink,
        # so it is approval-gated even though the mesh is tailnet-only.
        approval_required=True,
    ),
]

HANDLERS = {"mesh_map": mesh_map, "mesh_post": mesh_post}
