"""Basal-ganglia action selector — epsilon-greedy over 6 action types.

Reads NeuroBus state, computes a score for each action type, then selects
one via epsilon-greedy.  Publishes the selected action to a local Queue
for the executor to pick up.

Action types:
  shell_cmd          — run a shell command
  file_write         — write a file to disk
  notify             — send a notification
  query_knowledge    — query the knowledge DB
  render_response    — produce a text response
  null               — no-op (exploration / rest)

Usage:
    from aegis.action.basal_ganglia import ActionSelector
    selector = ActionSelector()
    action = await selector.select(state)
"""
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Any

from aegis.nexus.bus import BUS

log = logging.getLogger("action.basal_ganglia")

ACTION_TYPES = [
    "shell_cmd",
    "file_write",
    "notify",
    "query_knowledge",
    "render_response",
    "null",
]


@dataclass
class Action:
    action_type: str
    params: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0


class ActionSelector:
    def __init__(self, epsilon: float = 0.1, decay: float = 0.999) -> None:
        self.epsilon = epsilon
        self.decay = decay
        self._q: asyncio.Queue[Action] = asyncio.Queue(maxsize=16)

    def score(self, action_type: str, state: dict[str, float]) -> float:
        nu = state.get("novelty", 0.0)
        at = state.get("attention", 0.5)
        pa = state.get("patience", 0.5)
        re = state.get("reward", 0.0)

        scores = {
            "shell_cmd": 0.3 + at * 0.3 + re * 0.2,
            "file_write": 0.2 + at * 0.2 + nu * 0.2,
            "notify": 0.15 + nu * 0.25 + re * 0.1,
            "query_knowledge": 0.2 + pa * 0.2 + nu * 0.2,
            "render_response": 0.4 + at * 0.3 + re * 0.2,
            "null": 0.1 + pa * 0.1 - at * 0.05,
        }
        return max(0.0, min(1.0, scores.get(action_type, 0.0)))

    async def select(self, state: dict[str, float]) -> Action:
        if random.random() < self.epsilon:
            chosen = random.choice(ACTION_TYPES)
            log.debug("basal_ganglia: epsilon-explore -> %s", chosen)
            await self._emit_action(chosen)
            return Action(action_type=chosen)

        scored = [(at, self.score(at, state)) for at in ACTION_TYPES]
        scored.sort(key=lambda x: x[1], reverse=True)
        chosen = scored[0][0]
        log.debug("basal_ganglia: greedy -> %s (score=%.3f)", chosen, scored[0][1])
        await self._emit_action(chosen)
        self.epsilon = max(0.01, self.epsilon * self.decay)
        return Action(action_type=chosen, confidence=scored[0][1])

    async def _emit_action(self, action_type: str) -> None:
        await BUS.publish("action.selected", {"action_type": action_type})
