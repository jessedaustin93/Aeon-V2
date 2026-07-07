"""SnifferOps telemetry tool for RF/network awareness from the lab hub."""
import json
import os
import urllib.error
import urllib.request
from collections import Counter
from typing import Dict, Iterable, List

from aeon.core.config import Config
from aeon.core.tools import ToolDefinition

DEFAULT_BASE_URL = "http://100.121.48.64:8766"
MAX_LIMIT = 200


def _base_url(config: Config) -> str:
    value = os.environ.get("AEON_SNIFFEROPS_BASE_URL", DEFAULT_BASE_URL)
    return value.rstrip("/")


def _fetch_json(url: str, timeout: float = 10.0) -> Dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Aeon-V2 SnifferOps"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.URLError as exc:
        return {"error": str(exc)}
    except json.JSONDecodeError as exc:
        return {"error": f"invalid json from SnifferOps: {exc}"}


def _limit(value, default: int = 25) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0, min(parsed, MAX_LIMIT))


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _filter_signals(signals: Iterable[Dict], signal_type: str, min_strength) -> List[Dict]:
    filtered: List[Dict] = []
    wanted_type = signal_type.strip().lower()
    strength_floor = _as_float(min_strength)
    for signal in signals:
        if wanted_type and str(signal.get("type", "")).lower() != wanted_type:
            continue
        strength = _as_float(signal.get("signalStrength"))
        if strength_floor is not None and (strength is None or strength < strength_floor):
            continue
        filtered.append(signal)
    return filtered


def _sort_key(signal: Dict) -> float:
    strength = _as_float(signal.get("signalStrength"))
    if strength is None:
        return -9999.0
    return strength


def snifferops_telemetry(arguments: Dict, config: Config) -> Dict:
    """Return concise SnifferOps health and awareness telemetry."""
    mode = str(arguments.get("mode", "overview")).strip().lower()
    limit = _limit(arguments.get("limit", 25))
    signal_type = str(arguments.get("type", "") or "")
    min_strength = arguments.get("min_strength")
    base = _base_url(config)

    health = _fetch_json(f"{base}/snifferops/health")
    if mode == "health":
        return {"source": base, "health": health}
    if health.get("error"):
        return {"source": base, "health": health, "error": health["error"]}

    awareness = _fetch_json(f"{base}/snifferops/awareness")
    if awareness.get("error"):
        return {"source": base, "health": health, "awareness": awareness, "error": awareness["error"]}

    signals = awareness.get("signals", [])
    if not isinstance(signals, list):
        signals = []
    filtered = _filter_signals(signals, signal_type, min_strength)
    ordered = sorted(filtered, key=_sort_key, reverse=True)
    by_type = Counter(str(signal.get("type", "unknown")) for signal in signals)
    payload = {
        "source": base,
        "health": health,
        "totalSignals": awareness.get("totalSignals", len(signals)),
        "returnedSignals": min(limit, len(ordered)),
        "filteredSignals": len(filtered),
        "byType": dict(sorted(by_type.items())),
        "signals": ordered[:limit],
    }
    if mode == "signals":
        return payload
    payload["summary"] = {
        "strongest": ordered[0] if ordered else None,
        "filter": {"type": signal_type or None, "min_strength": min_strength},
    }
    return payload


DEFINITIONS = [
    ToolDefinition(
        name="snifferops_telemetry",
        description="Query the SnifferOps hub for health, RF/network signal counts, and recent telemetry.",
        parameters={
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "description": "overview, health, or signals. Defaults to overview.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max signals to return, capped at 200. Defaults to 25.",
                },
                "type": {
                    "type": "string",
                    "description": "Optional signal type filter such as RTL_SDR, WiFi, or Bluetooth.",
                },
                "min_strength": {
                    "type": "number",
                    "description": "Optional minimum signalStrength filter.",
                },
            },
        },
        tags=["snifferops", "telemetry", "sdr"],
        approval_required=False,
    )
]

HANDLERS = {"snifferops_telemetry": snifferops_telemetry}
