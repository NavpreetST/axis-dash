"""Supabase task poller — polls Supabase tasks table for open forge tasks.

Every 15s, queries tasks WHERE status='open' AND phase='forge', claims the
first row, feeds it into ForgeDispatcher, and writes back the result.

Safe to run alongside socket-driven FORGE:SUBMIT: — only reads tasks that
originated in Supabase (phase='forge'), never touches socket-submitted tasks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from aegis.forge.dispatcher import ForgeDispatcher, TaskStatus

log = logging.getLogger(__name__)

SUPABASE_URL: str = ""
SUPABASE_KEY: str = ""
TABLE_NAME: str = "tasks"
POLL_INTERVAL_S: float = 15.0

_enabled: bool = False


def _read_config() -> None:
    global SUPABASE_URL, SUPABASE_KEY, _enabled
    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "") or os.getenv("SERVICE_ROLE", "") or os.getenv("SUPABASE_ANON_KEY", "")
    _enabled = bool(SUPABASE_URL and SUPABASE_KEY)


async def run(dispatcher: ForgeDispatcher) -> None:
    """Poll Supabase every 15s for open forge tasks, claim and dispatch."""
    _read_config()
    if not _enabled:
        log.info("forge supabase poller: skipped (no SUPABASE_URL / SUPABASE_ANON_KEY)")
        return

    log.info("forge supabase poller: polling %s/%s every %.0fs",
             SUPABASE_URL, TABLE_NAME, POLL_INTERVAL_S)

    while True:
        try:
            await _poll_once(dispatcher)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("forge supabase poller: poll error — %s", e, exc_info=True)
        await asyncio.sleep(POLL_INTERVAL_S)


async def _poll_once(dispatcher: ForgeDispatcher) -> None:
    """Single poll cycle: fetch open tasks, claim first, submit to forge."""
    tasks = await _fetch_open_tasks()
    if not tasks:
        return

    task = tasks[0]
    task_id = task.get("id")
    spec = task.get("spec") or task.get("description", "")
    if not task_id or not spec:
        log.warning(
            "forge supabase poller: open task %s missing id or spec", task_id
        )
        return

    if not await _claim_task(task_id):
        log.warning("forge supabase poller: failed to claim task %s", task_id)
        return

    try:
        from aegis.forge.dispatcher import TaskStatus

        forge_task = await dispatcher.submit(spec)
        forge_task = await dispatcher.execute(forge_task.id)

        result_status = (
            "complete" if forge_task.status == TaskStatus.COMPLETED else "failed"
        )
        summary = json_summary(forge_task)
        await _write_result(task_id, result_status, summary)
        log.info("forge supabase poller: task %s -> %s", task_id, result_status)
    except Exception as e:
        log.error(
            "forge supabase poller: dispatch error for task %s — %s", task_id, e
        )
        await _write_result(task_id, "failed", {"error": str(e)})


async def _fetch_open_tasks() -> list[dict]:
    """Fetch first open-forge task, ordered by creation time."""
    url = f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}"
    headers = _headers()
    params = {
        "status": "eq.open",
        "phase": "eq.forge",
        "limit": "1",
        "order": "created_at.asc,id.asc",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.warning("forge supabase poller: fetch error — %s", e)
        return []


async def _claim_task(task_id: str) -> bool:
    """Claim an open task by id, returns True if row was updated."""
    url = f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}"
    headers = _headers()
    headers["Prefer"] = "return=representation"
    body = {
        "status": "in_progress",
        "owner": "forge",
        "updated_at": _now_iso(),
    }
    params = {
        "status": "eq.open",
        "id": f"eq.{task_id}",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.patch(url, json=body, headers=headers, params=params)
        if resp.status_code < 400:
            data = resp.json()
            return isinstance(data, list) and len(data) > 0
        log.warning("forge supabase poller: claim status %d for task %s",
                     resp.status_code, task_id)
        return False
    except Exception as e:
        log.warning("forge supabase poller: claim error — %s", e)
        return False


async def _write_result(task_id: str, status: str, summary: dict) -> None:
    """Write task result back to Supabase."""
    url = f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}"
    headers = _headers()
    headers["Prefer"] = "return=minimal"
    body = {
        "status": status,
        "result_summary": json.dumps(summary) if isinstance(summary, dict) else summary,
        "updated_at": _now_iso(),
    }
    params = {"id": f"eq.{task_id}"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.patch(url, json=body, headers=headers, params=params)
        if resp.status_code >= 400:
            log.warning("forge supabase poller: write result status %d for task %s",
                         resp.status_code, task_id)
    except Exception as e:
        log.warning("forge supabase poller: write result error — %s", e)


def _headers() -> dict[str, str]:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def json_summary(task) -> dict:
    """Build a summary dict from a completed ForgeTask."""
    return {
        "status": task.status.value,
        "diff_count": len(task.diffs),
        "files_created": task.files_created,
        "files_modified": task.files_modified,
        "error": task.error,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
