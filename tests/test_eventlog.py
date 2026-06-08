"""Tests for the eventlog module — frozen 8-field schema enforcement."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from aegis.observability.eventlog import (
    _CONTRACTS_PATH,
    REQUIRED_FIELDS,
    SCHEMA_VERSION,
    VALID_EVENT_TYPES,
    VALID_SENSITIVITIES,
    VALID_SEVERITIES,
    VALID_SOURCES,
    _append_event_sync,
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
        _append_event_sync({"schema_version": 1, "extra_field": True})


def test_append_event_writes_jsonl(tmp_path: Path):
    """append_event writes a valid JSON line to today's JSONL file."""
    events_dir = tmp_path / "events"
    event = make_event(source="aegis", event_type="chat_turn", payload={"text": "hi"})

    with patch("aegis.observability.eventlog.EVENTS_DIR", events_dir):
        _append_event_sync(event)

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


def test_append_event_fsyncs(tmp_path: Path):
    """append_event must fsync after write for crash safety."""
    events_dir = tmp_path / "events"
    event = make_event(source="aegis", event_type="chat_turn", payload={})

    with patch("aegis.observability.eventlog.EVENTS_DIR", events_dir):
        with patch("aegis.observability.eventlog.os.fsync") as mock_fsync:
            _append_event_sync(event)
            mock_fsync.assert_called_once()


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


def test_valid_sources_derived_from_schema():
    """VALID_SOURCES must match the schema contract, not a hardcoded list."""
    schema = json.loads(_CONTRACTS_PATH.read_text(encoding="utf-8"))
    schema_sources = frozenset(schema["properties"]["source"]["enum"])
    assert schema_sources == VALID_SOURCES, (
        f"VALID_SOURCES ({VALID_SOURCES}) doesn't match schema ({schema_sources}). "
        "Update contracts/event.schema.json, not the code."
    )


def test_navpreets_removed_from_schema():
    """navpreets must NOT be in the frozen source enum."""
    schema = json.loads(_CONTRACTS_PATH.read_text(encoding="utf-8"))
    assert "navpreets" not in schema["properties"]["source"]["enum"]


# ---------------------------------------------------------------------------
# log_event() tests — publishes to eventlog.append, does NOT call append_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_event_publishes_to_eventlog_append():
    """log_event() must publish to the BUS 'eventlog.append' topic."""
    from aegis.observability.eventlog import log_event

    with patch("aegis.observability.eventlog.BUS") as mock_bus:
        mock_bus.publish = AsyncMock()
        await log_event(
            source="aegis",
            event_type="chat_turn",
            payload={"prompt": "hi", "reply": "hello"},
        )
        mock_bus.publish.assert_called_once()
        call_args = mock_bus.publish.call_args
        assert call_args[0][0] == "eventlog.append"
        event = call_args[0][1]
        assert event["event_type"] == "chat_turn"
        assert event["schema_version"] == 1


@pytest.mark.asyncio
async def test_log_event_does_not_call_append_event():
    """log_event() must NOT call _append_event_sync() directly — sole writer is run()."""
    from aegis.observability.eventlog import log_event

    with patch("aegis.observability.eventlog.BUS") as mock_bus:
        mock_bus.publish = AsyncMock()
        with patch("aegis.observability.eventlog._append_event_sync") as mock_append:
            await log_event(
                source="aegis",
                event_type="error",
                payload={"err": "test"},
                severity="error",
            )
            mock_append.assert_not_called()


# ---------------------------------------------------------------------------
# run() tests — sole writer, writes JSONL + publishes to eventlog.write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_writes_jsonl_from_eventlog_append(tmp_path: Path):
    """run() must pick up events from eventlog.append, write JSONL, and publish to eventlog.write."""
    from aegis.observability.eventlog import run

    events_dir = tmp_path / "events"
    event = make_event(source="aegis", event_type="chat_turn", payload={"prompt": "hi"})

    with patch("aegis.observability.eventlog.EVENTS_DIR", events_dir):
        with patch("aegis.observability.eventlog.BUS") as mock_bus:
            # Set up a queue that delivers one event then blocks forever
            import asyncio

            q: asyncio.Queue = asyncio.Queue()
            q.put_nowait(type("Msg", (), {"payload": event})())
            mock_bus.subscribe.return_value = q
            mock_bus.publish = AsyncMock()

            # Run run() for a short time
            task = asyncio.create_task(run())
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # Verify JSONL was written
    jsonl_files = list(events_dir.glob("*.jsonl"))
    assert len(jsonl_files) == 1
    line = jsonl_files[0].read_text().strip()
    parsed = json.loads(line)
    assert parsed["event_type"] == "chat_turn"
    assert parsed["schema_version"] == 1


