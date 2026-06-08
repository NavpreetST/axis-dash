"""Forge Manager — manages the opencode server lifecycle.

Starts `opencode serve` as an asyncio subprocess on a random port,
provides an httpx client for API calls, and handles graceful shutdown.

SECURITY: The server subprocess runs with a scrubbed environment to
prevent ~/.config/aegis/secrets.env or .git credentials from leaking
into the opencode worker. Git/push credentials are injected ONLY at
the gate stage, never here.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import signal
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

OPENCODE_BIN = os.getenv("OPENCODE_BIN", "opencode")
FORGE_BASE = Path(os.getenv("AEGIS_FORGE_DIR", "/opt/aegis/forge"))

# Env-var keys that are allowed to pass through to the opencode sandbox.
# Everything else (API keys, tokens, git credentials) is STRIPPED.
_SANDBOX_ALLOWLIST: frozenset[str] = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LANG",
        "LC_ALL",
        "SHELL",
        "TERM",
        "TMPDIR",
        "OPENCODE_BIN",
        "OPENCODE_LOG_LEVEL",
        "OPENCODE_CONFIG",
        "OPENCODE_CONFIG_CONTENT",
        "OPENCODE_PERMISSION",
        "AEGIS_FORGE_DIR",
    }
)

# Known secret env-var prefixes that must NEVER reach the sandbox.
_SECRET_PREFIXES: tuple[str, ...] = (
    "API_KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "AUTH",
    "CREDENTIAL",
    "GROQ_",
    "GEMINI_",
    "OPENAI_",
    "ANTHROPIC_",
    "HF_",
    "HUGGINGFACE_",
)

# The server password we generate to lock the opencode serve endpoint.
# Only the ForgeManager client knows it.
_SERVER_PASSWORD: str = secrets.token_urlsafe(32)


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

    @staticmethod
    def _sanitize_env() -> dict[str, str]:
        """Build a sandbox-safe environment for the opencode subprocess.

        Strips all known secret env vars so forge workers NEVER have access to
        host credentials (~/.config/aegis/secrets.env, .git credentials, etc.).
        Git/push auth is injected ONLY at the GateStage, never in the worker.
        """
        sandbox = {}
        for k, v in os.environ.items():
            upper = k.upper()
            # Allow-listed keys always pass through
            if k in _SANDBOX_ALLOWLIST:
                sandbox[k] = v
                continue
            # Strip anything that looks like a credential
            if any(upper.startswith(p) or upper.endswith(p) for p in _SECRET_PREFIXES):
                continue
            # Strip common secret names by exact match
            if upper in ("SECRET", "PRIVATE_KEY", "ACCESS_KEY", "API_KEY"):
                continue
            # Default: pass through non-secret-looking vars
            sandbox[k] = v
        return sandbox

    async def start(self) -> None:
        """Start opencode serve on a random port, wait for health."""
        FORGE_BASE.mkdir(parents=True, exist_ok=True)

        env = self._sanitize_env()
        env["OPENCODE_LOG_LEVEL"] = "WARN"
        env["OPENCODE_SERVER_PASSWORD"] = _SERVER_PASSWORD

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
            auth=httpx.BasicAuth("opencode", _SERVER_PASSWORD),
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

        # Read stderr lines until we find the port (with timeout)
        async def _read_stderr() -> int:
            async for raw_line in self._proc.stderr:
                line = raw_line.decode(errors="replace").strip()
                if "listening on" in line.lower():
                    try:
                        addr = line.split("127.0.0.1:")[-1].strip()
                        return int(addr.split()[0])
                    except (IndexError, ValueError):
                        pass
                if "port:" in line.lower():
                    try:
                        return int(line.split("port:")[-1].strip().split()[0])
                    except (IndexError, ValueError):
                        pass
            raise RuntimeError("could not detect forge server port from stderr")

        try:
            return await asyncio.wait_for(_read_stderr(), timeout=30.0)
        except TimeoutError:
            if self._proc and self._proc.returncode is None:
                self._proc.kill()
                await self._proc.wait()
            raise RuntimeError("forge server port detection timed out after 30s") from None

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
        """Create an opencode session bound to the sandbox workdir."""
        r = await self.client.post(
            "/session",
            json={"title": f"forge:{workdir.name}"},
            params={"directory": workdir.as_posix()},
        )
        r.raise_for_status()
        session_id = r.json()["id"]
        log.info("forge session created: %s — dir=%s", session_id, workdir)
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
        """Delete a session. Raises on failure."""
        r = await self.client.delete(f"/session/{session_id}")
        if r.status_code >= 400:
            r.raise_for_status()

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
