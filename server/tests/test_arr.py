"""Tests for the read-only *arr queue tool."""
from aeon.tools import arr


def test_unknown_app_is_rejected():
    out = arr.arr_queue({"app": "plex"}, config=None)
    assert "Unknown app" in out["report"]
    assert out["data"]["error"] == "unknown app"


def test_missing_api_key_refuses_to_guess(monkeypatch):
    monkeypatch.delenv("AEON_SONARR_API_KEY", raising=False)
    out = arr.arr_queue({"app": "sonarr"}, config=None)
    assert "no API key" in out["report"].lower() or "won't guess" in out["report"]
    assert out["data"]["error"] == "no api key"


def _patch(monkeypatch, payload):
    monkeypatch.setenv("AEON_SONARR_API_KEY", "test-key")
    monkeypatch.setattr(arr, "_fetch", lambda url, api_key, timeout=10.0: payload)


def test_queue_report_is_grounded(monkeypatch):
    payload = {
        "totalRecords": 2,
        "records": [
            {"title": "House.of.the.Dragon.S03E03.1080p", "status": "downloading",
             "size": 4_000_000_000, "sizeleft": 1_000_000_000, "timeleft": "00:12:30",
             "quality": {"quality": {"name": "WEBDL-1080p"}}},
            {"title": "Some.Show.S01E01", "status": "queued", "size": 2_000_000_000,
             "sizeleft": 2_000_000_000, "timeleft": "00:00:00",
             "quality": {"quality": {"name": "HDTV-720p"}}},
        ],
    }
    _patch(monkeypatch, payload)
    out = arr.arr_queue({"app": "sonarr"}, config=None)
    report = out["report"]
    assert "Sonarr queue — 2 items" in report
    assert "House.of.the.Dragon.S03E03.1080p" in report
    assert "downloading 1" in report and "queued 1" in report
    assert "75%" in report            # (4G-1G)/4G
    assert "WEBDL-1080p" in report
    assert "00:12:30" in report
    assert out["data"]["total"] == 2
    # fabrication guard
    assert "Ubuntu" not in report


def test_queue_unreachable_refuses_to_guess(monkeypatch):
    monkeypatch.setenv("AEON_RADARR_API_KEY", "test-key")
    monkeypatch.setattr(arr, "_fetch", lambda url, api_key, timeout=10.0: {"error": "HTTP 401"})
    out = arr.arr_queue({"app": "radarr"}, config=None)
    assert "won't guess" in out["report"]
    assert out["data"]["error"] == "HTTP 401"


def test_empty_queue_says_real_state(monkeypatch):
    _patch(monkeypatch, {"totalRecords": 0, "records": []})
    out = arr.arr_queue({"app": "sonarr"}, config=None)
    assert "queue is empty" in out["report"]
    assert "not an error" in out["report"]
