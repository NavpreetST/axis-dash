"""Tests for event producers — daemon lifecycle, renderer fallback, quota, brain crash.

Every producer must:
1. Emit through eventlog.log_event() (never write JSONL or hit Supabase/B2 directly).
2. Never block or crash the daemon path — log_event failure must not propagate.
3. Produce events that pass _validate_event() (8-field frozen schema, schema_version=1).
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from aegis.observability.eventlog import (
    make_event,
    VALID_SOURCES,
    VALID_EVENT_TYPES,
    VALID_SEVERITIES,
    VALID_SENSITIVITIES,
)


# ---------------------------------------------------------------------------
# Schema guard — every producer's event must pass _validate_event()
# ---------------------------------------------------------------------------

def _validate_event(event: dict) -> bool:
    """Mirror of supabase_sync._validate_event — rejects unknown fields."""
    required = {
        "schema_version", "timestamp", "source", "event_type",
        "payload", "severity", "provenance", "sensitivity",
    }
    if set(event.keys()) != required:
        return False
    if event.get("schema_version") != 1:
        return False
    if event.get("source") not in VALID_SOURCES:
        return False
    if event.get("event_type") not in VALID_EVENT_TYPES:
        return False
    if event.get("severity") not in VALID_SEVERITIES:
        return False
    if event.get("sensitivity") not in VALID_SENSITIVITIES:
        return False
    if not isinstance(event.get("payload"), dict):
        return False
    return True


def _assert_valid_event(event: dict) -> None:
    """Assert event passes schema validation."""
    assert _validate_event(event), f"Event failed validation: {event}"


# ---------------------------------------------------------------------------
# 1. Daemon startup — main.py (verify code path exists)
# ---------------------------------------------------------------------------

def test_startup_event_code_exists():
    """Verify main.py contains the startup event emission code."""
    import inspect
    from aegis import main
    source = inspect.getsource(main.main)
    assert 'event_type="task_done"' in source
    assert '"task": "boot"' in source
    assert '"status": "online"' in source
    assert 'severity="info"' in source


def test_startup_event_valid_shape():
    """Startup event shape passes schema validation."""
    event = make_event(
        source="aegis",
        event_type="task_done",
        payload={"task": "boot", "status": "online"},
        severity="info",
        sensitivity="internal",
    )
    _assert_valid_event(event)
    assert event["event_type"] == "task_done"
    assert event["severity"] == "info"


# ---------------------------------------------------------------------------
# 2. Daemon shutdown — main.py (verify code path exists)
# ---------------------------------------------------------------------------

def test_shutdown_event_code_exists():
    """Verify main.py contains the shutdown event emission code."""
    import inspect
    from aegis import main
    source = inspect.getsource(main.main)
    assert 'event_type="error"' in source
    assert '"reason": "shutdown"' in source
    assert 'severity="warn"' in source
    assert 'asyncio.wait_for(' in source


def test_shutdown_event_valid_shape():
    """Shutdown event shape passes schema validation."""
    event = make_event(
        source="aegis",
        event_type="error",
        payload={"where": "main_loop", "reason": "shutdown"},
        severity="warn",
        sensitivity="internal",
    )
    _assert_valid_event(event)
    assert event["event_type"] == "error"
    assert event["severity"] == "warn"


# ---------------------------------------------------------------------------
# 3. Renderer fallback — dispatcher.py
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fallback_emits_event():
    """Fallback from Gemini→Groq emits error / warn with correct payload."""
    from aegis.renderer.dispatcher import _render_with_chain

    events: list[dict] = []

    async def _capture_log_event(**kwargs):
        events.append(make_event(**kwargs))

    class FailGemini:
        name = "gemini"
        async def render(self, intent):
            raise Exception("gemini down")

    class GoodGroq:
        name = "groq"
        async def render(self, intent):
            return "groq says hi"

    with patch("aegis.renderer.dispatcher.CHAIN", [FailGemini, GoodGroq]):
        with patch("aegis.renderer.dispatcher.eventlog") as mock_eventlog:
            mock_eventlog.log_event = _capture_log_event
            with patch("aegis.observability.renderer_state.record_provider_attempt"):
                result = await _render_with_chain({"action": "speak"})

    fallback_events = [
        e for e in events
        if e.get("payload", {}).get("where") == "dispatcher"
        and e.get("payload", {}).get("fallback_to") == "groq"
    ]
    assert fallback_events, f"No fallback event emitted. Events: {events}"
    _assert_valid_event(fallback_events[0])
    assert fallback_events[0]["severity"] == "warn"
    assert fallback_events[0]["event_type"] == "error"
    assert fallback_events[0]["source"] == "aegis"
    assert fallback_events[0]["sensitivity"] == "internal"
    assert fallback_events[0]["payload"]["fallback_from"] == "gemini"
    assert fallback_events[0]["payload"]["fallback_to"] == "groq"


# ---------------------------------------------------------------------------
# 4. All renderers exhausted — dispatcher.py
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_exhausted_emits_critical():
    """All renderers fail emits error / critical."""
    from aegis.renderer.dispatcher import _render_with_chain

    events: list[dict] = []

    async def _capture_log_event(**kwargs):
        events.append(make_event(**kwargs))

    class FailGemini:
        name = "gemini"
        async def render(self, intent):
            raise Exception("gemini down")

    class FailGroq:
        name = "groq"
        async def render(self, intent):
            raise Exception("groq down")

    class FailTemplate:
        name = "template"
        async def render(self, intent):
            raise Exception("template down")

    with patch("aegis.renderer.dispatcher.CHAIN", [FailGemini, FailGroq, FailTemplate]):
        with patch("aegis.renderer.dispatcher.eventlog") as mock_eventlog:
            mock_eventlog.log_event = _capture_log_event
            with patch("aegis.observability.renderer_state.record_provider_attempt"):
                result = await _render_with_chain({"action": "speak"})

    exhausted = [
        e for e in events
        if e.get("payload", {}).get("error") == "all_adapters_exhausted"
    ]
    assert exhausted, f"No all-exhausted event emitted. Events: {events}"
    _assert_valid_event(exhausted[0])
    assert exhausted[0]["severity"] == "critical"
    assert exhausted[0]["event_type"] == "error"
    assert exhausted[0]["source"] == "aegis"
    assert exhausted[0]["sensitivity"] == "internal"


# ---------------------------------------------------------------------------
# 5. Quota exhausted — gemini.py
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_quota_exhausted_emits_event():
    """QuotaExhausted raises and emits error / warn with count/budget."""
    from aegis.renderer.gemini import render
    from aegis.renderer import QuotaExhausted

    events: list[dict] = []

    async def _capture_log_event(**kwargs):
        events.append(make_event(**kwargs))

    with patch("aegis.renderer.gemini._quota") as mock_quota:
        mock_quota.reserve.side_effect = QuotaExhausted("budget exhausted")
        mock_quota._load.return_value = {"count": 240, "budget": 240}
        mock_quota.DAILY_BUDGET = 240
        with patch("aegis.renderer.gemini.eventlog") as mock_eventlog:
            mock_eventlog.log_event = _capture_log_event
            with patch("aegis.renderer.gemini._api_key", return_value="fake-key"):
                with pytest.raises(QuotaExhausted):
                    await render({"action": "speak"})

    quota_events = [
        e for e in events
        if e.get("payload", {}).get("where") == "quota"
    ]
    assert quota_events, f"No quota event emitted. Events: {events}"
    _assert_valid_event(quota_events[0])
    assert quota_events[0]["severity"] == "warn"
    assert quota_events[0]["event_type"] == "error"
    assert quota_events[0]["source"] == "aegis"
    assert quota_events[0]["sensitivity"] == "internal"
    assert quota_events[0]["payload"]["count"] == 240
    assert quota_events[0]["payload"]["budget"] == 240


# ---------------------------------------------------------------------------
# 6. Day rollover — _quota.py + dispatcher drain
# ---------------------------------------------------------------------------

def test_day_rollover_pending():
    """Day rollover pushes to _DAY_ROLLOVER_PENDING."""
    from aegis.renderer import _quota
    import json
    from unittest.mock import patch

    # Clear pending
    _quota._DAY_ROLLOVER_PENDING.clear()

    # Simulate a usage file from yesterday
    old_usage = {"date": "2020-01-01", "count": 100}
    with patch.object(_quota, "_USAGE_PATH") as mock_path:
        mock_path.read_text.return_value = json.dumps(old_usage)
        mock_path.__truediv__ = lambda self, x: mock_path
        mock_path.with_suffix = lambda x: mock_path
        _quota._load()

    assert len(_quota._DAY_ROLLOVER_PENDING) == 1
    assert _quota._DAY_ROLLOVER_PENDING[0] == _quota._today_pacific()


def test_pop_day_rollover_drains():
    """pop_day_rollover() returns one date then clears."""
    from aegis.renderer import _quota

    _quota._DAY_ROLLOVER_PENDING.clear()
    _quota._DAY_ROLLOVER_PENDING.append("2026-06-08")

    result = _quota.pop_day_rollover()
    assert result == "2026-06-08"
    assert _quota.pop_day_rollover() is None


@pytest.mark.asyncio
async def test_day_rollover_emits_event_in_dispatcher():
    """Dispatcher tick loop drains day-rollover and emits task_created / info."""
    from aegis.renderer.dispatcher import run
    from aegis.renderer import _quota

    _quota._DAY_ROLLOVER_PENDING.clear()
    _quota._DAY_ROLLOVER_PENDING.append("2026-06-08")

    events: list[dict] = []

    async def _capture_log_event(**kwargs):
        events.append(make_event(**kwargs))

    # Create a minimal BUS mock that delivers one tick then blocks
    with patch("aegis.renderer.dispatcher.BUS") as mock_bus:
        tick_q: asyncio.Queue = asyncio.Queue()
        speak_q: asyncio.Queue = asyncio.Queue()
        tick_q.put_nowait(MagicMock(payload={"action": "tick"}))

        def subscribe(topic, maxsize=64):
            if topic == "intent.packet":
                return tick_q
            return speak_q
        mock_bus.subscribe = subscribe
        mock_bus.publish = AsyncMock()

        with patch("aegis.renderer.dispatcher.eventlog") as mock_eventlog:
            mock_eventlog.log_event = _capture_log_event
            task = asyncio.create_task(run())
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    rollover = [
        e for e in events
        if e.get("payload", {}).get("event") == "day_rollover"
    ]
    assert rollover, f"No day-rollover event emitted. Events: {events}"
    _assert_valid_event(rollover[0])
    assert rollover[0]["severity"] == "info"
    assert rollover[0]["event_type"] == "task_created"
    assert rollover[0]["source"] == "aegis"
    assert rollover[0]["sensitivity"] == "internal"


# ---------------------------------------------------------------------------
# 7. Brain crash — ncp.py (consume_tick is nested; test via run())
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_brain_crash_emits_event():
    """Forward-pass exception emits error / error and does NOT propagate."""
    from aegis.brain import ncp as ncp_mod

    events: list[dict] = []

    async def _capture_log_event(**kwargs):
        events.append(make_event(**kwargs))

    # Reset rate-limit state
    ncp_mod._last_crash_emit = 0.0

    tick_q: asyncio.Queue = asyncio.Queue()
    text_q: asyncio.Queue = asyncio.Queue()
    mem_q: asyncio.Queue = asyncio.Queue()

    with patch("aegis.brain.ncp.BUS") as mock_bus:
        def subscribe(topic, maxsize=64):
            if topic == "tick":
                return tick_q
            if topic == "sensor.text":
                return text_q
            return mem_q
        mock_bus.subscribe = subscribe
        mock_bus.publish = AsyncMock()

        with patch("aegis.brain.ncp._build_input_vec", side_effect=RuntimeError("brain crash")):
            with patch("aegis.brain.ncp.eventlog") as mock_eventlog:
                mock_eventlog.log_event = _capture_log_event

                # Inject text so consume_tick will process
                ncp_mod.LAST_TEXT_INPUT = "test input"
                tick_q.put_nowait(MagicMock(payload={"tick": 1}))

                task = asyncio.create_task(ncp_mod.run())
                await asyncio.sleep(0.1)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    crash_events = [
        e for e in events
        if e.get("payload", {}).get("where") == "brain.ncp.consume_tick"
    ]
    assert crash_events, f"No crash event emitted. Events: {events}"
    _assert_valid_event(crash_events[0])
    assert crash_events[0]["severity"] == "error"
    assert crash_events[0]["event_type"] == "error"
    assert crash_events[0]["source"] == "aegis"
    assert crash_events[0]["sensitivity"] == "internal"
    assert "brain crash" in crash_events[0]["payload"]["err"]


@pytest.mark.asyncio
async def test_brain_crash_still_publishes_next_tick():
    """After a crash, the next tick still works — daemon continues."""
    from aegis.brain import ncp as ncp_mod

    ncp_mod._last_crash_emit = 0.0
    ncp_mod.LAST_TEXT_INPUT = ""
    ncp_mod.WM.clear()
    ncp_mod.CONTEXT_TEXTS.clear()

    tick_q: asyncio.Queue = asyncio.Queue()
    text_q: asyncio.Queue = asyncio.Queue()
    mem_q: asyncio.Queue = asyncio.Queue()

    with patch("aegis.brain.ncp.BUS") as mock_bus:
        def subscribe(topic, maxsize=64):
            if topic == "tick":
                return tick_q
            if topic == "sensor.text":
                return text_q
            return mem_q
        mock_bus.subscribe = subscribe
        mock_bus.publish = AsyncMock()

        with patch("aegis.brain.ncp.eventlog") as mock_eventlog:
            mock_eventlog.log_event = AsyncMock()
            call_count = 0
            original_build = ncp_mod._build_input_vec

            def failing_then_ok(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise RuntimeError("first tick crash")
                return original_build(*args, **kwargs)

            with patch("aegis.brain.ncp._build_input_vec", side_effect=failing_then_ok):
                # First tick: crash
                ncp_mod.LAST_TEXT_INPUT = "crash tick"
                tick_q.put_nowait(MagicMock(payload={"tick": 1}))
                task = asyncio.create_task(ncp_mod.run())
                await asyncio.sleep(0.1)

                # Second tick: should work
                ncp_mod.LAST_TEXT_INPUT = "good tick"
                tick_q.put_nowait(MagicMock(payload={"tick": 2}))
                await asyncio.sleep(0.1)

                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # The second tick should have published an intent
        intent_calls = [c for c in mock_bus.publish.call_args_list if c[0][0] == "intent.packet"]
        assert len(intent_calls) >= 1, (
            f"Expected at least 1 intent publish after crash recovery, "
            f"got {len(intent_calls)}"
        )


# ---------------------------------------------------------------------------
# 8. Log_event failure never propagates — all producers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_brain_crash_log_failure_does_not_propagate():
    """If log_event itself raises, consume_tick continues without crashing."""
    from aegis.brain import ncp as ncp_mod

    ncp_mod._last_crash_emit = 0.0
    ncp_mod.LAST_TEXT_INPUT = "test"
    ncp_mod.WM.clear()

    tick_q: asyncio.Queue = asyncio.Queue()
    text_q: asyncio.Queue = asyncio.Queue()
    mem_q: asyncio.Queue = asyncio.Queue()

    with patch("aegis.brain.ncp.BUS") as mock_bus:
        def subscribe(topic, maxsize=64):
            if topic == "tick":
                return tick_q
            if topic == "sensor.text":
                return text_q
            return mem_q
        mock_bus.subscribe = subscribe
        mock_bus.publish = AsyncMock()

        with patch("aegis.brain.ncp._build_input_vec", side_effect=RuntimeError("crash")):
            with patch("aegis.brain.ncp.eventlog") as mock_eventlog:
                mock_eventlog.log_event = AsyncMock(side_effect=RuntimeError("BUS down"))
                tick_q.put_nowait(MagicMock(payload={"tick": 1}))
                task = asyncio.create_task(ncp_mod.run())
                await asyncio.sleep(0.05)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass


@pytest.mark.asyncio
async def test_dispatcher_fallback_log_failure_does_not_propagate():
    """If log_event raises during fallback, render still returns."""
    from aegis.renderer.dispatcher import _render_with_chain

    class FailGemini:
        name = "gemini"
        async def render(self, intent):
            raise Exception("gemini down")

    class GoodGroq:
        name = "groq"
        async def render(self, intent):
            return "groq says hi"

    with patch("aegis.renderer.dispatcher.CHAIN", [FailGemini, GoodGroq]):
        with patch("aegis.renderer.dispatcher.eventlog") as mock_eventlog:
            mock_eventlog.log_event = AsyncMock(side_effect=RuntimeError("BUS down"))
            with patch("aegis.observability.renderer_state.record_provider_attempt"):
                result = await _render_with_chain({"action": "speak"})

    # Render should still succeed despite log_event failure
    assert result["text"] == "groq says hi"
    assert result["provider"] == "groq"
    assert result["fallback_fired"] is True
