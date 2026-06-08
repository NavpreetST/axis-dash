"""Forge — opencode dispatcher for Helios.

Manages an opencode server subprocess, submits coding tasks to isolated
sandbox workdirs, captures structured results (diffs/files/logs), and
runs a gate stage before any commit/push.
"""

from aegis.forge.dispatcher import ForgeDispatcher
from aegis.forge.gate import GateStage
from aegis.forge.manager import ForgeManager

__all__ = ["ForgeManager", "ForgeDispatcher", "GateStage"]
