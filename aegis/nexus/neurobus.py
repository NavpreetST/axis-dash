"""Aegis Nexus — 6-scalar neuromodulator state.

Mirrors the brainstem chemicals (Psyche §NeuroBus):
  reward    (DA)    was outcome better/worse than expected?
  novelty   (NE)    how unfamiliar is the current frame?
  attention (ACh)   how worth attending?
  patience  (5-HT)  willingness to wait for delayed reward
  threat    (amyg)  danger / aversive signal
  trust     (OT)    bias toward in-group / familiar context
"""
from __future__ import annotations
import asyncio
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

from .bus import BUS
from aegis.observability.paths import NEUROBUS_STATE_PATH, atomic_write_json

log = logging.getLogger("nexus.neurobus")


@dataclass
class NeuroState:
    reward: float = 0.0
    novelty: float = 0.0
    attention: float = 0.5
    patience: float = 0.5
    threat: float = 0.0
    trust: float = 0.5

    def vec(self) -> list[float]:
        return [self.reward, self.novelty, self.attention,
                self.patience, self.threat, self.trust]

    def clamp(self) -> None:
        for f in ("reward", "novelty", "attention",
                  "patience", "threat", "trust"):
            v = getattr(self, f)
            setattr(self, f, max(-1.0, min(1.0, v)))


STATE = NeuroState()

# per-tick decay rates at 1 Hz
DECAY = {
    "reward":    0.95,
    "novelty":   0.90,
    "attention": 0.98,
    "patience":  0.99,
    "threat":    0.95,
    "trust":     0.999,
}


def _orb_state_dir() -> Path:
    return Path(os.getenv("AEGIS_STATE_DIR", "/var/lib/aegis"))


def _build_orb_snapshot() -> dict:
    """Build the richer orb snapshot for the web server.

    Best-effort: if optional imports fail, fall back to safe defaults.
    Import errors are logged at debug; the tick loop must never be killed
    by a missing optional module.
    """
    now = datetime.now(timezone.utc).isoformat()
    snap: dict = {"updated_at": now, **asdict(STATE)}
    try:
        from aegis.brain.ncp import hidden_state_vec
        snap["h"] = hidden_state_vec()
    except (ImportError, ModuleNotFoundError) as e:
        log.debug("orb snapshot: hidden_state_vec unavailable — %s", e)
        snap["h"] = []
    try:
        from aegis.renderer import _is_speaking as _spk
        snap["is_speaking"] = _spk
    except (ImportError, ModuleNotFoundError) as e:
        log.debug("orb snapshot: _is_speaking unavailable — %s", e)
        snap["is_speaking"] = False
    try:
        from aegis.mnemosyne.write import pop_last_event
        snap["mnemosyne_event"] = pop_last_event()
    except (ImportError, ModuleNotFoundError) as e:
        log.debug("orb snapshot: pop_last_event unavailable — %s", e)
        snap["mnemosyne_event"] = None
    return snap


async def run() -> None:
    log.info("neurobus running")
    tick_q = BUS.subscribe("tick")
    sense_q = BUS.subscribe("sensor.*")

    async def on_tick() -> None:
        while True:
            await tick_q.get()
            for f, rate in DECAY.items():
                setattr(STATE, f, getattr(STATE, f) * rate)
            STATE.clamp()
            await BUS.publish("neurobus.state", asdict(STATE))
            # Write the lightweight neurobus state file.
            try:
                now = datetime.now(timezone.utc).isoformat()
                atomic_write_json(
                    NEUROBUS_STATE_PATH,
                    {"updated_at": now, **asdict(STATE)},
                )
            except (OSError, ValueError, TypeError) as e:
                log.warning("neurobus: failed to write neurobus_state — %s", e)
            # Write the richer orb snapshot for the web server.
            try:
                orb_path = _orb_state_dir() / "orb_state.json"
                atomic_write_json(orb_path, _build_orb_snapshot())
            except (OSError, ValueError, TypeError) as e:
                log.warning("neurobus: failed to write orb_state — %s", e)

    async def on_sense() -> None:
        while True:
            msg = await sense_q.get()
            if msg.topic == "sensor.text":
                # any text input is novel + attention-grabbing
                STATE.novelty = min(1.0, STATE.novelty + 0.3)
                STATE.attention = min(1.0, STATE.attention + 0.2)
            STATE.clamp()

    await asyncio.gather(on_tick(), on_sense())
