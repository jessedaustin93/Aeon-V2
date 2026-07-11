"""Read-only qBittorrent tool: list downloads/queue from the WebUI API.

Read-only and non-gated (it only calls torrents/info). Returns a deterministic,
direct-output report so the model relays real torrents instead of inventing them
or shelling out (approval spam). Changing torrents (pause/resume/delete) is NOT
here — mutations must go through an approval-gated tool.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from typing import Dict, List

from aeon.core.config import Config
from aeon.core.tools import ToolDefinition

DEFAULT_BASE_URL = "http://t3610:8080"
MAX_LIMIT = 100

# qBittorrent's "unknown/infinite" ETA sentinel (~100 days in seconds).
_ETA_INFINITE = 8640000


def _base_url(config: Config) -> str:
    return os.environ.get("AEON_QBITTORRENT_URL", DEFAULT_BASE_URL).rstrip("/")


def _fetch(url: str, timeout: float = 10.0):
    req = urllib.request.Request(url, headers={"User-Agent": "Aeon-V2 qbittorrent"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.URLError as exc:
        return {"error": str(exc.reason if hasattr(exc, "reason") else exc)}
    except json.JSONDecodeError as exc:
        return {"error": f"invalid json from qBittorrent: {exc}"}


def _human_bytes(value) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _human_eta(seconds) -> str:
    try:
        secs = int(seconds)
    except (TypeError, ValueError):
        return "—"
    if secs < 0 or secs >= _ETA_INFINITE:
        return "—"
    if secs < 90:
        return f"{secs}s"
    if secs < 5400:
        return f"{secs // 60}m"
    if secs < 172800:
        return f"{secs // 3600}h"
    return f"{secs // 86400}d"


def _limit(value, default: int = 20) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, MAX_LIMIT))


def qbittorrent_downloads(arguments: Dict, config: Config) -> Dict:
    """Read-only: list torrents from qBittorrent, optionally filtered by state/category."""
    base = _base_url(config)
    state_filter = str(arguments.get("filter", "all") or "all").strip().lower()
    category = str(arguments.get("category", "") or "").strip()
    limit = _limit(arguments.get("limit", 20))

    query = {"filter": state_filter, "sort": "added_on", "reverse": "true"}
    if category:
        query["category"] = category
    url = f"{base}/api/v2/torrents/info?" + urllib.parse.urlencode(query)
    result = _fetch(url)

    if isinstance(result, dict) and result.get("error"):
        return {
            "report": (
                f"qBittorrent is unreachable ({result['error']}). "
                "I can't see the download list right now, so I won't guess."
            ),
            "data": {"source": base, "error": result["error"]},
        }
    torrents: List[Dict] = result if isinstance(result, list) else []

    states = Counter(str(t.get("state", "unknown")) for t in torrents)
    total_dl = sum(int(t.get("dlspeed", 0) or 0) for t in torrents)
    total_up = sum(int(t.get("upspeed", 0) or 0) for t in torrents)

    filt_part = "" if state_filter == "all" else f" · filter: {state_filter}"
    cat_part = f" · category: {category}" if category else ""
    lines = [
        f"# qBittorrent — {len(torrents)} torrents{filt_part}{cat_part}",
        "",
    ]
    if torrents:
        lines.append("- states: " + ", ".join(f"{s} {n}" for s, n in sorted(states.items())))
        lines.append(f"- ↓ {_human_bytes(total_dl)}/s · ↑ {_human_bytes(total_up)}/s")
        lines.append("")
        lines.append("## Torrents")
        for t in torrents[:limit]:
            name = str(t.get("name", "unnamed")).strip()
            pct = f"{float(t.get('progress', 0)) * 100:.0f}%"
            state = t.get("state", "?")
            size = _human_bytes(t.get("size"))
            dl = int(t.get("dlspeed", 0) or 0)
            speed_part = f" · ↓ {_human_bytes(dl)}/s" if dl > 0 else ""
            eta = _human_eta(t.get("eta"))
            eta_part = f" · ETA {eta}" if eta != "—" else ""
            cat = str(t.get("category", "") or "")
            cat_tag = f" · {cat}" if cat else ""
            lines.append(
                f"- [{state} {pct}] {name[:80]} · {size}{speed_part}{eta_part}{cat_tag}"
            )
    else:
        lines.append("- no torrents match. This is the real state, not an error.")

    return {
        "report": "\n".join(lines).rstrip() + "\n",
        "data": {
            "source": base,
            "count": len(torrents),
            "states": dict(sorted(states.items())),
            "total_dlspeed": total_dl,
            "total_upspeed": total_up,
            "torrents": [
                {k: t.get(k) for k in ("name", "state", "progress", "size", "dlspeed",
                                       "eta", "category", "num_seeds", "num_leechs")}
                for t in torrents[:limit]
            ],
        },
    }


DEFINITIONS = [
    ToolDefinition(
        name="qbittorrent_downloads",
        description=(
            "Read-only: current qBittorrent torrents/downloads (name, state, progress, "
            "speed, ETA, category). Optional filter (all, downloading, completed, paused, "
            "active, stalled, seeding, errored) and category (e.g. radarr, sonarr). No "
            "approval needed. Presents a factual download report as-is. Does NOT change "
            "torrents — pausing/removing requires a separate approval-gated tool."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": "State filter: all, downloading, completed, paused, active, stalled, seeding, errored. Default all.",
                },
                "category": {
                    "type": "string",
                    "description": "Optional category filter, e.g. radarr or sonarr.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max torrents to list, capped at 100. Default 20.",
                },
            },
        },
        tags=["qbittorrent", "downloads", "torrents"],
        approval_required=False,
        direct=True,
    )
]

HANDLERS = {"qbittorrent_downloads": qbittorrent_downloads}
