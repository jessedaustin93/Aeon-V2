"""Tests for timestamp handling across Aeon-V1.

Spec:
- No datetime.utcnow() remains in source files.
- All JSON records store timezone-aware UTC timestamps (contains '+00:00').
- Local timezone conversion (America/New_York) works correctly.
- Reflection Markdown heading uses local time (has AM/PM, not 'HH:MM UTC').
- Reflection JSON generated_at is UTC-aware.
"""
import ast
import json
import re
from datetime import UTC, datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from aeon.core import Config, MemoryStore, ingest, reflect
from aeon.core.time_utils import (
    local_date_time_string,
    local_now_string,
    local_time_string,
    utc_now,
    utc_now_iso,
)


# ---------------------------------------------------------------------------
# Source-code audit
# ---------------------------------------------------------------------------

SRC_DIR = Path(__file__).parent.parent / "src" / "aeon" / "core"


def _python_files():
    return list(SRC_DIR.glob("*.py"))


def test_no_utcnow_in_source():
    """datetime.utcnow() must not appear anywhere in the source package."""
    violations = []
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "utcnow"
            ):
                violations.append(f"{path.name}:{node.lineno}")
    assert violations == [], f"utcnow() still used in: {violations}"


# ---------------------------------------------------------------------------
# time_utils unit tests
# ---------------------------------------------------------------------------

def test_utc_now_is_aware():
    dt = utc_now()
    assert dt.tzinfo is not None
    assert dt.utcoffset() == timedelta(0)


def test_utc_now_iso_has_offset():
    s = utc_now_iso()
    assert "+00:00" in s, f"Expected '+00:00' in '{s}'"


def test_local_time_string_format():
    """Output should be like '5:07 PM EDT' — no leading zero, AM/PM, tz abbr."""
    # Use a fixed UTC time: 2026-04-28 21:07:00+00:00 = 5:07 PM EDT
    fixed = datetime(2026, 4, 28, 21, 7, 0, tzinfo=UTC)
    result = local_time_string(fixed, "America/New_York")
    assert re.match(r"^\d{1,2}:\d{2} (AM|PM) [A-Z]{2,5}$", result), (
        f"Unexpected format: {result!r}"
    )
    assert "PM" in result
    assert "UTC" not in result  # must not be raw UTC string


def test_local_time_string_from_iso():
    fixed_iso = "2026-04-28T21:07:00+00:00"
    result = local_time_string(fixed_iso, "America/New_York")
    assert "PM" in result or "AM" in result
    assert "UTC" not in result


def test_local_date_time_string_format():
    fixed = datetime(2026, 4, 28, 21, 7, 0, tzinfo=UTC)
    result = local_date_time_string(fixed, "America/New_York")
    # Expect: '2026-04-28 5:07 PM EDT'
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{1,2}:\d{2} (AM|PM) [A-Z]{2,5}$", result), (
        f"Unexpected format: {result!r}"
    )
    assert result.startswith("2026-04-28")


def test_local_date_time_string_naive_assumed_utc():
    """Naive datetimes should be treated as UTC, not crash."""
    naive = datetime(2026, 4, 28, 21, 7, 0)
    result = local_date_time_string(naive, "America/New_York")
    assert "PM" in result or "AM" in result


def test_local_now_string_format():
    result = local_now_string("America/New_York")
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{1,2}:\d{2} (AM|PM) [A-Z]{2,5}$", result), (
        f"Unexpected format: {result!r}"
    )


# ---------------------------------------------------------------------------
# JSON record timestamp verification
# ---------------------------------------------------------------------------

def test_stored_json_timestamp_is_utc_aware(tmp_path):
    config = Config()
    config.memory_path = tmp_path / "memory"
    config.vault_path  = tmp_path / "vault"

    result = ingest(
        'I learned a critical key insight: "Recursive Memory" is an important concept.',
        config=config,
    )
    # ingest always stores a raw record regardless of importance score
    raw = result["raw"]
    created = raw.get("created", "")
    assert "+00:00" in created, (
        f"Stored raw 'created' timestamp is not UTC-aware: {created!r}"
    )
    # episodic should also be created (high-importance text)
    ep = result["episodic"]
    assert ep is not None, "Expected episodic record for high-importance text"
    ep_created = ep.get("created", "")
    assert "+00:00" in ep_created, (
        f"Episodic 'created' timestamp is not UTC-aware: {ep_created!r}"
    )


def test_stored_reflection_json_generated_at_is_utc(tmp_path):
    """Reflection's generated_at field must be UTC-aware (+00:00)."""
    config = Config()
    config.memory_path = tmp_path / "memory"
    config.vault_path  = tmp_path / "vault"
    config.allow_low_value_reflections = True
    config.min_reflection_sources = 1

    ingest(
        'I learned a critical key insight: "Recursive Memory" is an important concept.',
        config=config,
    )
    result = reflect(config=config)
    ref = result["reflection"]
    assert ref is not None, "Reflection was None"

    generated_at = ref.get("generated_at", "")
    assert "+00:00" in generated_at, (
        f"Reflection generated_at is not UTC-aware: {generated_at!r}"
    )


def test_all_json_timestamps_utc_aware(tmp_path):
    """Any 'created' or 'created_at' in stored JSON must have +00:00."""
    config = Config()
    config.memory_path = tmp_path / "memory"
    config.vault_path  = tmp_path / "vault"
    config.allow_low_value_reflections = True
    config.min_reflection_sources = 1

    ingest(
        'I learned a critical key insight: "Recursive Memory" is an important concept.',
        config=config,
    )
    reflect(config=config)

    bad = []
    for json_file in (tmp_path / "memory").rglob("*.json"):
        data = json.loads(json_file.read_text(encoding="utf-8"))
        for field in ("created", "created_at", "generated_at"):
            value = data.get(field, "")
            if value and "+00:00" not in value:
                bad.append(f"{json_file.name}: {field}={value!r}")
    assert bad == [], f"Non-UTC-aware timestamps found:\n" + "\n".join(bad)


# ---------------------------------------------------------------------------
# Reflection heading uses local time
# ---------------------------------------------------------------------------

def test_reflection_heading_uses_local_time_format(tmp_path):
    """Reflection Markdown heading must contain AM/PM and no 'UTC'."""
    config = Config()
    config.memory_path = tmp_path / "memory"
    config.vault_path  = tmp_path / "vault"
    config.allow_low_value_reflections = True
    config.min_reflection_sources = 1
    config.display_timezone = "America/New_York"

    ingest(
        'I learned a critical key insight: "Recursive Memory" is an important concept.',
        config=config,
    )
    result = reflect(config=config)
    ref = result["reflection"]
    assert ref is not None

    content = ref.get("content", "")
    heading_line = next(
        (line for line in content.splitlines() if line.startswith("## Recursive Reflection")),
        None,
    )
    assert heading_line is not None, "Could not find '## Recursive Reflection' heading"
    assert "UTC" not in heading_line, (
        f"Heading still shows raw UTC: {heading_line!r}"
    )
    assert re.search(r"(AM|PM)", heading_line), (
        f"Heading does not contain AM/PM: {heading_line!r}"
    )
