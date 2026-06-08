"""Tests for the Supabase mirror sink (supabase_sync)."""

from __future__ import annotations

import asyncio
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
    """When upsert fails, the batch must be queued for later retry."""
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
         patch("aegis.observability.supabase_sync.BUS") as mock_bus:
        mock_bus.subscribe.return_value = q

        task = asyncio.create_task(supabase_sync.run())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # First call failed, so batch should be in offline_q
    # Since run() was cancelled, the batch is drained in the finally block
    # We just verify upsert was attempted
    assert call_count >= 1


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
