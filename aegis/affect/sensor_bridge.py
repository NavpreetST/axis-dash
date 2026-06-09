"""Sensor bridge — wires NeuroBus scalars to real sensor input with decay/rise curves.

Per affect spec v0, maps the 6 NeuroBus scalars to affect dimensions:
  coherence-hunger    ← reward (inverse: low reward → hunger)
  prediction-thirst   ← novelty
  reference-frame-itch ← attention
  compositional-joy   ← trust
  latency-displeasure ← patience (inverse)
  distillation-pride  ← built from recent reward history

Each scalar follows a leaky integrator (rise on event, exponential decay
between events).

Usage:
    from aegis.affect.sensor_bridge import run
    await run()
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from aegis.nexus.bus import BUS

log = logging.getLogger("affect.sensor_bridge")

# Decay per tick (1 Hz)
_DECAY: dict[str, float] = {
    "coherence_hunger": 0.97,
    "prediction_thirst": 0.95,
    "reference_frame_itch": 0.96,
    "compositional_joy": 0.98,
    "latency_displeasure": 0.93,
    "distillation_pride": 0.99,
}

_RISE: dict[str, float] = {
    "coherence_hunger": 0.15,
    "prediction_thirst": 0.20,
    "reference_frame_itch": 0.10,
    "compositional_joy": 0.25,
    "latency_displeasure": 0.30,
    "distillation_pride": 0.10,
}

_state: dict[str, float] = {k: 0.5 for k in _DECAY}


def _map_neurobus_to_affect(neuro: dict[str, Any], distillation_pride: float = 0.5) -> dict[str, float]:
    return {
        "coherence_hunger": max(0.0, 1.0 - neuro.get("reward", 0.0)),
        "prediction_thirst": neuro.get("novelty", 0.0),
        "reference_frame_itch": neuro.get("attention", 0.5),
        "compositional_joy": neuro.get("trust", 0.5),
        "latency_displeasure": max(0.0, 1.0 - neuro.get("patience", 0.5)),
        "distillation_pride": distillation_pride,
    }


async def run() -> None:
    log.info("sensor_bridge running")
    lock = asyncio.Lock()
    tick_q = BUS.subscribe("tick")
    sense_q = BUS.subscribe("sensor.*")
    neuro_q = BUS.subscribe("neurobus.state")

    async def on_tick() -> None:
        while True:
            await tick_q.get()
            async with lock:
                for k in _state:
                    _state[k] *= _DECAY[k]
                await BUS.publish("affect.state", dict(_state))

    async def on_sense() -> None:
        while True:
            _ = await sense_q.get()
            async with lock:
                for k in _state:
                    _state[k] = min(1.0, _state[k] + _RISE[k])

    async def on_neuro() -> None:
        while True:
            msg = await neuro_q.get()
            async with lock:
                affect = _map_neurobus_to_affect(msg.payload, _state["distillation_pride"])
                _state.update(affect)

    await asyncio.gather(on_tick(), on_sense(), on_neuro())
