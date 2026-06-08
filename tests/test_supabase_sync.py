"""Tests for the Supabase mirror sink (supabase_sync)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from aegis.observability.eventlog import make_event, REQUIRED_FIELDS


def _make_msg(event: dict):
    """Wrap *event* in a fake BUS message object."""
    return type("Msg", (), {"payload": event})()


# ---------------------------------------------------------------------------
# Feature-flag OFF → no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_returns_immediately_when_disabled():
    """run() must return immediately when SUPABASE_URL / KEY are unset."""
    from aegis.observability import supabase_sync

    with patch.object(supabase_sync, "_enabled", False):
        result = await supabase_sync.run()
        assert result is None  # returns, does not block


# ---------------------------------------------------------------------------
# Once-mirrored invariant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_once_mirrored():
    """One event published to eventlog.write must be upserted exactly once."""
    from aegis.observability import supabase_sync

    event = make_event(source="aegis", event_type="chat_turn", payload={"t": 1})
    q: asyncio.Queue = asyncio.Queue()
    q.put_nowait(_make_msg(event))

    mock_upsert = AsyncMock()

    with patch.object(supabase_sync, "_enabled", True), \
         patch.object(supabase_sync, "_upsert_batch", mock_upsert), \
         patch("aegis.observability.supabase_sync.BUS") as mock_bus:
        mock_bus.subscribe.return_value = q

        task = asyncio.create_task(supabase_sync.run())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert mock_upsert.call_count >= 1
    first_call_batch = mock_upsert.call_args_list[0][0][0]
    assert len(first_call_batch) == 1
    assert first_call_batch[0]["event_type"] == "chat_turn"


# ---------------------------------------------------------------------------
# Idempotent replay — merge-duplicates header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_uses_merge_duplicates_header():
    """_upsert_batch must send Prefer: resolution=merge-duplicates."""
    from aegis.observability import supabase_sync

    batch = [make_event(source="aegis", event_type="chat_turn", payload={"i": 0})]

    with patch("aegis.observability.supabase_sync.httpx") as mock_httpx:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.AsyncClient.return_value = mock_client

        await supabase_sync._upsert_batch(batch)

        _, kwargs = mock_client.post.call_args
        assert kwargs["headers"]["Prefer"] == "resolution=merge-duplicates"


# ---------------------------------------------------------------------------
# Retry with back-off on failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_retries_on_server_error():
    """_upsert_batch must retry up to MAX_RETRIES on 5xx."""
    from aegis.observability import supabase_sync

    batch = [make_event(source="aegis", event_type="error", payload={})]

    with patch("aegis.observability.supabase_sync.httpx") as mock_httpx, \
         patch("aegis.observability.supabase_sync.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        mock_resp_500 = MagicMock(status_code=500, text="err")
        mock_resp_200 = MagicMock(status_code=200, text="ok")
        mock_client = AsyncMock()
        mock_client.post.side_effect = [mock_resp_500, mock_resp_500, mock_resp_200]
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.AsyncClient.return_value = mock_client

        await supabase_sync._upsert_batch(batch)

        assert mock_client.post.call_count == 3
        assert mock_sleep.call_count == 2  # slept twice before success


@pytest.mark.asyncio
async def test_upsert_does_not_retry_on_4xx_non_retryable():
    """4xx (not 409/429) must NOT be retried."""
    from aegis.observability import supabase_sync

    batch = [make_event(source="aegis", event_type="chat_turn", payload={})]

    with patch("aegis.observability.supabase_sync.httpx") as mock_httpx:
        mock_resp_400 = MagicMock(status_code=400, text="bad request")
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp_400
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.AsyncClient.return_value = mock_client

        await supabase_sync._upsert_batch(batch)

        assert mock_client.post.call_count == 1  # no retry


# ---------------------------------------------------------------------------
# Offline queue + reconcile
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_batch_goes_to_offline_queue():
    """When upsert fails, the batch must be queued for later retry by reconcile."""
    from aegis.observability import supabase_sync

    event = make_event(source="aegis", event_type="chat_turn", payload={"q": True})
    q: asyncio.Queue = asyncio.Queue()
    q.put_nowait(_make_msg(event))

    call_count = 0

    async def _fake_upsert(batch):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("connection refused")

    with patch.object(supabase_sync, "_enabled", True), \
         patch.object(supabase_sync, "_upsert_batch", side_effect=_fake_upsert), \
         patch.object(supabase_sync, "FLUSH_INTERVAL_SECONDS", 0.01), \
         patch("aegis.observability.supabase_sync.BUS") as mock_bus:
        mock_bus.subscribe.return_value = q

        task = asyncio.create_task(supabase_sync.run())
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert call_count >= 2, (
        f"Expected initial failure + reconcile retry (>= 2 calls), got {call_count}"
    )


# ---------------------------------------------------------------------------
# Schema validation rejects bad events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_event_dropped():
    """Events missing required fields must be dropped (not upserted)."""
    from aegis.observability import supabase_sync

    bad_event = {"schema_version": 1, "extra": True}
    q: asyncio.Queue = asyncio.Queue()
    q.put_nowait(_make_msg(bad_event))

    mock_upsert = AsyncMock()

    with patch.object(supabase_sync, "_enabled", True), \
         patch.object(supabase_sync, "_upsert_batch", mock_upsert), \
         patch("aegis.observability.supabase_sync.BUS") as mock_bus:
        mock_bus.subscribe.return_value = q

        task = asyncio.create_task(supabase_sync.run())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    mock_upsert.assert_not_called()


# ---------------------------------------------------------------------------
# _validate_event
# ---------------------------------------------------------------------------


def test_validate_event_accepts_valid():
    from aegis.observability import supabase_sync

    event = make_event(source="aegis", event_type="chat_turn", payload={})
    assert supabase_sync._validate_event(event) is True


def test_validate_event_rejects_missing_field():
    from aegis.observability import supabase_sync

    event = make_event(source="aegis", event_type="chat_turn", payload={})
    del event["severity"]
    assert supabase_sync._validate_event(event) is False


def test_validate_event_rejects_extra_field():
    from aegis.observability import supabase_sync

    event = make_event(source="aegis", event_type="chat_turn", payload={})
    event["bogus"] = 1
    assert supabase_sync._validate_event(event) is False


def test_validate_event_rejects_non_dict_payload():
    from aegis.observability import supabase_sync

    event = make_event(source="aegis", event_type="chat_turn", payload={})
    event["payload"] = "not a dict"
    assert supabase_sync._validate_event(event) is False


def test_validate_event_rejects_non_mapping():
    from aegis.observability import supabase_sync

    assert supabase_sync._validate_event("not a dict") is False
    assert supabase_sync._validate_event(42) is False
    assert supabase_sync._validate_event(None) is False
    assert supabase_sync._validate_event([1, 2, 3]) is False


# ---------------------------------------------------------------------------
# Startup reconciliation — backfill JSONL → Supabase
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconcile_jsonl_backfills_events(tmp_path: Path):
    """_reconcile_jsonl must read JSONL files and upsert to Supabase."""
    from aegis.observability import supabase_sync

    events_dir = tmp_path / "events"
    events_dir.mkdir()

    # Write 3 events to a JSONL file
    events = [
        make_event(source="aegis", event_type="chat_turn", payload={"i": i})
        for i in range(3)
    ]
    jsonl_file = events_dir / "2025-01-15.jsonl"
    jsonl_file.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n",
        encoding="utf-8",
    )

    mock_upsert = AsyncMock()

    with patch.object(supabase_sync, "EVENTS_DIR", events_dir), \
         patch.object(supabase_sync, "RECONCILE_STATE_PATH", events_dir / ".reconcile.json"), \
         patch.object(supabase_sync, "_upsert_batch", mock_upsert):
        await supabase_sync._reconcile_jsonl()

    assert mock_upsert.call_count == 1
    batch = mock_upsert.call_args_list[0][0][0]
    assert len(batch) == 3
    assert batch[0]["event_type"] == "chat_turn"


@pytest.mark.asyncio
async def test_reconcile_skips_already_synced_lines(tmp_path: Path):
    """Lines already synced (tracked in state file) must be skipped."""
    from aegis.observability import supabase_sync

    events_dir = tmp_path / "events"
    events_dir.mkdir()

    events = [
        make_event(source="aegis", event_type="chat_turn", payload={"i": i})
        for i in range(5)
    ]
    jsonl_file = events_dir / "2025-01-15.jsonl"
    jsonl_file.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n",
        encoding="utf-8",
    )

    # State says first 3 lines already synced
    state_path = events_dir / ".reconcile.json"
    state_path.write_text(json.dumps({"2025-01-15.jsonl": 3}), encoding="utf-8")

    mock_upsert = AsyncMock()

    with patch.object(supabase_sync, "EVENTS_DIR", events_dir), \
         patch.object(supabase_sync, "RECONCILE_STATE_PATH", state_path), \
         patch.object(supabase_sync, "_upsert_batch", mock_upsert):
        await supabase_sync._reconcile_jsonl()

    # Only 2 new lines should be upserted
    assert mock_upsert.call_count == 1
    batch = mock_upsert.call_args_list[0][0][0]
    assert len(batch) == 2
    assert batch[0]["payload"]["i"] == 3
    assert batch[1]["payload"]["i"] == 4


@pytest.mark.asyncio
async def test_reconcile_saves_state_after_sync(tmp_path: Path):
    """State file must be updated after successful sync."""
    from aegis.observability import supabase_sync

    events_dir = tmp_path / "events"
    events_dir.mkdir()

    events = [
        make_event(source="aegis", event_type="chat_turn", payload={"i": i})
        for i in range(3)
    ]
    jsonl_file = events_dir / "2025-01-15.jsonl"
    jsonl_file.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n",
        encoding="utf-8",
    )

    state_path = events_dir / ".reconcile.json"

    with patch.object(supabase_sync, "EVENTS_DIR", events_dir), \
         patch.object(supabase_sync, "RECONCILE_STATE_PATH", state_path), \
         patch.object(supabase_sync, "_upsert_batch", new_callable=AsyncMock):
        await supabase_sync._reconcile_jsonl()

    assert state_path.exists()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["2025-01-15.jsonl"] == 3


@pytest.mark.asyncio
async def test_run_calls_reconcile_on_startup(tmp_path: Path):
    """run() must call _reconcile_jsonl() before subscribing to BUS."""
    from aegis.observability import supabase_sync

    reconcile_called = False
    original_reconcile = supabase_sync._reconcile_jsonl

    async def _mock_reconcile():
        nonlocal reconcile_called
        reconcile_called = True

    q: asyncio.Queue = asyncio.Queue()

    with patch.object(supabase_sync, "_enabled", True), \
         patch.object(supabase_sync, "_reconcile_jsonl", side_effect=_mock_reconcile), \
         patch("aegis.observability.supabase_sync.BUS") as mock_bus:
        mock_bus.subscribe.return_value = q

        task = asyncio.create_task(supabase_sync.run())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert reconcile_called
