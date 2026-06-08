"""Forge Manager — manages the opencode server lifecycle.

Starts `opencode serve` as an asyncio subprocess on a random port,
provides an httpx client for API calls, and handles graceful shutdown.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

OPENCODE_BIN = os.getenv("OPENCODE_BIN", "opencode")
FORGE_BASE = Path(os.getenv("AEGIS_FORGE_DIR", "/opt/aegis/forge"))


class ForgeManager:
    """Long-lived manager for the opencode server subprocess."""

    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._port: int | None = None
        self._client: httpx.AsyncClient | None = None
        self._ready = asyncio.Event()

    @property
    def base_url(self) -> str:
        if self._port is None:
            raise RuntimeError("forge server not started")
        return f"http://127.0.0.1:{self._port}"

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("forge server not started")
        return self._client

    @property
    def is_ready(self) -> bool:
        return self._ready.is_set()

    async def start(self) -> None:
        """Start opencode serve on a random port, wait for health."""
        FORGE_BASE.mkdir(parents=True, exist_ok=True)

        # Use port 0 to let OS assign a free port
        env = os.environ.copy()
        env["OPENCODE_LOG_LEVEL"] = "WARN"

        self._proc = await asyncio.create_subprocess_exec(
            OPENCODE_BIN,
            "serve",
            "--port",
            "0",
            "--hostname",
            "127.0.0.1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        # Parse port from stderr (opencode prints it on startup)
        self._port = await self._detect_port()
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(300.0),  # tasks can be long
        )

        # Health check with retries
        for _attempt in range(20):
            try:
                r = await self._client.get("/global/health")
                if r.status_code == 200:
                    self._ready.set()
                    log.info("forge server ready on port %d", self._port)
                    return
            except (httpx.ConnectError, httpx.ReadTimeout):
                pass
            await asyncio.sleep(0.5)

        log.error("forge server failed to become ready")
        await self.stop()
        raise RuntimeError("forge server startup timeout")

    async def _detect_port(self) -> int:
        """Read port from opencode's stderr output."""
        if self._proc is None or self._proc.stderr is None:
            raise RuntimeError("no process stderr")

        # Read stderr lines until we find the port
        async for raw_line in self._proc.stderr:
            line = raw_line.decode(errors="replace").strip()
            # opencode prints: "Server listening on 127.0.0.1:PORT"
            if "listening on" in line.lower():
                # Extract port from line like "Server listening on 127.0.0.1:54321"
                try:
                    addr = line.split("127.0.0.1:")[-1].strip()
                    return int(addr.split()[0])
                except (IndexError, ValueError):
                    pass
            # Also handle: "port: 54321" format
            if "port:" in line.lower():
                try:
                    return int(line.split("port:")[-1].strip().split()[0])
                except (IndexError, ValueError):
                    pass

        raise RuntimeError("could not detect forge server port from stderr")

    async def stop(self) -> None:
        """Gracefully stop the opencode server."""
        if self._client:
            await self._client.aclose()
            self._client = None

        if self._proc and self._proc.returncode is None:
            self._proc.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except TimeoutError:
                self._proc.kill()
                await self._proc.wait()
            log.info("forge server stopped")

        self._proc = None
        self._port = None
        self._ready.clear()

    async def create_session(self, workdir: Path) -> str:
        """Create an opencode session, return session ID."""
        r = await self.client.post("/session", json={"title": f"forge:{workdir.name}"})
        r.raise_for_status()
        session_id = r.json()["id"]
        log.info("forge session created: %s", session_id)
        return session_id

    async def send_prompt(self, session_id: str, prompt: str) -> dict:
        """Send a prompt and wait for the full response."""
        r = await self.client.post(
            f"/session/{session_id}/message",
            json={"parts": [{"type": "text", "text": prompt}]},
        )
        r.raise_for_status()
        return r.json()

    async def get_diffs(self, session_id: str) -> list[dict]:
        """Fetch file diffs for a session."""
        r = await self.client.get(f"/session/{session_id}/diff")
        r.raise_for_status()
        return r.json()

    async def get_messages(self, session_id: str) -> list[dict]:
        """Fetch all messages for a session."""
        r = await self.client.get(f"/session/{session_id}/message")
        r.raise_for_status()
        return r.json()

    async def delete_session(self, session_id: str) -> None:
        """Delete a session."""
        await self.client.delete(f"/session/{session_id}")

    async def run_forever(self) -> None:
        """Keep the server alive; restart on crash."""
        while True:
            try:
                await self.start()
                await self._ready.wait()
                # Wait for process to exit (it shouldn't while healthy)
                if self._proc:
                    await self._proc.wait()
                log.warning("forge server exited, restarting in 2s...")
            except Exception as e:
                log.error("forge server error: %s", e)
            await self.stop()
            await asyncio.sleep(2.0)