@pytest.mark.asyncio
async def test_run_publishes_to_eventlog_write(tmp_path: Path):
    """run() must publish to eventlog.write after writing JSONL (for cloud consumers)."""
    from aegis.observability.eventlog import run

    events_dir = tmp_path / "events"
    event = make_event(source="aegis", event_type="error", payload={"err": "test"})

    with patch("aegis.observability.eventlog.EVENTS_DIR", events_dir):
        with patch("aegis.observability.eventlog.BUS") as mock_bus:
            import asyncio

            q: asyncio.Queue = asyncio.Queue()
            q.put_nowait(type("Msg", (), {"payload": event})())
            mock_bus.subscribe.return_value = q
            mock_bus.publish = AsyncMock()

            task = asyncio.create_task(run())
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            # Verify eventlog.write was published to (for supabase/b2)
            write_calls = [
                c for c in mock_bus.publish.call_args_list if c[0][0] == "eventlog.write"
            ]
            assert len(write_calls) == 1
            assert write_calls[0][0][1]["event_type"] == "error"


# ---------------------------------------------------------------------------
# Secret-payload redaction
# ---------------------------------------------------------------------------


def test_append_event_redacts_secret_in_error_log(caplog):
    """When sensitivity=secret and append fails, payload must be redacted in logs."""
    import logging

    from aegis.observability.eventlog import _log_append_error

    event = make_event(
        source="aegis",
        event_type="error",
        payload={"secret_key": "hunter2"},
        sensitivity="secret",
    )

    with caplog.at_level(logging.WARNING):
        _log_append_error(event, OSError("test failure"))
        matching = [r.message for r in caplog.records if "append failed" in r.message]
        assert matching, "Expected an append-failure warning log"
        for message in matching:
            assert "hunter2" not in message
            assert "<REDACTED>" in message


def test_secret_payload_redacted_in_jsonl(tmp_path: Path):
    """sensitivity=secret payloads must be redacted in JSONL — never persisted in plaintext."""
    events_dir = tmp_path / "events"
    event = make_event(
        source="aegis",
        event_type="error",
        payload={"api_key": "sk-live-supersecret"},
        sensitivity="secret",
    )

    with patch("aegis.observability.eventlog.EVENTS_DIR", events_dir):
        _append_event_sync(event)

    jsonl_file = list(events_dir.glob("*.jsonl"))[0]
    parsed = json.loads(jsonl_file.read_text().strip())
    # The payload in JSONL must NOT contain the secret
    assert "sk-live-supersecret" not in json.dumps(parsed)
    assert parsed["payload"]["redacted"] is True
    assert parsed["sensitivity"] == "secret"


# ---------------------------------------------------------------------------
# Durability guarantee — append failure skips cloud mirror
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_skips_cloud_mirror_on_append_failure(tmp_path: Path):
    """When _append_event_sync() raises, run() must NOT publish to eventlog.write."""
    from aegis.observability.eventlog import run

    events_dir = tmp_path / "events"
    event = make_event(source="aegis", event_type="error", payload={"err": "test"})

    with patch("aegis.observability.eventlog.EVENTS_DIR", events_dir):
        with patch("aegis.observability.eventlog.BUS") as mock_bus:
            import asyncio

            q: asyncio.Queue = asyncio.Queue()
            q.put_nowait(type("Msg", (), {"payload": event})())
            mock_bus.subscribe.return_value = q
            mock_bus.publish = AsyncMock()

            # Use an Event to synchronize: _append_event_sync is called → set event
            append_called = asyncio.Event()

            def _fail_append(evt):
                append_called.set()
                raise OSError("disk full")

            with patch("aegis.observability.eventlog._append_event_sync", side_effect=_fail_append):
                task = asyncio.create_task(run())
                await append_called.wait()  # wait until _append_event_sync was called
                await asyncio.sleep(0)  # let run() hit the return
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            # Verify eventlog.write was NOT published to
            write_calls = [
                c for c in mock_bus.publish.call_args_list if c[0][0] == "eventlog.write"
            ]
            assert len(write_calls) == 0, (
                f"eventlog.write should NOT be published when append fails, "
                f"but got {len(write_calls)} calls"
            )


