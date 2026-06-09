"""Filesystem watcher sensor — watchfiles-based .md change detector.

Monitors Helios/ for .md file changes and publishes (file_path, change_type)
to NeuroBus channel "sensor.fs".  Runs as a long-lived asyncio task.

Usage:
    from aegis.hive.sensors.fs_watcher import run
    await run(watch_dir=Path("/opt/aegis/Helios"), poll_interval=1.0)
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aegis.nexus.bus import BUS

log = logging.getLogger("hive.sensors.fs_watcher")

WATCH_DIR = Path("/opt/aegis/Helios")


async def run(watch_dir: Path = WATCH_DIR, poll_interval: float = 1.0) -> None:
    known: dict[Path, float] = {}
    while True:
        if watch_dir.is_dir():
            for p in watch_dir.rglob("*.md"):
                mtime = p.stat().st_mtime
                prev = known.get(p)
                if prev is None:
                    known[p] = mtime
                    await BUS.publish("sensor.fs", {"file_path": str(p), "change_type": "created"})
                elif mtime > prev:
                    known[p] = mtime
                    await BUS.publish("sensor.fs", {"file_path": str(p), "change_type": "modified"})
            gone = [p for p in known if not p.exists()]
            for p in gone:
                del known[p]
                await BUS.publish("sensor.fs", {"file_path": str(p), "change_type": "deleted"})
        await asyncio.sleep(poll_interval)
