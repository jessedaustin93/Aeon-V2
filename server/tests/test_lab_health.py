"""Tests for the deterministic lab_health world-view tool."""
from aeon.tools import lab_health as lh


def test_host_of_parses_ids():
    assert lh._host_of("aeon@t5810") == "t5810"
    assert lh._host_of("claude@hp") == "hp"
    assert lh._host_of("host:t3610") == "t3610"
    assert lh._host_of("no-host") == ""


def _fixture():
    return {
        "hub": "http://127.0.0.1:8787",
        "totals": {"machines": 3, "agents": 4, "programs": 2},
        "hosts": {
            "t5810": {
                "agents": [{"id": "aeon@t5810"}, {"id": "codex@t5810"}],
                "programs": ["aeon@t5810", "telemetry@t5810"],
                "services": [{"name": "mesh-hub", "state": "up"}],
                "online": True,
                "freshest_age": 4,
            },
            "t3610": {
                "agents": [{"id": "music@t3610"}],
                "programs": [],
                "services": [{"name": "jellyfin", "state": "up"}, {"name": "sonarr", "state": "up"}],
                "online": True,
                "freshest_age": 10,
            },
            "x1": {
                "agents": [{"id": "claude@x1"}],
                "programs": [],
                "services": [{"name": "aeon", "state": "down"}, {"name": "ssh", "state": "up"}],
                "online": False,
                "freshest_age": 2_300_000,
            },
        },
    }


def test_render_contains_only_real_hosts():
    """The report must never contain a machine or service not in the source data."""
    report = lh._render(_fixture())
    headers = {line[3:].split(" — ")[0] for line in report.splitlines() if line.startswith("## ")}
    assert headers == {"t5810", "t3610", "x1"}
    for real in ("jellyfin", "sonarr", "mesh-hub", "aeon"):
        assert real in report
    for invented in ("titanium", "roam", "ROG Ally", "web-scraper-cron"):
        assert invented not in report


def test_render_marks_online_and_offline():
    report = lh._render(_fixture())
    assert "t5810 — ✅ online" in report
    assert "x1 — ⛔ offline" in report
    assert "d ago" in report  # x1's stale age rendered, not guessed


def test_render_flags_down_service_state():
    report = lh._render(_fixture())
    # x1's aeon service is down and must be shown as such, not hidden or invented.
    assert "aeon (down)" in report
    assert "1 down" in report
    assert "jellyfin, sonarr — all up" in report


def test_render_hub_error_refuses_to_guess():
    report = lh._render({"error": "grid hub unreachable: TimeoutError"})
    assert "unavailable" in report.lower()
    assert "won't guess" in report.lower()


def test_lab_health_returns_report_and_data(monkeypatch):
    monkeypatch.setattr(lh, "_collect", lambda config: _fixture())
    out = lh.lab_health({}, config=None)
    assert set(out) == {"report", "data"}
    assert out["report"].startswith("# Lab health — 2/3 machines online")