# ---------------------------------------------------------------------------
# Concurrent-append serialization — no interleaving
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_appends_are_serialized(tmp_path: Path):
    """Multiple concurrent write_and_mirror() calls must not interleave JSONL records.

    Each record must be a complete, valid JSON line.  Interleaving would
    produce partial/corrupt lines.
    """
    from aegis.observability.eventlog import write_and_mirror

    events_dir = tmp_path / "events"
    N = 20
    events = [
        make_event(
            source="aegis",
            event_type="chat_turn",
            payload={"index": i, "data": "x" * 500},
        )
        for i in range(N)
    ]

    with patch("aegis.observability.eventlog.EVENTS_DIR", events_dir):
        with patch("aegis.observability.eventlog.BUS") as mock_bus:
            mock_bus.publish = AsyncMock()
            # Fire all writes concurrently
            await asyncio.gather(*[write_and_mirror(e) for e in events])

    jsonl_files = list(events_dir.glob("*.jsonl"))
    assert len(jsonl_files) == 1

    lines = jsonl_files[0].read_text().strip().split("\n")
    assert len(lines) == N, f"expected {N} lines, got {len(lines)}"

    # Every line must be valid JSON with the correct schema
    seen_indices = set()
    for line in lines:
        parsed = json.loads(line)
        assert set(parsed.keys()) == REQUIRED_FIELDS
        assert parsed["schema_version"] == SCHEMA_VERSION
        seen_indices.add(parsed["payload"]["index"])

    # All indices must be present (no drops)
    assert seen_indices == set(range(N))


# ---------------------------------------------------------------------------
# Once-local-plus-mirror invariant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_written_once_and_mirrored(tmp_path: Path):
    """Each event must hit local JSONL exactly once AND be published to eventlog.write.

    No event written twice, none dropped.  Both log_event() and any
    direct path go through write_and_mirror().
    """
    from aegis.observability.eventlog import write_and_mirror

    events_dir = tmp_path / "events"
    events = [
        make_event(source="aegis", event_type="chat_turn", payload={"i": i}) for i in range(5)
    ]

    with patch("aegis.observability.eventlog.EVENTS_DIR", events_dir):
        with patch("aegis.observability.eventlog.BUS") as mock_bus:
            mock_bus.publish = AsyncMock()

            for event in events:
                await write_and_mirror(event)

            # Count eventlog.write publishes
            write_calls = [
                c for c in mock_bus.publish.call_args_list if c[0][0] == "eventlog.write"
            ]
            assert len(write_calls) == len(events), (
                f"expected {len(events)} eventlog.write publishes, got {len(write_calls)}"
            )

            # Verify each published event matches what was written
            published = [c[0][1] for c in write_calls]
            for orig, pub in zip(events, published, strict=True):
                assert orig["event_type"] == pub["event_type"]
                assert orig["payload"] == pub["payload"]

    # Verify local JSONL has exactly one copy of each event
    jsonl_files = list(events_dir.glob("*.jsonl"))
    assert len(jsonl_files) == 1
    lines = jsonl_files[0].read_text().strip().split("\n")
    assert len(lines) == len(events), f"expected {len(events)} JSONL lines, got {len(lines)}"


@pytest.mark.asyncio
async def test_write_and_mirror_skips_mirror_on_append_failure(tmp_path: Path):
    """When _append_event_sync() raises, write_and_mirror() must NOT publish to eventlog.write."""
    from aegis.observability.eventlog import write_and_mirror

    events_dir = tmp_path / "events"
    event = make_event(source="aegis", event_type="error", payload={"err": "test"})

    with patch("aegis.observability.eventlog.EVENTS_DIR", events_dir):
        with patch("aegis.observability.eventlog.BUS") as mock_bus:
            mock_bus.publish = AsyncMock()

            with patch(
                "aegis.observability.eventlog._append_event_sync",
                side_effect=OSError("disk full"),
            ):
                await write_and_mirror(event)

            write_calls = [
                c for c in mock_bus.publish.call_args_list if c[0][0] == "eventlog.write"
            ]
            assert len(write_calls) == 0
