"""NIM overnight memory consolidation — batch re-summarization of Mnemosyne episodes.

FLAG-OFF by default: requires NVIDIA_API_KEY in secrets.env.
Uses the day-rollover hook (pop_day_rollover) as trigger — fires once at
the first post-midnight tick, exactly the off-peak window.

Architecture:
    consolidation.run() ──► subscribes to tick BUS
                         ──► drains pop_day_rollover() on every tick
                         ──► on rollover: query unconsolidated episodes
                         ──► chunk into batches → NIM /v1/chat/completions
                         ──► re-embed via MiniLM → store as action='consolidated'
                         ──► mark originals as consolidated=1

Crash isolation:
    run() wraps the entire consolidation logic in try/except so that an
    unhandled raise NEVER propagates into the daemon's asyncio.gather().
"""
from __future__ import annotations

import array
import asyncio
import json
import logging
import os
import time
from pathlib import Path

import httpx

from aegis.nexus.bus import BUS
from aegis.nim_budget import (
    NIM_BATCH_SIZE,
    NIM_MODEL,
    NIM_BUDGET,
    NimBudget,
)
from aegis.observability import eventlog

log = logging.getLogger(__name__)

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
NIM_ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"
MAX_RETRIES = 5
INITIAL_BACKOFF = 1.0
BACKOFF_CAP = 30.0

_enabled = bool(NVIDIA_API_KEY)

# Consolidation prompt — asks NIM to compact episodes into a memory document
CONSOLIDATION_PROMPT = """\
You are a memory consolidation agent. Summarize the following conversation \
episodes into a compact memory document. Preserve key facts, user preferences, \
important context, and decisions. Remove redundancy and filler. Output a single \
concise paragraph that captures the essential information.

Episodes to consolidate:
{episodes}
"""

_STATE_PATH = Path.home() / ".local" / "share" / "aegis" / "consolidation_state.json"


def _load_state() -> dict:
    """Load consolidation state (last_run timestamp, etc.)."""
    try:
        return json.loads(_STATE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict) -> None:
    """Atomic write of consolidation state."""
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(_STATE_PATH)


def _get_unconsolidated(conn) -> list[dict]:
    """Query episodes where consolidated=0 AND action != 'seed'.

    Returns list of {id, ts, text, action} dicts.
    """
    cur = conn.execute(
        "SELECT id, ts, text, action FROM episodes "
        "WHERE consolidated = 0 AND (action IS NULL OR action != 'seed') "
        "ORDER BY ts ASC"
    )
    return [{"id": r[0], "ts": r[1], "text": r[2], "action": r[3]} for r in cur.fetchall()]


def _mark_consolidated(conn, ids: list[int]) -> None:
    """Mark episodes as consolidated (authoritative cursor)."""
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    conn.execute(
        f"UPDATE episodes SET consolidated = 1 WHERE id IN ({placeholders})",
        ids,
    )
    conn.commit()


def _store_consolidated(conn, text: str, neurobus: str) -> None:
    """Store a consolidated episode with action='consolidated' and CURRENT ts."""
    from aegis.hive.text_encoder import get_model
    model = get_model()
    emb = model.encode(text, normalize_embeddings=True).tolist()
    conn.execute(
        "INSERT INTO episodes (ts, text, embedding, neurobus, action) "
        "VALUES (?, ?, ?, ?, ?)",
        (time.time(), f"CONSOLIDATED: {text}",
         array.array("f", emb).tobytes(),
         neurobus, "consolidated"),
    )
    conn.commit()


async def _call_nim(payload: dict) -> dict | None:
    """Call NIM with exponential backoff. Returns response or None on failure."""
    backoff = INITIAL_BACKOFF

    for attempt in range(MAX_RETRIES):
        # Rate-limit gate — use module-level singleton to share history
        wait = NIM_BUDGET.wait_s()
        if wait > 0:
            log.debug("consolidation: rate-limited, sleeping %.1fs", wait)
            await asyncio.sleep(wait)

        # Record the attempt in the shared budget
        if not NIM_BUDGET.allow():
            log.debug("consolidation: budget exhausted after allow check")
            await asyncio.sleep(1.0)
            continue

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    NIM_ENDPOINT,
                    headers={
                        "Authorization": f"Bearer {NVIDIA_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                if r.status_code == 429:
                    log.warning("consolidation: NIM 429, backoff %.1fs", backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, BACKOFF_CAP)
                    continue
                r.raise_for_status()
                return r.json()
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as e:
            log.warning("consolidation: NIM network error (attempt %d): %s", attempt + 1, e)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_CAP)
        except Exception as e:
            log.warning("consolidation: NIM unexpected error (attempt %d): %s", attempt + 1, e)
            return None

    log.error("consolidation: NIM call failed after %d retries", MAX_RETRIES)
    return None


