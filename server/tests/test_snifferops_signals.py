"""Tests for the read-only, time-windowed SnifferOps signal-history tool."""
from datetime import datetime, timedelta, timezone

from aeon.tools import snifferops as so


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def test_parse_window_seconds():
    assert so._parse_window_seconds("24h") == 24 * 3600
    assert so._parse_window_seconds("7d") == 7 * 86400
    assert so._parse_window_seconds("90m") == 5400
    assert so._parse_window_seconds("2") == 7200  # bare number = hours
    assert so._parse_window_seconds(None) == 24 * 3600
    assert so._parse_window_seconds("garbage") == 24 * 3600


def test_signal_seen_at_handles_iso_and_epoch():
    iso = so._signal_seen_at({"lastSeen": "2026-06-13T03:31:34Z"})
    assert iso is not None and iso.tzinfo is not None
    epoch_ms = so._signal_seen_at({"lastSeen": 1781320900660})
    assert epoch_ms is not None and epoch_ms.tzinfo is not None
    assert so._signal_seen_at({}) is None


def _patch(monkeypatch, signals, node="node-x"):
    monkeypatch.setattr(
        so, "_fetch_json", lambda url, timeout=10.0: {"nodeName": node, "signals": signals}
    )


def test_signals_filters_to_window_and_stays_grounded(monkeypatch):
    now = datetime.now(timezone.utc)
    signals = [
        {"type": "WIFI", "name": "ap-recent", "lastSeen": _iso(now - timedelta(minutes=10)),
         "isEncrypted": True, "threatLevel": "UNKNOWN", "signalStrength": -40},
        {"type": "RTL_SDR", "name": "beacon-recent", "lastSeen": _iso(now - timedelta(hours=2)),
         "threatLevel": "UNKNOWN", "signalStrength": -60},
        {"type": "WIFI", "name": "ap-old", "lastSeen": _iso(now - timedelta(days=30))},
    ]
    _patch(monkeypatch, signals)
    out = so.snifferops_signals({"window": "24h"}, config=None)
    report = out["report"]
    assert "ap-recent" in report and "beacon-recent" in report
    assert "ap-old" not in report  # outside window -> excluded, not hidden or invented
    assert "2 signals captured in window (of 3 tracked total)" in report
    assert out["data"]["capturedInWindow"] == 2


def test_signals_type_filter(monkeypatch):
    now = datetime.now(timezone.utc)
    _patch(monkeypatch, [
        {"type": "WIFI", "name": "wifi1", "lastSeen": _iso(now)},
        {"type": "RTL_SDR", "name": "rtl1", "lastSeen": _iso(now)},
    ])
    out = so.snifferops_signals({"window": "24h", "type": "RTL_SDR"}, config=None)
    assert "rtl1" in out["report"]
    assert "wifi1" not in out["report"]


def test_signals_unreachable_refuses_to_guess(monkeypatch):
    monkeypatch.setattr(so, "_fetch_json", lambda url, timeout=10.0: {"error": "conn refused"})
    out = so.snifferops_signals({}, config=None)
    assert "won't guess" in out["report"]
    assert out["data"]["error"] == "conn refused"


def test_signals_empty_window_says_so(monkeypatch):
    _patch(monkeypatch, [{"type": "WIFI", "lastSeen": "2020-01-01T00:00:00Z"}])
    out = so.snifferops_signals({"window": "1h"}, config=None)
    assert "nothing captured in this window" in out["report"]
    assert "not an error" in out["report"]
