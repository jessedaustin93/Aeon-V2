"""Deterministic, grounded lab world-view.

The local model tends to invent machine/program names when it composes a status
summary from raw JSON. `lab_health` instead builds the finished, human-readable
report in code from the Grid Kernel's own live data — the same agents, programs,
and self-hosted service telemetry that power the kernel's world view — so the
model has only real names to relay, nothing to fabricate.

Read-only (queries the local hub only), so it is NOT approval-gated.
"""
from datetime import datetime, timezone
from typing import Dict, Optional

from aeon.core.config import Config
from aeon.core.tools import ToolDefinition
from aeon.mesh import MeshClient, MeshConfig

ONLINE_WINDOW_SECONDS = 120


def _host_of(entity_id: str) -> str:
    """`aeon@t5810` -> `t5810`; `host:t5810` -> `t5810`; else ''."""
    if "@" in entity_id:
        return entity_id.rsplit("@", 1)[-1].strip().lower()
    if entity_id.startswith("host:"):
        return entity_id.split(":", 1)[1].strip().lower()
    return ""


def _age_seconds(value: str) -> Optional[int]:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - ts).total_seconds()))


def _fmt_age(seconds: Optional[int]) -> str:
    if seconds is None:
        return "unknown"
    if seconds < 90:
        return f"{seconds}s ago"
    if seconds < 5400:
        return f"{seconds // 60}m ago"
    if seconds < 172800:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _collect(config: Config) -> Dict:
    """Gather the live grid world view grouped by real short host name."""
    client = MeshClient(MeshConfig.from_env())
    if not client.configured:
        return {"error": "grid hub not configured (AEON_MESH_HUB / AEON_MESH_TOKEN)"}
    try:
        agents = client.agents()
        programs = client.kernel_programs()
        telemetry = client.telemetry()
    except Exception as exc:  # noqa: BLE001 — the hub being down must not crash the tool
        return {"error": f"grid hub unreachable: {type(exc).__name__}: {exc}"}

    hosts: Dict[str, Dict] = {}

    def host_entry(name: str) -> Dict:
        return hosts.setdefault(
            name,
            {"agents": [], "programs": [], "services": [], "host_age": None, "min_agent_age": None},
        )

    for a in agents:
        h = _host_of(str(a.get("id", "")))
        if not h:
            continue
        entry = host_entry(h)
        entry["agents"].append(a)
        age = _age_seconds(str(a.get("last_seen", "")))
        if age is not None and (entry["min_agent_age"] is None or age < entry["min_agent_age"]):
            entry["min_agent_age"] = age

    for p in programs:
        h = _host_of(str(p.get("id", "")))
        if h:
            host_entry(h)["programs"].append(str(p.get("id", "")))

    for t in telemetry:
        machine = str(t.get("machine") or "").strip().lower()
        if not machine:
            continue
        entry = host_entry(machine)
        if t.get("kind") == "host":
            entry["host_age"] = _age_seconds(str(t.get("ts", "")))
        elif t.get("kind") == "service":
            key = str(t.get("key", ""))
            name = key.split(".", 1)[1] if "." in key else key
            entry["services"].append({"name": name, "state": str(t.get("state") or "unknown")})

    for entry in hosts.values():
        entry["services"].sort(key=lambda s: s["name"])
        ages = [a for a in (entry["min_agent_age"], entry["host_age"]) if a is not None]
        freshest = min(ages) if ages else None
        entry["online"] = freshest is not None and freshest <= ONLINE_WINDOW_SECONDS
        entry["freshest_age"] = freshest

    return {
        "hub": client.config.hub,
        "hosts": hosts,
        "totals": {"machines": len(hosts), "agents": len(agents), "programs": len(programs)},
    }


def _render(collected: Dict) -> str:
    if collected.get("error"):
        return (
            f"Grid world-view unavailable: {collected['error']}. "
            "I can't see the mesh right now, so I won't guess at its state."
        )
    hosts = collected["hosts"]
    totals = collected["totals"]
    online_count = sum(1 for h in hosts.values() if h["online"])
    lines = [
        f"# Lab health — {online_count}/{totals['machines']} machines online, "
        f"{totals['agents']} agents, {totals['programs']} programs",
        "",
    ]
    for name in sorted(hosts):
        h = hosts[name]
        status = "✅ online" if h["online"] else f"⛔ offline (last seen {_fmt_age(h['freshest_age'])})"
        agent_names = sorted({str(a.get("id", "")).split("@", 1)[0] for a in h["agents"] if a.get("id")})
        lines.append(f"## {name} — {status}")
        lines.append(
            f"- agents: {', '.join(agent_names) if agent_names else 'none'}"
            f" · programs: {len(h['programs'])}"
        )
        services = h["services"]
        if services:
            parts = [
                s["name"] if s["state"] in ("up", "ok") else f"{s['name']} ({s['state']})"
                for s in services
            ]
            down = sum(1 for s in services if s["state"] not in ("up", "ok"))
            suffix = " — all up" if down == 0 else f" — {down} down"
            lines.append(f"- hosting ({len(services)}): {', '.join(parts)}{suffix}")
        else:
            lines.append("- hosting: none reported by the grid kernel")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def lab_health(arguments: Dict, config: Config) -> Dict:
    """Deterministic, grounded report of machines, agents, programs, and hosted services."""
    collected = _collect(config)
    return {"report": _render(collected), "data": collected}


DEFINITIONS = [
    ToolDefinition(
        name="lab_health",
        description=(
            "Grounded live world-view of the lab from the Grid Kernel: real machines, "
            "which are online, their agents/programs, and the self-hosted services "
            "each machine runs (with up/down state) — the same data the kernel's world "
            "view uses. Returns a ready-to-present 'report'. Use this for any 'what "
            "machines/agents/programs/services are running / is X online / lab health' "
            "question, and present the report as-is."
        ),
        parameters={"type": "object", "properties": {}},
        tags=["mesh", "grid", "health"],
        approval_required=False,
        direct=True,
    )
]

HANDLERS = {"lab_health": lab_health}
