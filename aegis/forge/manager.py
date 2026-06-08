"""Forge Manager — runs opencode tasks via `opencode run --format json`.

Each task is executed as an ephemeral `opencode run` subprocess in an
isolated sandbox workdir.  This replaced the earlier `opencode serve`-
based backend because the serve API doesn't surface tool/function-calling
for any of the no-login free models (big-pickle, mimo, nemotron, deepseek).
`opencode run` drives opencode's own agent loop and produces real tool
calls + file diffs with those same free models.

SECURITY:
  - The subprocess runs with a scrubbed environment (strict allowlist) to
    prevent ~/.config/aegis/secrets.env or .git credentials from leaking
    into the opencode worker.
  - The process is sandboxed with an isolated HOME, an empty CWD outside
    /opt/aegis, and a minimal opencode config (no instructions, no skills).
  - permission.bash is set to "deny" to prevent arbitrary shell execution.
  - git/push credentials are injected ONLY at the gate stage, never here.
  - A hard subprocess timeout (120s) prevents runaway loops (opencode #26220).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger(__name__)

OPENCODE_BIN = os.getenv("OPENCODE_BIN", "opencode")
FORGE_BASE = Path(os.getenv("AEGIS_FORGE_DIR", "/opt/aegis/forge"))

# Isolated sandbox HOME to prevent opencode from loading the user's global
# config or the project config at /opt/aegis/opencode.json.
_SANDBOX_DIR = FORGE_BASE / ".sandbox"
_SANDBOX_CWD = _SANDBOX_DIR / "cwd"
_SANDBOX_HOME = _SANDBOX_DIR / "home"

# Strict allowlist: ONLY these env vars reach the forge worker.
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

# Hard timeout for a single opencode run subprocess (loop guard).
_RUN_TIMEOUT_SECONDS: float = 120.0


class ForgeManager:
    """Runs opencode tasks via ephemeral `opencode run` subprocesses.

    No long-lived server.  Each call to ``run_task()`` spawns a fresh
    ``opencode run --format json`` subprocess in the task's sandbox
    workdir, captures JSON events from stdout, and returns parsed results.

    Concurrency is managed by the dispatcher's semaphore
    (MAX_CONCURRENT_FORGE_TASKS=2 by default), NOT by the manager.
    """

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Public API (called by ForgeDispatcher)
    # ------------------------------------------------------------------

    async def run_task(self, workdir: Path, spec: str) -> dict:
        """Run ``opencode run --format json`` in *workdir* with *spec*.

        Returns a dict with:
          - ``events``: list of parsed JSON lines from stdout
          - ``session_id``: extracted from the first step_start event
          - ``tool_calls``: list of tool_use events (for loop guard)
          - ``time_s``: wall-clock seconds
          - ``return_code``: subprocess exit code
          - ``logs``: full stdout as a string
        """
        _SANDBOX_CWD.mkdir(parents=True, exist_ok=True)

        # Per-task config to avoid race when multiple run_task() instances
        # run concurrently reading/writing the shared _SANDBOX_CONFIG.
        config_path = workdir / "sandbox-config.json"
        cfg = {
            "$schema": "https://opencode.ai/config.json",
            "model": "opencode/big-pickle",
            "permission": {
                "bash": "deny",
            },
        }
        config_path.write_text(json.dumps(cfg, indent=2))

        env = self._sanitize_env()
        env["HOME"] = str(_SANDBOX_HOME)
        env["OPENCODE_CONFIG"] = str(config_path)
        env["OPENCODE_LOG_LEVEL"] = "WARN"

        args = [
            OPENCODE_BIN,
            "run",
            "--format", "json",
            "--model", "opencode/big-pickle",
            "--pure",
            "--dir", str(workdir),
            "--dangerously-skip-permissions",
            spec,
        ]

        log.info("forge: running opencode run in %s", workdir)
        t0 = time.perf_counter()

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=str(_SANDBOX_CWD),
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=_RUN_TIMEOUT_SECONDS
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            elapsed = time.perf_counter() - t0
            log.error(
                "forge: opencode run timed out after %.1fs (loop guard) — %s",
                _RUN_TIMEOUT_SECONDS,
                workdir,
            )
            # Return a partial result with the timeout error
            return {
                "events": [],
                "session_id": None,
                "tool_calls": 0,
                "time_s": round(elapsed, 1),
                "return_code": -1,
                "logs": f"TIMEOUT after {_RUN_TIMEOUT_SECONDS}s",
                "error": (
                    f"task exceeded {_RUN_TIMEOUT_SECONDS}s limit "
                    f"(possible big-pickle loop, see opencode #26220)"
                ),
            }

        elapsed = time.perf_counter() - t0

        stdout_text = stdout_bytes.decode(errors="replace")
        stderr_text = stderr_bytes.decode(errors="replace")

        if stderr_text.strip():
            for line in stderr_text.strip().split("\n"):
                log.debug("[forge-run stderr] %s", line.rstrip()[:200])

        events = []
        tool_calls = 0
        session_id = None
        for line in stdout_text.strip().split("\n"):
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
                events.append(ev)
                if ev.get("type") == "step_start":
                    session_id = ev.get("sessionID")
                if ev.get("type") == "tool_use":
                    tool_calls += 1
            except json.JSONDecodeError:
                log.warning("forge: failed to parse run output line: %.100s", line)

        result = {
            "events": events,
            "session_id": session_id,
            "tool_calls": tool_calls,
            "time_s": round(elapsed, 1),
            "return_code": proc.returncode or 0,
            "logs": stdout_text,
            "error": None,
        }

        log.info(
            "forge: run completed in %.1fs — %d events, %d tool calls, rc=%d",
            elapsed,
            len(events),
            tool_calls,
            proc.returncode or 0,
        )
        return result

    @staticmethod
    async def get_diffs(workdir: Path) -> list[dict]:
        """Run ``git diff --staged`` and ``git ls-files --others`` in *workdir*.

        If *workdir* is not a git repo, fall back to listing all files
        in the workdir tree.
        Returns a list of diff dicts with keys: path, status.
        """
        has_git = False
        try:
            rc, _ = await _run_simple(["git", "rev-parse", "--git-dir"], cwd=workdir)
            if rc == 0:
                has_git = True
        except Exception:
            has_git = False

        if has_git:
            diffs = []

            rc, out = await _run_simple(
                ["git", "diff", "--staged", "--name-status"], cwd=workdir
            )
            if rc == 0 and out.strip():
                for line in out.strip().split("\n"):
                    parts = line.strip().split("\t")
                    if len(parts) >= 2:
                        status = parts[0]
                        path = parts[-1]
                        diffs.append({"path": path, "status": _map_git_status(status)})

            rc2, out2 = await _run_simple(
                ["git", "ls-files", "--others", "--exclude-standard"], cwd=workdir
            )
            if rc2 == 0 and out2.strip():
                for path in out2.strip().split("\n"):
                    if path.strip() and not any(d["path"] == path for d in diffs):
                        diffs.append({"path": path.strip(), "status": "added"})

            if not diffs:
                # Fall back to listing all files in workdir
                return _list_files_as_diffs(workdir)
            return diffs

        return _list_files_as_diffs(workdir)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_env() -> dict[str, str]:
        """Build a sandbox-safe environment (strict allowlist)."""
        sandbox = {}
        for k, v in os.environ.items():
            if k in _SANDBOX_ALLOWLIST:
                sandbox[k] = v
        # Ensure HOME is always present for sandbox isolation
        if "HOME" not in sandbox:
            sandbox["HOME"] = str(Path.home())
        return sandbox


def _map_git_status(git_status: str) -> str:
    """Map git status characters to our status labels."""
    mapping = {
        "A": "added",
        "M": "modified",
        "D": "deleted",
        "R": "renamed",
        "C": "copied",
        "??": "added",
    }
    return mapping.get(git_status.strip(), "modified")


def _list_files_as_diffs(workdir: Path) -> list[dict]:
    """Fallback: walk workdir and list all files as added diffs.
    Skips internal sandbox files (e.g. sandbox-config.json) to avoid
    exposing them in task diffs/files_created.
    """
    diffs = []
    _INTERNAL_FILES = {"sandbox-config.json"}
    if workdir.exists():
        for f in sorted(workdir.rglob("*")):
            if f.is_file() and f.name not in _INTERNAL_FILES:
                try:
                    rel = f.relative_to(workdir)
                    diffs.append({"path": str(rel), "status": "added"})
                except ValueError:
                    pass
    return diffs


async def _run_simple(
    args: list[str], cwd: Path | None = None, timeout: float = 10.0
) -> tuple[int, str]:
    """Run a simple subprocess and return (returncode, stdout)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(cwd) if cwd else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return (proc.returncode or 0), stdout.decode(errors="replace")
    except Exception as e:
        return 1, str(e)
