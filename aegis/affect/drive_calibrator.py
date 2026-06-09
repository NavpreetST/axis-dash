"""Sensitivity drive calibrator — 5 drives from sensor noise + interaction frequency.

Produces 5 sensitivity drives and publishes to NeuroBus channel "affect.drive":

  tiger   — reactive / threat-sensitive   (driven by threat + novelty)
  bird    — exploratory / reward-seeking   (driven by reward + attention)
  ant/bee — persistent / detail-oriented   (driven by patience + repetition)
  octopus — flexible / context-switching   (driven by novelty + low attention)
  corvid  — social / trust-building        (driven by trust + interaction count)

Each drive is a leaky integrator updated every tick.

Usage:
    from aegis.affect.drive_calibrator import run
    await run()
"""
from __future__ import annotations

import asyncio
import logging

from aegis.nexus.bus import BUS

log = logging.getLogger("affect.drive_calibrator")

_DECAY: dict[str, float] = {
    "tiger": 0.95,
    "bird": 0.96,
    "ant_bee": 0.98,
    "octopus": 0.94,
    "corvid": 0.97,
}

_drives: dict[str, float] = {k: 0.3 for k in _DECAY}


def _calibrate(neuro: dict[str, float], interaction_count: int = 0) -> dict[str, float]:
    r = neuro.get("reward", 0.0)
    n = neuro.get("novelty", 0.0)
    a = neuro.get("attention", 0.5)
    p = neuro.get("patience", 0.5)
    t = neuro.get("threat", 0.0)
    tr = neuro.get("trust", 0.5)

    return {
        "tiger": t * 0.6 + n * 0.2,
        "bird": r * 0.5 + a * 0.3,
        "ant_bee": p * 0.4 + a * 0.2,
        "octopus": n * 0.4 + (1.0 - a) * 0.3,
        "corvid": tr * 0.5 + min(1.0, interaction_count / 100) * 0.2,
    }


async def run() -> None:
    log.info("drive_calibrator running")
    interaction_count = 0
    tick_q = BUS.subscribe("tick")
    neuro_q = BUS.subscribe("neurobus.state")
    sense_q = BUS.subscribe("sensor.*")

    async def on_tick() -> None:
        while True:
            await tick_q.get()
            for k in _drives:
                _drives[k] *= _DECAY[k]
            await BUS.publish("affect.drive", dict(_drives))

    async def on_neuro() -> None:
        while True:
            msg = await neuro_q.get()
            raw = _calibrate(msg.payload, interaction_count)
            for k, v in raw.items():
                _drives[k] = min(1.0, _drives[k] + v * 0.1)

    async def on_sense() -> None:
        nonlocal interaction_count
        while True:
            await sense_q.get()
            interaction_count += 1

    await asyncio.gather(on_tick(), on_neuro(), on_sense())