def _format_episodes(episodes: list[dict]) -> str:
    """Format episodes for the consolidation prompt."""
    lines = []
    for ep in episodes:
        prefix = "User" if ep["action"] is None else "Aegis"
        lines.append(f"[{prefix}] {ep['text']}")
    return "\n".join(lines)


async def _consolidate_batch(conn, episodes: list[dict]) -> int:
    """Consolidate a batch of episodes via NIM. Returns count of episodes consolidated."""
    if not episodes:
        return 0

    episode_text = _format_episodes(episodes)
    prompt = CONSOLIDATION_PROMPT.format(episodes=episode_text)

    payload = {
        "model": NIM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 400,
        "temperature": 0.3,
    }

    response = await _call_nim(payload)
    if not response:
        return 0

    try:
        summary = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as e:
        log.warning("consolidation: malformed NIM response: %s", e)
        return 0

    if not summary or not summary.strip():
        return 0

    # Store consolidated episode and mark originals
    _store_consolidated(conn, summary.strip(), "{}")
    _mark_consolidated(conn, [ep["id"] for ep in episodes])

    return len(episodes)


async def _emit_event(event_type: str, severity: str, payload: dict) -> None:
    """Emit consolidation lifecycle event — best-effort, never block."""
    try:
        await asyncio.wait_for(
            eventlog.log_event(
                source="aegis",
                event_type=event_type,
                payload={"where": "consolidation", **payload},
                severity=severity,
                sensitivity="internal",
            ),
            timeout=2.0,
        )
    except Exception:
        log.debug("consolidation: failed to emit event", exc_info=True)


async def run() -> None:
    """Main consolidation loop — FLAG-OFF by default.

    Subscribes to tick BUS, drains pop_day_rollover() on every tick.
    On day-rollover: query unconsolidated episodes, chunk into batches,
    call NIM, re-embed, store, mark originals.
    """
    if not _enabled:
        log.info("consolidation: skipped (no NVIDIA_API_KEY)")
        await asyncio.Event().wait()
        return

    from aegis.renderer._quota import pop_day_rollover
    from aegis.mnemosyne.db import CONN

    log.info("consolidation: enabled (NIM model=%s, RPM cap=%d)", NIM_MODEL, NimBudget().rpm_cap)

    tick_q = BUS.subscribe("tick")

    while True:
        try:
            await tick_q.get()

            rollover_date = pop_day_rollover()
            if not rollover_date:
                continue

            log.info("consolidation: day-rollover detected (%s), starting batch", rollover_date)
            await _emit_event("task_created", "info", {
                "event": "batch_start",
                "rollover_date": rollover_date,
            })

            # Query unconsolidated episodes (authoritative cursor: consolidated=0)
            episodes = _get_unconsolidated(CONN)
            if not episodes:
                log.info("consolidation: no unconsolidated episodes, skipping")
                await _emit_event("task_done", "info", {
                    "event": "batch_done",
                    "episodes_consolidated": 0,
                    "reason": "nothing_to_consolidate",
                })
                continue

            # Chunk into batches
            batches = [episodes[i:i + NIM_BATCH_SIZE]
                       for i in range(0, len(episodes), NIM_BATCH_SIZE)]

            total_consolidated = 0
            for batch_idx, batch in enumerate(batches):
                log.info("consolidation: processing batch %d/%d (%d episodes)",
                         batch_idx + 1, len(batches), len(batch))
                count = await _consolidate_batch(CONN, batch)
                total_consolidated += count

                # Backpressure: sleep between batches to respect RPM cap
                if batch_idx < len(batches) - 1:
                    await asyncio.sleep(5.0)

            log.info("consolidation: batch complete — %d episodes consolidated",
                     total_consolidated)
            await _emit_event("task_done", "info", {
                "event": "batch_done",
                "episodes_consolidated": total_consolidated,
                "batches_processed": len(batches),
            })

            # Update state with current timestamp (trigger/resume marker, NOT dedup cursor)
            _save_state({"last_run": time.time(), "last_rollover": rollover_date})

        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("consolidation: unhandled error — %s", e, exc_info=True)
            await _emit_event("error", "warn", {"err": str(e)})
            # Continue the loop — crash isolation, never propagate
