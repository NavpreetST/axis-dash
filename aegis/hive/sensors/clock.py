"""Calendar clock sensor — datetime-based time/day/week awareness.

Publishes (time_s, day_of_week, week_num) to NeuroBus channel "sensor.clock"
once per second on the tick boundary.

Usage:
    from aegis.hive.sensors.clock import run
    await run(hz=1.0)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from aegis.nexus.bus import BUS

log = logging.getLogger("hive.sensors.clock")


async def run(hz: float = 1.0) -> None:
    period = 1.0 / hz
    log.info("clock sensor starting at %.1f Hz", hz)
    while True:
        now = datetime.now(UTC)
        await BUS.publish("sensor.clock", {
            "time_s": now.timestamp(),
            "day_of_week": now.strftime("%A"),
            "week_num": now.isocalendar().week,
            "iso": now.isoformat(),
        })
        await asyncio.sleep(period)
