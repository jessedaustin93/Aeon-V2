"""Tests for the read-only qBittorrent downloads tool."""
from aeon.tools import qbittorrent as qb


def test_human_bytes():
    assert qb._human_bytes(0) == "0 B"
    assert qb._human_bytes(1536).endswith("KB")
    assert qb._human_bytes(1719531861).endswith("GB")
    assert qb._human_bytes("nope") == "?"


def test_human_eta():
    assert qb._human_eta(-1) == "—"
    assert qb._human_eta(qb._ETA_INFINITE) == "—"
    assert qb._human_eta(45) == "45s"
    assert qb._human_eta(720) == "12m"
    assert qb._human_eta(7200) == "2h"


def _patch(monkeypatch, torrents):
    monkeypatch.setattr(qb, "_fetch", lambda url, timeout=10.0: torrents)


def test_downloads_report_is_grounded(monkeypatch):
    torrents = [
        {"name": "Movie.A.2024", "state": "downloading", "progress": 0.45, "size": 1719531861,
         "dlspeed": 2300000, "upspeed": 0, "eta": 720, "category": "radarr"},
        {"name": "Show.B.S01", "state": "queuedDL", "progress": 0.0, "size": 500000000,
         "dlspeed": 0, "upspeed": 0, "eta": qb._ETA_INFINITE, "category": "sonarr"},
    ]
    _patch(monkeypatch, torrents)
    out = qb.qbittorrent_downloads({"filter": "all"}, config=None)
    report = out["report"]
    assert "Movie.A.2024" in report and "Show.B.S01" in report
    assert "2 torrents" in report
    assert "downloading 1" in report and "queuedDL 1" in report
    assert "radarr" in report and "sonarr" in report
    assert "ETA 12m" in report          # 720s -> 12m
    assert out["data"]["count"] == 2
    # invented data guard
    for invented in ("Ubuntu.iso", "seeding 99"):
        assert invented not in report


def test_downloads_unreachable_refuses_to_guess(monkeypatch):
    monkeypatch.setattr(qb, "_fetch", lambda url, timeout=10.0: {"error": "conn refused"})
    out = qb.qbittorrent_downloads({}, config=None)
    assert "won't guess" in out["report"]
    assert out["data"]["error"] == "conn refused"


def test_downloads_empty_says_real_state(monkeypatch):
    _patch(monkeypatch, [])
    out = qb.qbittorrent_downloads({}, config=None)
    assert "no torrents match" in out["report"]
    assert "not an error" in out["report"]
