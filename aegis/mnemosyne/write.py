"""Mnemosyne T1 — gated episode writes.

v1 gating policy:
- USER inputs are always stored (they're our ground truth).
- AEGIS replies are stored only if novelty + |reward| + threat > 0.3,
  so we don't bloat the DB with idle chatter.

Embeddings are stored as raw float32 blobs (4 bytes × 384 = 1.5 KB/row).
A year of dense chat at 100 turns/day = ~55 MB. Fine.
"""
import array
import asyncio
import json
import logging
import time

from aegis.nexus.bus import BUS
from aegis.nexus.neurobus import STATE as NEURO_STATE

from .db import CONN
from .t2_semantic import extract_facts, insert_batch

log = logging.getLogger("mnemosyne.write")

# B2/Orb: simple event queue for visual feedback.
_EVENT_QUEUE: list[dict] = []

def pop_last_event() -> dict | None:
    """Pop the oldest pending mnemosyne event, or None."""
    if _EVENT_QUEUE:
        return _EVENT_QUEUE.pop(0)
    return None
WRITE_THRESHOLD = 0.3


def _emb_blob(emb: list[float]) -> bytes:
    return array.array("f", emb).tobytes()


async def run() -> None:
    log.info("mnemosyne writer running")
    text_q  = BUS.subscribe("sensor.text")
    speak_q = BUS.subscribe("action.speak")
    last_emb: list[float] | None = None

    async def consume_text() -> None:
        nonlocal last_emb
        while True:
            msg = await text_q.get()
            last_emb = msg.payload["embedding"]
            CONN.execute(
                "INSERT INTO episodes (ts, text, embedding, neurobus, action) "
                "VALUES (?, ?, ?, ?, ?)",
                (time.time(),
                 f"USER: {msg.payload['text']}",
                 _emb_blob(last_emb),
                 json.dumps(NEURO_STATE.__dict__),
                 None),
            )
            CONN.commit()
            _EVENT_QUEUE.append({"tier": "T1", "op": "write", "ts": time.time()})
            try:
                user_text = msg.payload['text']
                facts = extract_facts(user_text, source=f"user_turn")
                if facts:
                    insert_batch(facts)
                    log.debug("t2: extracted %d facts", len(facts))
            except Exception:
                log.debug("t2: extraction failed", exc_info=True)
            log.debug("stored user turn")

    async def consume_speak() -> None:
        while True:
            msg = await speak_q.get()
            score = (NEURO_STATE.novelty
                     + abs(NEURO_STATE.reward)
                     + NEURO_STATE.threat)
            if score < WRITE_THRESHOLD or last_emb is None:
                continue
            emb = last_emb or [0.0] * 384
            CONN.execute(
                "INSERT INTO episodes (ts, text, embedding, neurobus, action) "
                "VALUES (?, ?, ?, ?, ?)",
                (time.time(),
                 f"AEGIS: {msg.payload['text']}",
                 _emb_blob(emb),
                 json.dumps(NEURO_STATE.__dict__),
                 "speak"),
            )
            CONN.commit()
            log.debug("stored aegis turn")

    await asyncio.gather(consume_text(), consume_speak())
