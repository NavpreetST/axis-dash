"""System metrics sensor — psutil-based CPU/mem/disk/network poller.

Publishes 4 scalars at ~1 Hz to NeuroBus channel "sensor.sys":
  cpu_pct, mem_pct, disk_pct, net_speed_kbps

Usage:
    from aegis.hive.sensors.sys_metrics import run
    await run()
"""
from __future__ import annotations

import asyncio
import logging

import psutil

from aegis.nexus.bus import BUS

log = logging.getLogger("hive.sensors.sys_metrics")

_INTERVAL = 1.0
_prev_net: tuple[int, int] | None = None


async def run() -> None:
    global _prev_net
    log.info("sys_metrics sensor started (%.1f Hz)", 1.0 / _INTERVAL)
    while True:
        cpu_pct = psutil.cpu_percent(interval=0)
        mem_pct = psutil.virtual_memory().percent
        disk_pct = psutil.disk_usage("/").percent

        net = psutil.net_io_counters()
        if _prev_net is not None:
            dt = _INTERVAL
            net_speed = (net.bytes_recv - _prev_net[0]) * 8 / (dt * 1000)
            net_speed_kbps = round(net_speed, 2)
        else:
            net_speed_kbps = 0.0
        _prev_net = (net.bytes_recv, net.bytes_sent)

        await BUS.publish("sensor.sys", {
            "cpu_pct": cpu_pct,
            "mem_pct": mem_pct,
            "disk_pct": disk_pct,
            "net_speed_kbps": net_speed_kbps,
        })
        await asyncio.sleep(_INTERVAL)
