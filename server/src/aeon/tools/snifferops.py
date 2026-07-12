"""Ethrox Detect telemetry tool for RF/network awareness from the lab hub.

The historical snifferops_* tool names are kept as compatibility aliases for
older Aeon prompts and skills.
"""
import json
import os
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

from aeon.core.config import Config
from aeon.core.tools import ToolDefinition

DEFAULT_BASE_URL = "http://100.121.48.64:8766"
MAX_LIMIT = 200


def _base_url(config: Config) -> str:
    value = (
        os.environ.get("AEON_ETHROX_DETECT_BASE_URL")
        or os.environ.get("AEON_SNIFFEROPS_BASE_URL")
        or DEFAULT_BASE_URL
    )
    return value.rstrip("/")


def _fetch_json(url: str, timeout: float = 10.0) -> Dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Ethrox AI Ethrox Detect"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.URLError as exc:
        return {"error": str(exc)}
    except json.JSONDecodeError as exc:
        return {"error": f"invalid json from Ethrox Detect: {exc}"}


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
    """Return concise Ethrox Detect health and awareness telemetry."""
    mode = str(arguments.get("mode", "overview")).strip().lower()
    limit = _limit(arguments.get("limit", 25))
    signal_type = str(arguments.get("type", "") or "")
    min_strength = arguments.get("min_strength")
    base = _base_url(config)

    health = _fetch_json(f"{base}/ethrox-detect/health")
    if mode == "health":
        return {"source": base, "health": health}
    if health.get("error"):
        return {"source": base, "health": health, "error": health["error"]}

    awareness = _fetch_json(f"{base}/ethrox-detect/awareness")
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


def _parse_window_seconds(value) -> int:
    """'24h' / '7d' / '90m' / '45s' / bare number (hours) -> seconds. Default 24h."""
    if value is None:
        return 24 * 3600
    text = str(value).strip().lower()
    if not text:
        return 24 * 3600
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if text[-1] in units:
        try:
            return max(60, int(float(text[:-1]) * units[text[-1]]))
        except ValueError:
            return 24 * 3600
    try:  # bare number = hours
        return max(60, int(float(text) * 3600))
    except ValueError:
        return 24 * 3600


