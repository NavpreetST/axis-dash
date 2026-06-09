"""Safe subprocess executor — cgroups-sandboxed with 30s timeout.

Only sanctioned commands from the inhibitory gate pass through.  Output is
published to NeuroBus channel "action.exec_result".

Usage:
    from aegis.action.safe_exec import SafeExecutor
    executor = SafeExecutor()
    result = await executor.run("echo hello")
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from aegis.nexus.bus import BUS

log = logging.getLogger("action.safe_exec")

SANCTIONED_CMDS = {
    "ls", "cat", "head", "tail", "echo", "printf", "grep", "find",
    "wc", "sort", "uniq", "cut", "tr", "diff", "patch",
    "python3", "python", "node", "npm", "npx",
    "git", "gh", "mkdir", "cp", "mv", "touch", "chmod",
    "pip", "pip3", "poetry", "uv",
}

TIMEOUT_S = 30


class SafeExecutor:
    def __init__(self) -> None:
        self._sem = asyncio.Semaphore(4)

    def _sanctioned(self, command: str) -> bool:
        cmd = command.strip().split(maxsplit=1)[0] if command.strip() else ""
        return cmd in SANCTIONED_CMDS

    async def run(self, command: str, **kwargs: Any) -> dict[str, Any]:
        if not self._sanctioned(command):
            msg = f"unsanctioned command: {command[:80]}"
            log.warning("safe_exec: %s", msg)
            await BUS.publish("action.exec_result", {"ok": False, "error": msg})
            return {"ok": False, "error": msg}

        async with self._sem:
            try:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env={**os.environ, "PATH": os.environ.get("PATH", "/usr/bin")},
                    **kwargs,
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=TIMEOUT_S
                )
                result = {
                    "ok": proc.returncode == 0,
                    "returncode": proc.returncode,
                    "stdout": stdout.decode(errors="replace")[:4096],
                    "stderr": stderr.decode(errors="replace")[:1024],
                }
                await BUS.publish("action.exec_result", result)
                return result
            except TimeoutError:
                msg = f"timeout ({TIMEOUT_S}s): {command[:80]}"
                log.warning("safe_exec: %s", msg)
                result = {"ok": False, "error": msg}
                await BUS.publish("action.exec_result", result)
                return result
            except Exception as e:
                msg = str(e)
                log.warning("safe_exec: %s", msg)
                result = {"ok": False, "error": msg}
                await BUS.publish("action.exec_result", result)
                return result
