"""Supabase mirror — batched upserts of events from the JSONL log.

Reads creds from ~/.config/aegis/secrets.env (NEVER from repo .env).
Gracefully skips if SUPABASE_URL or SUPABASE_SERVICE_KEY are not set.

Uses httpx (already a helios dependency) to hit the Supabase REST API.
No additional pip dependencies required.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

# Supabase REST API config — read from secrets.env via aegis.main bootstrap
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
TABLE_NAME = "events"

# Batch settings — upsert N events at a time, flush every M seconds
BATCH_SIZE = 20
FLUSH_INTERVAL_SECONDS = 30.0

_required_fields = frozenset({
    "schema_version", "timestamp", "source", "event_type",
    "payload", "severity", "provenance", "sensitivity",
})

_enabled = bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)


def _validate_event(event: dict) -> bool:
    """Return True if event has the required 8-field schema."""
    return set(event.keys()) == _required_fields and isinstance(event.get("payload"), dict)


async def _upsert_batch(batch: list[dict]) -> None:
    """POST a batch of events to Supabase REST API (upsert)."""
    import httpx

    url = f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=batch, headers=headers)
            if resp.status_code >= 400:
                log.warning(
                    "supabase: upsert failed (%d): %s",
                    resp.status_code,
                    resp.text[:200],
                )
            else:
                log.debug("supabase: upserted %d events", len(batch))
    except Exception as e:
        log.warning("supabase: upsert network error — %s", e)


async def run() -> None:
    """Periodically flush buffered events to Supabase.

    This is a STUB that can be activated by setting SUPABASE_URL and
    SUPABASE_SERVICE_KEY in ~/.config/aegis/secrets.env.  When creds
    are absent, the coroutine waits indefinitely (no-op).
    """
    if not _enabled:
        log.info("supabase mirror: skipped (no SUPABASE_URL / SUPABASE_SERVICE_KEY)")
        await asyncio.Event().wait()  # sleep forever (truly)
        return

    log.info("supabase mirror running → %s", TABLE_NAME)

    from aegis.nexus.bus import BUS

    try:
        q = BUS.subscribe("eventlog.write")
    except Exception as e:
        log.error("supabase mirror: failed to subscribe to eventlog.write — %s", e)
        return

    buffer: list[dict] = []

    async def _flush() -> None:
        nonlocal buffer
        if not buffer:
            return
        batch = list(buffer)
        buffer = []
        await _upsert_batch(batch)

    async def _listen() -> None:
        nonlocal buffer
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=FLUSH_INTERVAL_SECONDS)
                if msg.payload and _validate_event(dict(msg.payload)):
                    payload = dict(msg.payload) if msg.payload else {}
                    buffer.append(payload)
                    if len(buffer) >= BATCH_SIZE:
                        await _flush()
                else:
                    log.debug("supabase: dropped event with invalid schema")
            except asyncio.TimeoutError:
                await _flush()
            except Exception as e:
                log.warning("supabase mirror: listen error — %s", e)

    await _listen()
