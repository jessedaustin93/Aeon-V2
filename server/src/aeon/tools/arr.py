"""Read-only *arr queue tool (Sonarr / Radarr / Lidarr) via the Servarr v3 API.

Read-only and non-gated: it only reads the download queue. Returns a deterministic,
direct-output report so the model relays real queue items instead of inventing them
or shelling out. Changing anything (search, delete, blocklist) must go through a
separate approval-gated tool.

Config per app via env: AEON_SONARR_URL / AEON_SONARR_API_KEY (and RADARR / LIDARR).
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

APPS = {
    # Sonarr/Radarr are on Servarr API v3; Lidarr is still on v1.
    "sonarr": {"port": 8989, "label": "Sonarr", "api": "v3"},
    "radarr": {"port": 7878, "label": "Radarr", "api": "v3"},
    "lidarr": {"port": 8686, "label": "Lidarr", "api": "v1"},
}
MAX_LIMIT = 100


def _config_for(app: str):
    up = app.upper()
    url = os.environ.get(f"AEON_{up}_URL", f"http://t3610:{APPS[app]['port']}").rstrip("/")
    key = os.environ.get(f"AEON_{up}_API_KEY", "").strip()
    return url, key


def _fetch(url: str, api_key: str, timeout: float = 10.0):
    req = urllib.request.Request(
        url, headers={"X-Api-Key": api_key, "User-Agent": "Aeon-V2 arr"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        return {"error": f"HTTP {exc.code}"}
    except urllib.error.URLError as exc:
        return {"error": str(exc.reason if hasattr(exc, "reason") else exc)}
    except json.JSONDecodeError as exc:
        return {"error": f"invalid json: {exc}"}


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


def _limit(value, default: int = 20) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, MAX_LIMIT))


def arr_queue(arguments: Dict, config: Config) -> Dict:
    """Read-only: the Sonarr/Radarr/Lidarr download queue."""
    app = str(arguments.get("app", "") or "").strip().lower()
    if app not in APPS:
        return {
            "report": f"Unknown app '{app}'. Choose one of: sonarr, radarr, lidarr.",
            "data": {"error": "unknown app"},
        }
    limit = _limit(arguments.get("limit", 20))
    url, api_key = _config_for(app)
    if not api_key:
        return {
            "report": (
                f"{APPS[app]['label']} has no API key configured "
                f"(set AEON_{app.upper()}_API_KEY). I can't query it, so I won't guess."
            ),
            "data": {"source": url, "error": "no api key"},
        }

    endpoint = f"{url}/api/{APPS[app]['api']}/queue?" + urllib.parse.urlencode(
        {"page": 1, "pageSize": limit, "sortKey": "timeleft", "sortDirection": "ascending"}
    )
    result = _fetch(endpoint, api_key)
    if isinstance(result, dict) and result.get("error"):
        return {
            "report": (
                f"{APPS[app]['label']} is unreachable ({result['error']}). "
                "I can't see its queue right now, so I won't guess."
            ),
            "data": {"source": url, "error": result["error"]},
        }

    records: List[Dict] = result.get("records", []) if isinstance(result, dict) else []
    total = result.get("totalRecords", len(records)) if isinstance(result, dict) else len(records)
    statuses = Counter(str(r.get("status", "unknown")) for r in records)

    lines = [f"# {APPS[app]['label']} queue — {total} items", ""]
    if records:
        lines.append("- statuses: " + ", ".join(f"{s} {n}" for s, n in sorted(statuses.items())))
        lines.append("")
        lines.append("## Queue")
        for r in records[:limit]:
            title = str(r.get("title", "unknown")).strip()
            size = float(r.get("size", 0) or 0)
            left = float(r.get("sizeleft", 0) or 0)
            pct = f"{(size - left) / size * 100:.0f}%" if size > 0 else "0%"
            status = r.get("status", "?")
            quality = (r.get("quality", {}) or {}).get("quality", {}).get("name", "")
            q_part = f" · {quality}" if quality else ""
            timeleft = str(r.get("timeleft", "") or "").strip()
            t_part = f" · {timeleft}" if timeleft and timeleft != "00:00:00" else ""
            lines.append(
                f"- [{status} {pct}] {title[:80]} · {_human_bytes(size)}{q_part}{t_part}"
            )
    else:
        lines.append("- queue is empty. This is the real state, not an error.")

    return {
        "report": "\n".join(lines).rstrip() + "\n",
        "data": {
            "source": url,
            "app": app,
            "total": total,
            "statuses": dict(sorted(statuses.items())),
            "records": [
                {k: r.get(k) for k in ("title", "status", "size", "sizeleft", "timeleft", "quality")}
                for r in records[:limit]
            ],
        },
    }


DEFINITIONS = [
    ToolDefinition(
        name="arr_queue",
        description=(
            "Read-only: the download queue of a media manager — Sonarr (TV), Radarr "
            "(movies), or Lidarr (music). Shows what each is grabbing/importing (title, "
            "status, progress, quality, time left). Requires the `app` argument. No "
            "approval needed. Presents a factual queue report as-is. Does NOT trigger "
            "searches or delete items — those need an approval-gated tool."
        ),
        parameters={
            "type": "object",
            "properties": {
                "app": {
                    "type": "string",
                    "description": "Which manager: sonarr, radarr, or lidarr.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max queue items to list, capped at 100. Default 20.",
                },
            },
            "required": ["app"],
        },
        tags=["arr", "sonarr", "radarr", "lidarr", "media"],
        approval_required=False,
        direct=True,
    )
]

HANDLERS = {"arr_queue": arr_queue}