def _signal_seen_at(signal: Dict) -> Optional[datetime]:
    """Parse a signal's lastSeen (ISO string or epoch ms/s) to aware UTC datetime."""
    value = signal.get("lastSeen") or signal.get("firstSeen")
    if value is None:
        return None
    if isinstance(value, (int, float)):
        secs = value / 1000.0 if value > 1e12 else float(value)
        try:
            return datetime.fromtimestamp(secs, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _fmt_age(seconds: int) -> str:
    if seconds < 90:
        return f"{seconds}s ago"
    if seconds < 5400:
        return f"{seconds // 60}m ago"
    if seconds < 172800:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def snifferops_signals(arguments: Dict, config: Config) -> Dict:
    """Read-only: signals Ethrox Detect has captured within a time window.

    Returns a deterministic `report` (direct-output) plus structured `data`, so
    the model relays real captures instead of inventing them.
    """
    base = _base_url(config)
    window_s = _parse_window_seconds(arguments.get("window"))
    wanted_type = str(arguments.get("type", "") or "").strip().upper()
    limit = _limit(arguments.get("limit", 25))

    awareness = _fetch_json(f"{base}/ethrox-detect/awareness")
    if awareness.get("error"):
        return {
            "report": (
                f"Ethrox Detect is unreachable ({awareness['error']}). "
                "I can't see its captures right now, so I won't guess."
            ),
            "data": {"source": base, "error": awareness["error"]},
        }

    now = datetime.now(timezone.utc)
    all_signals = awareness.get("signals", [])
    if not isinstance(all_signals, list):
        all_signals = []

    in_window: List[Dict] = []
    for sig in all_signals:
        if wanted_type and str(sig.get("type", "")).upper() != wanted_type:
            continue
        seen = _signal_seen_at(sig)
        if seen is None:
            continue
        age = int((now - seen).total_seconds())
        if 0 <= age <= window_s:
            in_window.append({"signal": sig, "age": age})

    in_window.sort(key=lambda x: x["age"])  # most recent first
    by_type = Counter(str(x["signal"].get("type", "unknown")) for x in in_window)
    encrypted = sum(1 for x in in_window if x["signal"].get("isEncrypted"))
    threats = Counter(str(x["signal"].get("threatLevel", "UNKNOWN")) for x in in_window)

    win_label = arguments.get("window") or "24h"
    node = awareness.get("nodeName", "ethrox-detect")
    type_part = f" ({wanted_type})" if wanted_type else ""
    lines = [
        f"# Ethrox Detect captures - last {win_label}{type_part} · node: {node}",
        "",
        f"- {len(in_window)} signals captured in window (of {len(all_signals)} tracked total)",
    ]
    if in_window:
        lines.append("- by type: " + ", ".join(f"{t} {n}" for t, n in sorted(by_type.items())))
        lines.append(
            f"- encrypted: {encrypted} · threat levels: "
            + ", ".join(f"{k} {v}" for k, v in sorted(threats.items()))
        )
        lines.append("")
        lines.append("## Most recent")
        for x in in_window[:limit]:
            s = x["signal"]
            name = str(s.get("name") or s.get("id") or "unnamed").strip()
            strength = s.get("signalStrength")
            enc = " · encrypted" if s.get("isEncrypted") else ""
            freq = s.get("frequencyHz")
            freq_part = f" · {float(freq) / 1e6:.1f} MHz" if freq else ""
            lines.append(
                f"- [{s.get('type', '?')}] {name[:70]} · strength {strength}"
                f"{freq_part}{enc} · seen {_fmt_age(x['age'])}"
            )
    else:
        lines.append(
            "- nothing captured in this window. Widen `window` (e.g. '7d') if you "
            "expected activity — this is the real state, not an error."
        )

    report = "\n".join(lines).rstrip() + "\n"
    return {
        "report": report,
        "data": {
            "source": base,
            "window_seconds": window_s,
            "capturedInWindow": len(in_window),
            "totalTracked": len(all_signals),
            "byType": dict(sorted(by_type.items())),
            "signals": [x["signal"] for x in in_window[:limit]],
        },
    }


DEFINITIONS = [
    ToolDefinition(
        name="snifferops_telemetry",
        description="Compatibility alias: query the Ethrox Detect hub for health, RF/network signal counts, and recent telemetry.",
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
        tags=["ethrox-detect", "snifferops", "telemetry", "sdr"],
        approval_required=False,
    ),
    ToolDefinition(
        name="snifferops_signals",
        description=(
            "Compatibility alias: read-only RF/network signals Ethrox Detect captured within a time window "
            "(e.g. 'what signals did we pick up in the last 24h/7d'). Optional type "
            "filter (WIFI, BLE, BLUETOOTH, CELLULAR, RTL_SDR). No approval needed. "
            "Presents a factual capture report as-is."
        ),
        parameters={
            "type": "object",
            "properties": {
                "window": {
                    "type": "string",
                    "description": "Time window: '24h', '7d', '90m', '45s', or a number of hours. Default 24h.",
                },
                "type": {
                    "type": "string",
                    "description": "Optional signal type filter: WIFI, BLE, BLUETOOTH, CELLULAR, RTL_SDR.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max recent signals to list, capped at 200. Default 25.",
                },
            },
        },
        tags=["ethrox-detect", "snifferops", "signals", "sdr", "rf"],
        approval_required=False,
        direct=True,
    ),
    ToolDefinition(
        name="ethrox_detect_telemetry",
        description="Query the Ethrox Detect hub for health, RF/network signal counts, and recent telemetry.",
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
        tags=["ethrox-detect", "telemetry", "sdr"],
        approval_required=False,
    ),
    ToolDefinition(
        name="ethrox_detect_signals",
        description=(
            "Read-only: RF/network signals Ethrox Detect captured within a time window "
            "(e.g. 'what signals did we pick up in the last 24h/7d'). Optional type "
            "filter (WIFI, BLE, BLUETOOTH, CELLULAR, RTL_SDR). No approval needed. "
            "Presents a factual capture report as-is."
        ),
        parameters={
            "type": "object",
            "properties": {
                "window": {
                    "type": "string",
                    "description": "Time window: '24h', '7d', '90m', '45s', or a number of hours. Default 24h.",
                },
                "type": {
                    "type": "string",
                    "description": "Optional signal type filter: WIFI, BLE, BLUETOOTH, CELLULAR, RTL_SDR.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max recent signals to list, capped at 200. Default 25.",
                },
            },
        },
        tags=["ethrox-detect", "signals", "sdr", "rf"],
        approval_required=False,
        direct=True,
    ),
]

HANDLERS = {
    "snifferops_telemetry": snifferops_telemetry,
    "snifferops_signals": snifferops_signals,
    "ethrox_detect_telemetry": snifferops_telemetry,
    "ethrox_detect_signals": snifferops_signals,
}
