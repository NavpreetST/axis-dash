"""Supabase mirror sink — BUS subscriber for ``eventlog.write``.

Subscribes to the ``eventlog.write`` BUS topic, batches events, and upserts
them into Supabase via the REST API with idempotent merge-duplicates.

Feature-flagged OFF by default: requires both ``SUPABASE_URL`` and
``SUPABASE_SERVICE_KEY`` environment variables (sourced from
``~/.config/aegis/secrets.env``).  When absent the ``run()`` coroutine
returns immediately — zero overhead, zero network calls.

Resilience
----------
* Local ``asyncio.Queue`` decouples the BUS from the HTTP sink; local writes
  are never blocked.
* Failed batches are placed on an offline queue and retried with exponential
  back-off (1 s → 2 s → 4 s → … capped at 30 s).
* A periodic timer flushes the batch even when the batch size is not reached.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

import httpx

from aegis.nexus.bus import BUS

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (from env / secrets.env)
# ---------------------------------------------------------------------------
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")
TABLE_NAME: str = "events"

BATCH_SIZE: int = 20
FLUSH_INTERVAL_SECONDS: float = 30.0

# Retry / back-off
MAX_RETRIES: int = 5
INITIAL_BACKOFF: float = 1.0
BACKOFF_CAP: float = 30.0

# Offline queue cap (prevents unbounded memory growth when Supabase is down)
OFFLINE_QUEUE_MAX: int = 500

_enabled: bool = bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)

_REQUIRED_FIELDS: frozenset[str] = frozenset({
    "schema_version", "timestamp", "source", "event_type",
    "payload", "severity", "provenance", "sensitivity",
})

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_event(event: dict) -> bool:
    """Return *True* if *event* conforms to the frozen 8-field schema."""
    if not isinstance(event, dict):
        return False
    return (
        set(event.keys()) == _REQUIRED_FIELDS
        and isinstance(event.get("payload"), dict)
    )


async def _upsert_batch(batch: list[dict]) -> None:
    """POST *batch* to Supabase REST API with idempotent upsert.

    Retries up to ``MAX_RETRIES`` times with exponential back-off.
    Raises on final failure so callers can re-queue.
    """
    url = f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }

    backoff = INITIAL_BACKOFF
    last_exc: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=batch, headers=headers)
            if resp.status_code < 400:
                log.debug("supabase: upserted %d events (attempt %d)", len(batch), attempt)
                return
            # 4xx other than 409/429 are non-retryable
            if 400 <= resp.status_code < 500 and resp.status_code not in (409, 429):
                log.warning(
                    "supabase: non-retryable upsert %d: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return  # drop — poison event
            log.warning(
                "supabase: upsert %d (attempt %d/%d), retrying in %.1fs",
                resp.status_code, attempt, MAX_RETRIES, backoff,
            )
        except Exception as exc:
            last_exc = exc
            log.warning(
                "supabase: network error (attempt %d/%d) — %s, retrying in %.1fs",
                attempt, MAX_RETRIES, exc, backoff,
            )

        if attempt < MAX_RETRIES:
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_CAP)

    # All retries exhausted
    msg = f"supabase: upsert failed after {MAX_RETRIES} attempts"
    if last_exc:
        raise last_exc from None
    raise RuntimeError(msg)


# ---------------------------------------------------------------------------
# Core coroutine
# ---------------------------------------------------------------------------


async def run() -> None:
    """Subscribe to ``eventlog.write``, batch events, upsert to Supabase.

    When ``SUPABASE_URL`` / ``SUPABASE_SERVICE_KEY`` are unset the
    coroutine returns immediately (feature-flag OFF).
    """
    if not _enabled:
        log.info("supabase mirror: skipped (no SUPABASE_URL / SUPABASE_SERVICE_KEY)")
        return

    log.info("supabase mirror sink → %s", TABLE_NAME)

    try:
        q: asyncio.Queue = BUS.subscribe("eventlog.write")
    except Exception as exc:
        log.error("supabase mirror: subscribe failed — %s", exc)
        return

    batch: list[dict] = []
    offline_q: asyncio.Queue[list[dict]] = asyncio.Queue(maxsize=OFFLINE_QUEUE_MAX)
    last_flush = time.monotonic()

    # -- internal helpers ---------------------------------------------------

    async def _flush(current: list[dict]) -> None:
        """Attempt to upsert *current*; on failure stash in offline queue."""
        if not current:
            return
        try:
            await _upsert_batch(current)
        except Exception:
            try:
                offline_q.put_nowait(current)
            except asyncio.QueueFull:
                log.warning(
                    "supabase: offline queue full — dropping %d events", len(current)
                )

    async def _reconcile() -> None:
        """Periodically retry offline-queued batches."""
        while True:
            await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
            if offline_q.empty():
                continue
            # Drain up to 5 queued batches per cycle
            for _ in range(min(5, offline_q.qsize())):
                try:
                    queued = offline_q.get_nowait()
                except asyncio.QueueEmpty:
                    break
                try:
                    await _upsert_batch(queued)
                except Exception:
                    # Put back at front is impossible with Queue; re-enqueue
                    try:
                        offline_q.put_nowait(queued)
                    except asyncio.QueueFull:
                        log.warning("supabase: offline queue full during reconcile — drop")
                    break  # back-off: stop draining this cycle

    async def _listen() -> None:
        nonlocal batch, last_flush
        while True:
            try:
                elapsed = time.monotonic() - last_flush
                timeout = max(0.01, FLUSH_INTERVAL_SECONDS - elapsed)
                msg = await asyncio.wait_for(q.get(), timeout=timeout)
                if msg.payload and _validate_event(dict(msg.payload)):
                    batch.append(dict(msg.payload))
                    if len(batch) >= BATCH_SIZE:
                        await _flush(batch)
                        batch = []
                        last_flush = time.monotonic()
                else:
                    log.debug("supabase: dropped event with invalid schema")
            except asyncio.TimeoutError:
                await _flush(batch)
                batch = []
                last_flush = time.monotonic()
            except asyncio.CancelledError:
                # Drain remaining batch on shutdown
                await _flush(batch)
                batch = []
                raise
            except Exception as exc:
                log.warning("supabase mirror: listen error — %s", exc)

    # -- run both loops concurrently ----------------------------------------
    reconcile_task = asyncio.create_task(_reconcile())
    listen_task = asyncio.create_task(_listen())
    try:
        await asyncio.gather(listen_task, reconcile_task)
    finally:
        reconcile_task.cancel()
        listen_task.cancel()
        # Suppress CancelledError from tasks
        for t in (listen_task, reconcile_task):
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
