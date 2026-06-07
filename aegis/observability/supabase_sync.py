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
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
TABLE_NAME = "events"

# Batch settings — upsert N events at a time, flush every M seconds
BATCH_SIZE = 20
FLUSH_INTERVAL_SECONDS = 30.0

_enabled = bool(SUPABASE_URL and SUPABASE_KEY)


async def _upsert_batch(batch: list[dict]) -> None:
    """POST a batch of events to Supabase REST API (upsert)."""
    import httpx

    url = f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }

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


async def run() -> None:
    """Periodically flush buffered events to Supabase.

    This is a STUB that can be activated by setting SUPABASE_URL and
    SUPABASE_SERVICE_KEY in ~/.config/aegis/secrets.env.  When creds
    are absent, the coroutine simply sleeps forever (no-op).
    """
    if not _enabled:
        log.info("supabase mirror: skipped (no SUPABASE_URL / SUPABASE_SERVICE_KEY)")
        await asyncio.sleep(3600 * 24 * 365)  # sleep forever
        return

    log.info("supabase mirror running → %s", TABLE_NAME)

    from aegis.nexus.bus import BUS

    q = BUS.subscribe("eventlog.write")
    buffer: list[dict] = []
    last_flush = asyncio.get_event_loop().time()

    async def _flush() -> None:
        nonlocal buffer, last_flush
        if not buffer:
            return
        batch = list(buffer)
        buffer = []
        last_flush = asyncio.get_event_loop().time()
        await _upsert_batch(batch)

    async def _listen() -> None:
        nonlocal buffer, last_flush
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=FLUSH_INTERVAL_SECONDS)
                payload = dict(msg.payload) if msg.payload else {}
                buffer.append(payload)
                if len(buffer) >= BATCH_SIZE:
                    await _flush()
            except asyncio.TimeoutError:
                await _flush()

    await _listen()
