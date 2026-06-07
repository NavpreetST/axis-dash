"""Tests for the eventlog module — frozen 8-field schema enforcement."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from aegis.observability.eventlog import (
    REQUIRED_FIELDS,
    SCHEMA_VERSION,
    VALID_EVENT_TYPES,
    VALID_SEVERITIES,
    VALID_SENSITIVITIES,
    VALID_SOURCES,
    append_event,
    make_event,
)


def test_make_event_has_all_8_fields():
    event = make_event(
        source="aegis",
        event_type="chat_turn",
        payload={"text": "hello"},
    )
    assert set(event.keys()) == REQUIRED_FIELDS
    assert len(event) == 8


def test_make_event_schema_version_is_1():
    event = make_event(source="aegis", event_type="chat_turn", payload={})
    assert event["schema_version"] == 1


def test_make_event_timestamp_is_iso():
    event = make_event(source="aegis", event_type="chat_turn", payload={})
    assert "T" in event["timestamp"]  # ISO format


def test_make_event_validates_source():
    with pytest.raises(ValueError, match="invalid source"):
        make_event(source="invalid_source", event_type="chat_turn", payload={})


def test_make_event_validates_event_type():
    with pytest.raises(ValueError, match="invalid event_type"):
        make_event(source="aegis", event_type="nonexistent_event", payload={})


def test_make_event_validates_severity():
    with pytest.raises(ValueError, match="invalid severity"):
        make_event(source="aegis", event_type="chat_turn", payload={}, severity="invalid")


def test_make_event_validates_sensitivity():
    with pytest.raises(ValueError, match="invalid sensitivity"):
        make_event(
            source="aegis",
            event_type="chat_turn",
            payload={},
            sensitivity="invalid",
        )


def test_make_event_default_severity_and_sensitivity():
    event = make_event(source="aegis", event_type="chat_turn", payload={})
    assert event["severity"] == "info"
    assert event["sensitivity"] == "internal"
    assert event["provenance"] == {}


def test_append_event_validates_schema():
    """Events with wrong fields must be rejected."""
    with pytest.raises(ValueError, match="schema violation"):
        append_event({"schema_version": 1, "extra_field": True})


def test_append_event_writes_jsonl(tmp_path: Path):
    """append_event writes a valid JSON line to today's JSONL file."""
    events_dir = tmp_path / "events"
    event = make_event(source="aegis", event_type="chat_turn", payload={"text": "hi"})

    with patch("aegis.observability.eventlog.EVENTS_DIR", events_dir):
        append_event(event)

    jsonl_file = list(events_dir.glob("*.jsonl"))
    assert len(jsonl_file) == 1

    lines = jsonl_file[0].read_text().strip().split("\n")
    assert len(lines) == 1

    parsed = json.loads(lines[0])
    assert set(parsed.keys()) == REQUIRED_FIELDS
    assert parsed["schema_version"] == 1
    assert parsed["source"] == "aegis"
    assert parsed["event_type"] == "chat_turn"
    assert parsed["payload"] == {"text": "hi"}


def test_all_valid_sources():
    for src in VALID_SOURCES:
        event = make_event(source=src, event_type="chat_turn", payload={})
        assert event["source"] == src


def test_all_valid_event_types():
    for et in VALID_EVENT_TYPES:
        event = make_event(source="aegis", event_type=et, payload={})
        assert event["event_type"] == et


def test_all_valid_severities():
    for sev in VALID_SEVERITIES:
        event = make_event(source="aegis", event_type="chat_turn", payload={}, severity=sev)
        assert event["severity"] == sev


def test_all_valid_sensitivities():
    for sens in VALID_SENSITIVITIES:
        event = make_event(source="aegis", event_type="chat_turn", payload={}, sensitivity=sens)
        assert event["sensitivity"] == sens
