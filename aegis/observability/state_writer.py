"""Daemon state-writer — emits daemon_state.json every tick.

Subscribes to the 1 Hz tick bus, collects telemetry from the daemon's
state files and runtime, and writes a comprehensive daemon_state.json
to /var/lib/aegis/ on every tick.

AXIS and the bridge depend on this file for real KPI data.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from aegis.observability.paths import (
    NEUROBUS_STATE_PATH,
    RENDERER_STATE_PATH,
    STATE_DIR,
    atomic_write_json,
)

log = logging.getLogger(__name__)

_DAEMON_START = time.time()

NCP_PARAMS = 41361
NCP_HIDDEN = 64
NCP_INPUT_DIM = 388
NCP_OUTPUT_DIM = 40

_MODEL_MAP = {"gemini": "gemini-2.5-flash"}


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _build_renderer_chain(rend: dict) -> list[str]:
    chain = rend.get("chain")
    if isinstance(chain, list) and chain:
        return [_MODEL_MAP.get(p, p) for p in chain if isinstance(p, str)]
    return ["gemini-2.5-flash", "groq", "template"]


def _build_budget(rend: dict) -> dict:
    providers = rend.get("providers") or {}
    gemini = providers.get("gemini") or {}
    if isinstance(gemini, dict):
        return {
            "provider": "gemini",
            "used": gemini.get("local_daily_used"),
            "limit": gemini.get("local_daily_budget", 240),
            "reset_tz": gemini.get("quota_window", "America/Los_Angeles"),
        }
    return {"provider": "gemini", "used": None, "limit": 240, "reset_tz": "America/Los_Angeles"}


def _build_neurobus(neuro: dict) -> dict:
    return {
        "reward": neuro.get("reward", 0.0),
        "novelty": neuro.get("novelty", 0.0),
        "attention": neuro.get("attention", 0.5),
        "patience": neuro.get("patience", 0.5),
        "threat": neuro.get("threat", 0.0),
        "trust": neuro.get("trust", 0.5),
    }


def _build_daemon_state(tick_id: int) -> dict:
    rend = _read_json(RENDERER_STATE_PATH)
    neuro = _read_json(NEUROBUS_STATE_PATH)

    uptime_s = int(time.time() - _DAEMON_START)
    now = datetime.now(UTC).isoformat()

    return {
        "updated_at": now,
        "daemon_status": "online",
        "launch_method": "nohup",
        "socket_path": os.getenv("AEGIS_SOCK", "/tmp/aegis.sock"),
        "renderer_chain": _build_renderer_chain(rend),
        "memory_backend": {"type": "sqlite", "embedding": "minilm-384"},
        "ncp": {
            "params": NCP_PARAMS,
            "hidden": NCP_HIDDEN,
            "input_dim": NCP_INPUT_DIM,
            "output_dim": NCP_OUTPUT_DIM,
            "init_state": "random-init",
        },
        "budget": _build_budget(rend),
        "neurobus": _build_neurobus(neuro),
        "tick_id": tick_id,
        "tick_rate": 1.0,
        "uptime_s": uptime_s,
    }


async def run() -> None:
    from aegis.nexus.bus import BUS

    log.info("state-writer running")
    tick_q = BUS.subscribe("tick")
    while True:
        msg = await tick_q.get()
        tick_id = (msg.payload or {}).get("n", 0)
        try:
            state = _build_daemon_state(tick_id)
            atomic_write_json(STATE_DIR / "daemon_state.json", state)
        except (OSError, ValueError, TypeError) as e:
            log.warning("state-writer: failed to write daemon_state — %s", e)
