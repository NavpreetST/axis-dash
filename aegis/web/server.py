"""Orb Phase 0 — FastAPI WebSocket server for the JARVIS Neural Orb.

Serves static files from aegis/web/static/ and exposes /state at 1 Hz.
Reads daemon-written state from /var/lib/aegis by default.

P0 bridge endpoints (this file):
  GET  /health   liveness + daemon uptime + state-file freshness summary
  WS   /state    1 Hz state push (neurobus, h, renderer fields, connected, ...)
  WS   /chat     bridges to the daemon's unix socket (request/reply, 15 s)
  SSE  /logs     tails /var/lib/aegis/events/YYYY-MM-DD.jsonl

The bridge is a separate process from the daemon. It reads files only;
it does not import aegis.* runtime modules.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import re
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp

log = logging.getLogger("web.server")

# Ensure asyncio.open_unix_connection exists for testing (Windows lacks it)
if not hasattr(asyncio, "open_unix_connection"):
    async def _dummy_open_unix_connection(path: str, **kwargs) -> None:
        raise NotImplementedError("Unix sockets not supported on this platform")
    asyncio.open_unix_connection = _dummy_open_unix_connection

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATE_DIR = Path(os.getenv("AEGIS_STATE_DIR", "/var/lib/aegis"))
EVENTS_DIR = STATE_DIR / "events"
SOCK_PATH = Path(os.getenv("AEGIS_SOCK", "/tmp/aegis.sock"))

# State freshness: a snapshot is considered "live" if either its
# `updated_at` (preferred) or file mtime is within this many seconds of now.
STALE_THRESHOLD_SECONDS = 5.0

# Chat bridge mirrors aegis/main.py:REPLY_TIMEOUT default of 15.0 s.
CHAT_REPLY_TIMEOUT_SECONDS = 15.0

# SSE heartbeat so proxies / browsers don't kill the stream.
SSE_HEARTBEAT_SECONDS = 15.0

# tick_rate is a documented constant from aegis/nexus/clock.py:run(hz=1.0),
# invoked at aegis/main.py:87 as clock.run(hz=1.0). It is a source-of-truth
# constant, not a runtime measurement; if the daemon's clock is later
# reconfigured, the bridge must be updated in lockstep.
TICK_RATE_HZ = 1.0

# pam / coherence have no source in the runtime as of inspection
# (no match for 'pam' or 'coherence' under /opt/aegis/aegis,
# /opt/aegis/scripts, or /opt/aegis/contracts). The bridge emits null
# and does not derive from NeuroBus.
PAM_UNRESOLVED = None
COHERENCE_UNRESOLVED = None

# ---- Auth + CORS config ---------------------------------------------------

# Token read from env. Never hardcoded, never logged, never committed.
HELIOS_TOKEN: str | None = os.getenv("HELIOS_TOKEN") or None

# CORS allowlist: comma-separated env var. Default includes AXIS on Vercel
# (placeholder) and localhost:5173 for local dev. Override via env.
_DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:5173,"
    "https://axis-dash.vercel.app"
)
ALLOWED_ORIGINS: set[str] = {
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", _DEFAULT_ALLOWED_ORIGINS).split(",")
    if o.strip()
}

_PREVIEW_ORIGIN_PAT = re.compile(
    r"^https://axis-dash-[a-z0-9-]+-navpreets-projects\.vercel\.app$"
)


def _is_allowed_origin(origin: str | None) -> bool:
    if not origin:
        return False
    if origin in ALLOWED_ORIGINS:
        return True
    if _PREVIEW_ORIGIN_PAT.match(origin):
        return True
    return False


# WebSocket close codes (RFC 6455). 4401 = application-defined auth failure.
WS_CLOSE_APP_AUTH_FAILED = 4401


def _extract_bearer(header_val: str | None) -> str | None:
    if not header_val:
        return None
    parts = header_val.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def _token_matches(provided: str | None) -> bool:
    """Constant-time compare of provided token against HELIOS_TOKEN."""
    if not HELIOS_TOKEN or not provided:
        return False
    return hmac.compare_digest(provided, HELIOS_TOKEN)


def _check_token(request: HTTPConnection) -> bool:
    """Check token from Authorization: Bearer header OR ?token= query param.

    Accepts any HTTPConnection (Request or WebSocket) since both expose
    .headers and .query_params.
    Returns True if the token matches HELIOS_TOKEN. False if missing or wrong.
    Does not raise; callers decide how to respond.
    """
    bearer = _extract_bearer(request.headers.get("authorization"))
    query_token = request.query_params.get("token")
    return _token_matches(bearer) or _token_matches(query_token)


def _first_str(*candidates: Any, default: str = "") -> str:
    """Return the first candidate that is a non-None string, else default.

    Avoids the `or` chain pitfall where falsy strings ("") or 0 are dropped.
    """
    for c in candidates:
        if c is not None:
            return str(c)
    return default


# ---- CORS middleware (explicit allowlist) ---------------------------------


class CORSMiddleware(BaseHTTPMiddleware):
    """Explicit-origin CORS. Reflects the request Origin if it's in the
    allowlist; never uses "*" because auth is involved (credentials mode)."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request, call_next):
        origin = request.headers.get("origin")
        # Reflect origin only if it's in the allowlist or matches preview pattern; else omit the header.
        allow_origin = origin if _is_allowed_origin(origin) else None

        if request.method == "OPTIONS":
            # Preflight: respond with CORS headers and 204.
            resp = StreamingResponse(iter([]), status_code=204)
        else:
            resp = await call_next(request)

        if allow_origin:
            resp.headers["Access-Control-Allow-Origin"] = allow_origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = (
                "Authorization, Content-Type"
            )
            resp.headers["Access-Control-Max-Age"] = "600"
        return resp


app = FastAPI(title="Helios Orb", docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        log.warning("bad json in %s: %s", path, e)
        return {}
    except OSError as e:
        log.warning("could not read %s: %s", path, e)
        return {}


def _float(value: Any, default: float) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default

    if x != x or x in (float("inf"), float("-inf")):
        return default

    return x


def _clamp_neg1_pos1(x: float) -> float:
    return max(-1.0, min(1.0, x))


def _alive_default(value: Any, default: float) -> float:
    """Use default when a scalar is effectively uninitialized.

    This prevents the orb from going visually dead when daemon files contain
    tiny underflow values like 1e-54 for attention/patience/trust.
    """
    x = _float(value, default)
    if abs(x) < 1e-6:
        return default
    return _clamp_neg1_pos1(x)


def _plain_scalar(value: Any, default: float) -> float:
    return _clamp_neg1_pos1(_float(value, default))


def _trust_default(value: Any) -> float:
    x = _float(value, 0.5)
    if x < 0.05:
        return 0.5
    return _clamp_neg1_pos1(x)


def _neurobus_from(obj: dict[str, Any]) -> dict[str, float]:
    return {
        "reward": _plain_scalar(obj.get("reward"), 0.0),
        "novelty": _plain_scalar(obj.get("novelty"), 0.0),
        "attention": _alive_default(obj.get("attention"), 0.5),
        "patience": _alive_default(obj.get("patience"), 0.5),
        "threat": _plain_scalar(obj.get("threat"), 0.0),
        "trust": _trust_default(obj.get("trust")),
    }


# ---- P0 bridge: state-file metadata, freshness, daemon introspection -----


def _parse_iso(ts: str | None) -> float | None:
    """Parse an ISO-8601 timestamp to epoch seconds, or None on failure."""
    if not ts or not isinstance(ts, str):
        return None
    try:
        s = ts.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).timestamp()
    except (TypeError, ValueError):
        return None


def _load_state_meta(name: str) -> dict[str, Any]:
    """Read a state file and return its parsed JSON plus freshness metadata.

    Returned shape:
      {
        "data": dict,            # parsed JSON, {} on any failure
        "exists": bool,
        "updated_at": str|None,  # ISO timestamp from the payload, if any
        "updated_epoch": float|None,
        "mtime_epoch": float|None,
        "age_seconds": float|None,
      }
    """
    path = STATE_DIR / name
    out: dict[str, Any] = {
        "data": {},
        "exists": False,
        "updated_at": None,
        "updated_epoch": None,
        "mtime_epoch": None,
        "age_seconds": None,
    }
    if not path.exists():
        return out
    out["exists"] = True
    try:
        out["mtime_epoch"] = path.stat().st_mtime
    except OSError as e:
        log.warning("stat failed on %s: %s", path, e)
    out["data"] = _load_json(path)
    out["updated_at"] = out["data"].get("updated_at")
    out["updated_epoch"] = _parse_iso(out["updated_at"])
    ref = out["updated_epoch"] if out["updated_epoch"] is not None else out["mtime_epoch"]
    if ref is not None:
        out["age_seconds"] = max(0.0, time.time() - ref)
    return out


def _renderer_from(obj: dict[str, Any]) -> dict[str, Any]:
    """Extract provider / rpd_used / rpd_budget from renderer_state.json.

    Returns None for each missing/unreadable field rather than guessing.
    """
    last_success = obj.get("last_success") or {}
    providers = obj.get("providers") or {}
    gemini = providers.get("gemini") or {}
    provider = last_success.get("provider") if isinstance(last_success, dict) else None
    rpd_used = gemini.get("local_daily_used") if isinstance(gemini, dict) else None
    rpd_budget = gemini.get("local_daily_budget") if isinstance(gemini, dict) else None
    return {
        "provider": provider if isinstance(provider, str) else None,
        "rpd_used": int(rpd_used) if isinstance(rpd_used, (int, float)) else None,
        "rpd_budget": int(rpd_budget) if isinstance(rpd_budget, (int, float)) else None,
    }


def _is_fresh(meta: dict[str, Any]) -> bool:
    return (
        meta.get("exists")
        and meta.get("age_seconds") is not None
        and meta["age_seconds"] <= STALE_THRESHOLD_SECONDS
    )


def _connected(orb_meta: dict[str, Any], rend_meta: dict[str, Any]) -> bool:
    """Connected = both state files exist, parse, and are within the
    staleness threshold (5 s via `updated_at`, else file mtime)."""
    return _is_fresh(orb_meta) and _is_fresh(rend_meta)


_DAEMON_CMDLINE_NEEDLES = ("aegis.main", "aegis\\main")


def _find_daemon_pid() -> int | None:
    """Find the PID of `python -m aegis.main` by walking /proc.

    No subprocess, no ps, no extra deps. /proc is always available on Linux.
    """
    needle_variants = list(_DAEMON_CMDLINE_NEEDLES)
    try:
        proc_root = Path("/proc")
        for entry in proc_root.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                cmdline = (entry / "cmdline").read_bytes().decode(
                    "utf-8", errors="replace"
                )
            except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
                continue
            cmdline_norm = cmdline.replace("\x00", " ")
            if any(n in cmdline_norm for n in needle_variants):
                try:
                    return int(entry.name)
                except ValueError:
                    continue
    except OSError as e:
        log.warning("scanning /proc for daemon pid failed: %s", e)
    return None


def _read_proc_starttime(pid: int) -> int | None:
    """Field 22 of /proc/<pid>/stat is starttime in clock ticks since boot.

    The comm field can contain spaces and parens, so split on the last ')'.
    """
    try:
        text = (Path("/proc") / str(pid) / "stat").read_text()
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return None
    rpar = text.rfind(")")
    if rpar < 0 or rpar + 2 >= len(text):
        return None
    fields = text[rpar + 2:].split()
    # fields[0] is state, fields[1] is ppid, ... fields[19] is starttime.
    if len(fields) < 20:
        return None
    try:
        return int(fields[19])
    except ValueError:
        return None


def _daemon_uptime_seconds() -> int | None:
    """Compute daemon uptime. Convenience wrapper: finds the PID first."""
    return _daemon_uptime_seconds_for_pid(_find_daemon_pid())


def _daemon_uptime_seconds_for_pid(pid: int | None) -> int | None:
    """Compute daemon uptime in whole seconds for a known PID.

    Source: /proc/<pid>/stat field 22 (starttime, in clock ticks since boot)
    and /proc/uptime (seconds since boot). No runtime changes required.

    Returns None if pid is None, or /proc is unreadable.
    """
    if pid is None:
        return None
    start_ticks = _read_proc_starttime(pid)
    if start_ticks is None:
        return None
    try:
        uptime_str = Path("/proc/uptime").read_text().split()[0]
        boot_seconds = float(uptime_str)
    except (FileNotFoundError, ValueError, IndexError, OSError):
        return None
    try:
        clk_tck = os.sysconf("SC_CLK_TCK")
    except (ValueError, OSError):
        clk_tck = 100
    if not clk_tck or clk_tck <= 0:
        clk_tck = 100
    start_since_boot = start_ticks / clk_tck
    # Capture time.time() once so wall_start and elapsed are consistent
    # (avoids microsecond drift between the two reads).
    now = time.time()
    wall_start = now - (boot_seconds - start_since_boot)
    elapsed = now - wall_start
    if elapsed < 0:
        return None
    return int(elapsed)


# ---- Phase 3 (P1): runtime-truth / drift-watchdog -----------------------

import subprocess as _subprocess

# Cached at first call — commit and socket path are stable for the
# bridge's lifetime. State-dependent fields are recomputed each call.
_RUNTIME_CACHE: dict | None = None

# NCP dims are a documented constant from the daemon startup log
# (aegis/main.py logs "ncp brain online; params=41361"). The hidden
# state size is 64 per the orb_state.json shape.
NCP_PARAMS = 41361
NCP_HIDDEN_SIZE = 64

# Repo path for git rev lookup. Override via env for portable config.
_REPO_DIR = os.getenv("AEGIS_REPO_DIR", "/opt/aegis")

# Memory backend path per README §Architecture.
_MEMORY_DB = Path(
    os.getenv("AEGIS_MEMORY_DB", str(Path.home() / ".local/share/aegis/mnemosyne.db"))
)


def _git_short_commit() -> str | None:
    """Return the short git commit hash, or None on failure.

    Resolution order:
      1. AEGIS_COMMIT env var  (set by deploy script / CI)
      2. git rev-parse --short HEAD  (development boxes)
    """
    env_commit = os.getenv("AEGIS_COMMIT")
    if env_commit:
        return env_commit.strip()[:40] or None
    try:
        out = _subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_REPO_DIR,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if out.returncode == 0:
            return out.stdout.strip() or None
    except (FileNotFoundError, _subprocess.TimeoutExpired, OSError):
        pass
    return None


def _detect_launch_method(pid: int | None) -> str:
    """Detect daemon launch method from /proc/<pid>/cgroup.

    Distinguishes systemd services (/system.slice/) from user-session /
    nohup processes (/user.slice/).  Returns "nohup" as the default when
    the daemon is alive but not under systemd — the expected Phase 0/1
    deployment pattern.

    PPID-based heuristics are unreliable because nohup orphans are
    reparented to init (PID 1), producing false-positive "systemd" labels.
    """
    if pid is None:
        return "unknown"
    try:
        with open(f"/proc/{pid}/cgroup") as f:
            cgroup = f.read()
        if "system.slice" in cgroup:
            return "systemd"
    except OSError:
        pass
    return "nohup"


def _renderer_chain(rend_data: dict) -> list[str]:
    """Extract renderer chain order from renderer_state.json.

    Prefers the explicit `chain` field; falls back to provider keys sorted.
    """
    chain = rend_data.get("chain")
    if isinstance(chain, list) and chain:
        return [str(p) for p in chain if isinstance(p, str)]
    providers = rend_data.get("providers") or {}
    if isinstance(providers, dict) and providers:
        return sorted(providers.keys())
    return []


def _budget(rend_data: dict) -> dict:
    """Extract per-provider daily budget from renderer_state.json."""
    providers = rend_data.get("providers") or {}
    if not isinstance(providers, dict):
        return {}
    out = {}
    for name, cfg in providers.items():
        if not isinstance(cfg, dict):
            continue
        used = cfg.get("local_daily_used")
        budget = cfg.get("local_daily_budget")
        if used is not None or budget is not None:
            out[name] = {
                "used": int(used) if isinstance(used, (int, float)) else None,
                "budget": int(budget) if isinstance(budget, (int, float)) else None,
                "window": cfg.get("quota_window"),
            }
    return out


def _known_issues(
    orb_meta: dict, rend_meta: dict, daemon_pid: int | None
) -> list[str]:
    """Dynamic drift detection. Empty list = no known issues.

    Each issue is a short tag like "state_stale:orb_state.json".
    """
    issues: list[str] = []

    # State file freshness
    if not orb_meta.get("exists"):
        issues.append("state_missing:orb_state.json")
    elif orb_meta.get("age_seconds") is not None and orb_meta["age_seconds"] > STALE_THRESHOLD_SECONDS:
        issues.append("state_stale:orb_state.json")

    if not rend_meta.get("exists"):
        issues.append("state_missing:renderer_state.json")
    elif rend_meta.get("age_seconds") is not None and rend_meta["age_seconds"] > STALE_THRESHOLD_SECONDS:
        issues.append("state_stale:renderer_state.json")

    # Socket staleness: file exists but daemon not running
    try:
        sock_exists = SOCK_PATH.exists()
    except OSError:
        sock_exists = False
    if sock_exists and daemon_pid is None:
        issues.append(f"socket_orphaned:{SOCK_PATH.name}")

    # Token not configured
    if not HELIOS_TOKEN:
        issues.append("token_unset:HELIOS_TOKEN")

    # Memory DB missing
    if not _MEMORY_DB.exists():
        issues.append(f"memory_db_missing:{_MEMORY_DB.name}")

    return issues


def _runtime_meta(orb_meta: dict, rend_meta: dict, daemon_pid: int | None) -> dict:
    """Build the runtime meta block for /state and /health.

    Cached on first call for stable fields (commit, socket_path).
    State-dependent fields (known_issues, budget) are precomputed and passed.
    """
    global _RUNTIME_CACHE
    if _RUNTIME_CACHE is None:
        _RUNTIME_CACHE = {
            "commit": _git_short_commit(),
            "socket_path": str(SOCK_PATH),
        }

    rend_data = rend_meta["data"]

    meta = dict(_RUNTIME_CACHE)  # shallow copy
    meta["launch_method"] = _detect_launch_method(daemon_pid)
    meta["renderer_chain"] = _renderer_chain(rend_data)
    meta["memory_backend"] = {
        "type": "sqlite",
        "path": _MEMORY_DB.name,
        "exists": _MEMORY_DB.exists(),
    }
    meta["ncp"] = {
        "params": NCP_PARAMS,
        "hidden_size": NCP_HIDDEN_SIZE,
    }
    meta["budget"] = _budget(rend_data)
    meta["known_issues"] = _known_issues(orb_meta, rend_meta, daemon_pid)

    return meta


def _build_state() -> dict[str, Any]:
    orb_meta = _load_state_meta("orb_state.json")
    rend_meta = _load_state_meta("renderer_state.json")
    neuro_file = _load_json(STATE_DIR / "neurobus_state.json")
    daemon_pid = _find_daemon_pid()

    orb = orb_meta["data"]

    if isinstance(orb.get("neurobus"), dict):
        neurobus = _neurobus_from(orb["neurobus"])
    elif orb:
        neurobus = _neurobus_from(orb)
    else:
        neurobus = _neurobus_from(neuro_file)

    h = orb.get("h", [])
    if not isinstance(h, list):
        h = []
    h = h[:64]

    renderer = _renderer_from(rend_meta["data"])

    return {
        "neurobus": neurobus,
        "h": h,
        "is_speaking": bool(orb.get("is_speaking", False)),
        "last_action_type": _first_str(
            orb.get("last_action_type"), orb.get("action_type"), default="idle"
        ),
        "tick_id": int(_float(orb.get("tick_id"), 0)),
        "mnemosyne_event": orb.get("mnemosyne_event"),
        "provider": renderer["provider"],
        "rpd_used": renderer["rpd_used"],
        "rpd_budget": renderer["rpd_budget"],
        "connected": _connected(orb_meta, rend_meta),
        "uptime_seconds": _daemon_uptime_seconds_for_pid(daemon_pid),
        "tick_rate": TICK_RATE_HZ,
        "pam": PAM_UNRESOLVED,
        "coherence": COHERENCE_UNRESOLVED,
        "runtime": _runtime_meta(orb_meta, rend_meta, daemon_pid),
    }


# ---- P0 bridge: /state (WS, auth via header or ?token=) -------------------


@app.websocket("/state")
async def state_ws(ws: WebSocket) -> None:
    # Auth check before accept. Check both Authorization header and ?token=.
    if not _check_token(ws):
        # Accept then close with app-defined auth code so the client sees
        # a proper WebSocket close (4401) instead of an opaque HTTP 403.
        await ws.accept()
        await ws.close(code=WS_CLOSE_APP_AUTH_FAILED, reason="auth_failed")
        return
    await ws.accept()
    # Check WS origin against allowlist (BaseHTTPMiddleware doesn't run on WS upgrades)
    origin = ws.headers.get("origin")
    if origin and not _is_allowed_origin(origin):
        log.warning("state ws origin rejected: %s", origin)
        await ws.close(code=WS_CLOSE_APP_AUTH_FAILED, reason="origin_not_allowed")
        return
    log.info("orb /state connected")
    try:
        while True:
            await ws.send_text(json.dumps(_build_state(), default=str))
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        log.info("orb /state disconnected")
    except Exception as e:
        log.warning("orb /state error: %s", e)


# ---- P0 bridge: /health (Bearer header only) ------------------------------


@app.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """Lightweight liveness + daemon introspection.

    Always 200; `ok` is true iff the bridge is running. `connected` reflects
    state-file freshness (see STALE_THRESHOLD_SECONDS).

    Auth: Authorization: Bearer <HELIOS_TOKEN> header only. Query-param
    token is NOT accepted on /health (keeps the public health check simple).
    """
    if not _token_matches(_extract_bearer(request.headers.get("authorization"))):
        raise HTTPException(status_code=401, detail="auth_required")
    orb_meta = _load_state_meta("orb_state.json")
    rend_meta = _load_state_meta("renderer_state.json")
    # Compute daemon pid once and thread through to uptime so the two
    # fields in the response are always consistent (avoids TOCTOU between
    # the two /proc scans).
    daemon_pid = _find_daemon_pid()
    return {
        "ok": True,
        "daemon_pid": daemon_pid,
        "uptime_seconds": _daemon_uptime_seconds_for_pid(daemon_pid),
        "connected": _connected(orb_meta, rend_meta),
        "state_files": {
            "orb_state.json": {
                "exists": orb_meta["exists"],
                "updated_at": orb_meta["updated_at"],
                "age_seconds": orb_meta["age_seconds"],
            },
            "renderer_state.json": {
                "exists": rend_meta["exists"],
                "updated_at": rend_meta["updated_at"],
                "age_seconds": rend_meta["age_seconds"],
            },
        },
        "tick_rate": TICK_RATE_HZ,
        "pam": PAM_UNRESOLVED,
        "coherence": COHERENCE_UNRESOLVED,
        # Phase 3 (P1): runtime-truth / drift-watchdog. Same shape as
        # the /state runtime field for consistency.
        "runtime": _runtime_meta(orb_meta, rend_meta, daemon_pid),
    }


# ---- P0 bridge: /chat (WS, auth via header or ?token=) --------------------

# ---- Forge HTTP proxy routes (additive) -----------------------------------

_TASK_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]{1,128}$")

def _sanitize_field(value: str, name: str = "field") -> str:
    """Strip CR/LF, reject empty."""
    sanitized = value.strip().replace("\r", "").replace("\n", "")
    if not sanitized:
        raise HTTPException(status_code=400, detail=f"invalid_{name}")
    return sanitized


def _sanitize_task_id(task_id: str) -> str:
    """Strip CR/LF and validate task_id pattern."""
    sanitized = _sanitize_field(task_id, "task_id")
    if not _TASK_ID_PATTERN.match(sanitized):
        raise HTTPException(status_code=400, detail="invalid_task_id")
    return sanitized


async def _forge_socket_cmd(command: str) -> str:
    """Send a single command to the forge unix socket and return the response.
    Returns the raw response string without trailing newline. Raises HTTPException on socket errors.
    """
    # Use getattr to allow patching in tests on platforms lacking open_unix_connection
    open_conn = getattr(asyncio, "open_unix_connection", None)
    if open_conn is None:
        raise HTTPException(status_code=501, detail="unix_socket_not_supported")
    try:
        reader, writer = await open_conn(str(SOCK_PATH), limit=262144)
    except (FileNotFoundError, ConnectionRefusedError, PermissionError, OSError) as e:
        log.warning("forge proxy socket open failed: %s", e)
        raise HTTPException(status_code=503, detail="forge_socket_unavailable")
    try:
        writer.write((command + "\n").encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=15.0)
        resp = line.decode(errors="replace").strip()
        return resp
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="forge_socket_timeout")
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


@app.post("/forge/submit")
async def forge_submit(request: Request) -> dict:
    """Submit a forge task spec. Requires auth token."""
    if not _check_token(request):
        raise HTTPException(status_code=401, detail="auth_required")
    body = await request.json()
    spec = body.get("spec") if isinstance(body, dict) else None
    if not isinstance(spec, str) or len(spec.strip()) < 10:
        raise HTTPException(status_code=400, detail="invalid_spec")
    spec_safe = _sanitize_field(spec, "spec")
    resp = await _forge_socket_cmd(f"FORGE:SUBMIT:{spec_safe}")
    # Expected response: FORGE:OK:<id> or FORGE:ERR:...
    if resp.startswith("FORGE:OK:"):
        return {"task_id": resp.split(":", 2)[2]}
    else:
        raise HTTPException(status_code=502, detail=resp)


@app.get("/forge/list")
async def forge_list(request: Request) -> dict:
    """List active forge tasks via FORGE:LIST socket command. Requires auth token."""
    if not _check_token(request):
        raise HTTPException(status_code=401, detail="auth_required")
    resp = await _forge_socket_cmd("FORGE:LIST")
    if resp.startswith("FORGE:LIST:"):
        payload = resp.split(":", 2)[2]
        try:
            return {"tasks": json.loads(payload)}
        except json.JSONDecodeError:
            raise HTTPException(status_code=502, detail="malformed_response")
    else:
        raise HTTPException(status_code=502, detail=resp)


@app.get("/forge/{task_id}/status")
async def forge_status(task_id: str, request: Request) -> dict:
    """Poll forge task status via FORGE:POLL socket command. Requires auth token."""
    if not _check_token(request):
        raise HTTPException(status_code=401, detail="auth_required")
    tid = _sanitize_task_id(task_id)
    resp = await _forge_socket_cmd(f"FORGE:POLL:{tid}")
    if resp.startswith("FORGE:STATUS:"):
        payload = resp.split(":", 2)[2]
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            raise HTTPException(status_code=502, detail="malformed_response")
    else:
        raise HTTPException(status_code=502, detail=resp)


@app.get("/forge/{task_id}/diff")
async def forge_diff(task_id: str, request: Request) -> dict:
    """Fetch forge task diff via FORGE:FETCH socket command. Requires auth token."""
    if not _check_token(request):
        raise HTTPException(status_code=401, detail="auth_required")
    tid = _sanitize_task_id(task_id)
    resp = await _forge_socket_cmd(f"FORGE:FETCH:{tid}")
    if resp.startswith("FORGE:RESULT:"):
        payload = resp.split(":", 2)[2]
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            raise HTTPException(status_code=502, detail="malformed_response")
    else:
        raise HTTPException(status_code=502, detail=resp)


@app.post("/forge/{task_id}/gate")
async def forge_gate(task_id: str, request: Request) -> dict:
    """Approve forge task gate. Requires auth token and approve=True."""
    if not _check_token(request):
        raise HTTPException(status_code=401, detail="auth_required")
    tid = _sanitize_task_id(task_id)
    try:
        body = await request.json()
    except Exception:
        body = {}
    approve = body.get("approve") if isinstance(body, dict) else None
    if approve is not True:
        raise HTTPException(status_code=400, detail="approval_required")
    resp = await _forge_socket_cmd(f"FORGE:GATE:{tid}")
    if resp.startswith("FORGE:GATE:"):
        payload = resp.split(":", 2)[2]
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            raise HTTPException(status_code=502, detail="malformed_response")
    else:
        raise HTTPException(status_code=502, detail=resp)


@app.post("/forge/{task_id}/cleanup")
async def forge_cleanup(task_id: str, request: Request) -> dict:
    """Cleanup forge task sandbox. Requires auth token."""
    if not _check_token(request):
        raise HTTPException(status_code=401, detail="auth_required")
    tid = _sanitize_task_id(task_id)
    resp = await _forge_socket_cmd(f"FORGE:CLEANUP:{tid}")
    if resp.startswith("FORGE:OK:"):
        return {"result": resp}
    else:
        raise HTTPException(status_code=502, detail=resp)


@app.websocket("/chat")
async def chat_ws(ws: WebSocket) -> None:
    """Bridge a browser WS to the daemon's unix socket (request/reply).

    Protocol (per aegis/main.py:serve_unix_socket):
      - one text frame from client = one line sent to the socket
      - one line read from the socket = one text frame sent to the client
      - REPLY_TIMEOUT default is 15 s (aegis/main.py:36)

    The bridge never invents a reply. On socket error / timeout / disconnect
    it sends a structured JSON error frame and closes.

    Auth: Authorization: Bearer <HELIOS_TOKEN> header OR ?token=<HELIOS_TOKEN>
    query param. Browsers can't set Authorization on WS, so query-param is
    the primary path for AXIS.
    """
    if not _check_token(ws):
        # Accept then close with app-defined auth code so the client sees
        # a proper WebSocket close (4401) instead of an opaque HTTP 403.
        await ws.accept()
        await ws.close(code=WS_CLOSE_APP_AUTH_FAILED, reason="auth_failed")
        return

    await ws.accept()

    # Check WS origin against allowlist (BaseHTTPMiddleware doesn't run on WS upgrades)
    origin = ws.headers.get("origin")
    if origin and not _is_allowed_origin(origin):
        log.warning("chat ws origin rejected: %s", origin)
        await ws.close(code=WS_CLOSE_APP_AUTH_FAILED, reason="origin_not_allowed")
        return

    # No pre-check on SOCK_PATH.exists() — rely on the try/except below
    # to handle TOCTOU races (daemon restart between check and connect).
    try:
        reader, writer = await asyncio.open_unix_connection(str(SOCK_PATH))
    except (FileNotFoundError, ConnectionRefusedError, PermissionError, OSError) as e:
        log.warning("chat socket open failed: %s", e)
        await ws.send_text(json.dumps({
            "error": "socket_unavailable",
            "sock": str(SOCK_PATH),
            "detail": str(e),
        }))
        await ws.close()
        return

    log.info("orb /chat connected -> %s", SOCK_PATH)
    try:
        while True:
            try:
                msg = await ws.receive_text()
            except WebSocketDisconnect:
                break
            if not msg:
                continue
            try:
                writer.write((msg + "\n").encode("utf-8"))
                await writer.drain()
            except (ConnectionResetError, BrokenPipeError, OSError) as e:
                await ws.send_text(json.dumps({
                    "error": "socket_write_failed",
                    "detail": str(e),
                }))
                break
            try:
                line = await asyncio.wait_for(
                    reader.readline(), timeout=CHAT_REPLY_TIMEOUT_SECONDS
                )
            except TimeoutError:
                await ws.send_text(json.dumps({
                    "error": "reply_timeout",
                    "timeout_seconds": CHAT_REPLY_TIMEOUT_SECONDS,
                }))
                continue
            if not line:
                await ws.send_text(json.dumps({
                    "error": "socket_closed_by_daemon",
                }))
                break
            await ws.send_text(line.decode("utf-8", errors="replace").rstrip("\n"))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.warning("orb /chat error: %s", e)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        log.info("orb /chat disconnected")


# ---- P0 bridge: /logs (SSE, auth via header or ?token=) -------------------


def _today_eventlog_path() -> Path:
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    return EVENTS_DIR / f"{day}.jsonl"


async def _tail_eventlog():
    """Async generator: yield parsed event dicts as they are appended.

    Handles UTC day rollover (re-opens the new day's file) and partial last
    lines (buffers until newline). Invalid JSON lines are skipped with a
    warn log; the bridge never fabricates events.
    """
    f = None
    path = None
    buf = ""
    last_heartbeat = time.monotonic()
    while True:
        if f is None or path != _today_eventlog_path():
            if f is not None:
                try:
                    f.close()
                except OSError:
                    pass
            path = _today_eventlog_path()
            try:
                # Run blocking mkdir + open in thread to avoid blocking the event loop
                def _open_log() -> object | None:
                    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
                    return open(path, encoding="utf-8", errors="replace")
                f = await asyncio.to_thread(_open_log)
            except FileNotFoundError:
                f = None
            except OSError as e:
                log.warning("logs: open %s failed: %s", path, e)
                f = None
        if f is None:
            await asyncio.sleep(0.5)
            continue
        # Run blocking read in thread to avoid blocking the event loop
        try:
            chunk = await asyncio.to_thread(f.read)
        except OSError as e:
            log.warning("logs: read %s failed: %s", path, e)
            f = None
            continue
        if not chunk:
            # heartbeat
            now = time.monotonic()
            if now - last_heartbeat >= SSE_HEARTBEAT_SECONDS:
                yield {"_heartbeat": True, "ts": time.time()}
                last_heartbeat = now
            await asyncio.sleep(0.5)
            continue
        buf += chunk
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError as e:
                log.warning("logs: bad json line in %s: %s", path, e)
                continue
            if not isinstance(evt, dict):
                log.warning("logs: non-object event in %s", path)
                continue
            yield evt
        last_heartbeat = time.monotonic()


@app.get("/logs")
async def logs_sse(request: Request) -> StreamingResponse:
    """Server-Sent Events stream of /var/lib/aegis/events/YYYY-MM-DD.jsonl.

    Auth: Authorization: Bearer <HELIOS_TOKEN> header OR ?token=<HELIOS_TOKEN>
    query param. EventSource can't set Authorization headers, so query-param
    is the primary path for AXIS.
    """
    if not _check_token(request):
        raise HTTPException(status_code=401, detail="auth_required")

    async def event_stream():
        # Yield an initial comment to flush headers immediately.
        # EventSource / browser needs the response headers right away.
        yield ": connected\n\n"
        async for evt in _tail_eventlog():
            # Check for client disconnect so we don't leak the generator
            # when the browser closes the EventSource without a new event.
            if await request.is_disconnected():
                return
            if evt.get("_heartbeat"):
                yield ": heartbeat\n\n"
                continue
            yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---- Coordination memory / conversation endpoints (Phase 3, P2) ------------
#
# Read-only access to the Mnemosyne episode store and the Knowledge DB
# (MiniLM embeddings + FTS5).  Both are SQLite databases on the box.

_KNOWLEDGE_DB = Path(os.getenv("AEGIS_KNOWLEDGE_DB", "/opt/aegis/knowledge/helios_knowledge.db"))
_CONVERSATION_GAP_SECONDS = 900  # 15 min gap between episodes = new conversation

# Whitelist of table/column identifiers allowed in SQL interpolation.
# Any name not in these sets will be rejected (defence-in-depth against
# accidental injection through the _search_knowledge helper).
_KNOWLEDGE_TABLES: frozenset[str] = frozenset({
    "facts", "concepts", "research_questions",
    "facts_fts", "concepts_fts", "research_questions_fts",
})
_KNOWLEDGE_COLUMNS: frozenset[str] = frozenset({
    "id", "name", "category", "content", "source_page", "status",
    "type", "summary", "source_pages", "dependencies", "embedding",
    "question", "avenue", "priority",
})


def _db_connect(db_path: Path) -> sqlite3.Connection | None:
    """Open a read-only SQLite connection, or None on failure."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except (sqlite3.Error, OSError):
        return None


def _load_conversation_groups() -> list[dict]:
    """Group episodes into conversations by time proximity."""
    conn = _db_connect(_MEMORY_DB)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT id, ts, text FROM episodes ORDER BY ts"
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()

    groups: list[dict] = []
    current: list[dict] | None = None
    for row in rows:
        ep = {"id": row["id"], "ts": row["ts"], "text": row["text"]}
        if current is None or (ep["ts"] - current[-1]["ts"]) > _CONVERSATION_GAP_SECONDS:
            current = []
            groups.append({"episodes": current})
        current.append(ep)

    result = []
    for g in groups:
        eps = g["episodes"]
        first = eps[0]
        last = eps[-1]
        topic = first["text"].split("\n")[0][:120]
        result.append({
            "id": first["id"],
            "topic": topic,
            "message_count": len(eps),
            "created_at": first["ts"],
            "updated_at": last["ts"],
        })
    return result


def _safe_json_decode(value: str | None) -> dict | None:
    """Parse a JSON string, returning None on any failure."""
    if not value:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        log.warning("memory: malformed JSON in episode neurobus field (%.40r)", value)
        return None


def _load_conversation_by_id(conversation_id: int) -> dict | None:
    """Return a single conversation with its messages, or None if not found."""
    groups = _load_conversation_groups()
    for g in groups:
        if g["id"] == conversation_id:
            # Re-fetch messages for this conversation
            conn = _db_connect(_MEMORY_DB)
            if conn is None:
                return None
            try:
                first_ts = g["created_at"]
                last_ts = g["updated_at"]
                rows = conn.execute(
                    "SELECT id, ts, text, neurobus, action FROM episodes "
                    "WHERE ts >= ? AND ts <= ? ORDER BY ts",
                    (first_ts, last_ts),
                ).fetchall()
            except sqlite3.Error:
                return None
            finally:
                conn.close()
            messages = [
                {
                    "id": r["id"],
                    "ts": r["ts"],
                    "text": r["text"],
                    "neurobus": _safe_json_decode(r["neurobus"]),
                    "action": r["action"],
                }
                for r in rows
            ]
            return {"id": g["id"], "topic": g["topic"], "messages": messages}
    return None


def _search_knowledge(q: str, top_n: int = 5) -> dict:
    """Search knowledge DB via FTS5 (text only — no embedding model)."""
    conn = _db_connect(_KNOWLEDGE_DB)
    if conn is None:
        return {"facts": [], "concepts": [], "research_questions": []}

    def search_table(table: str, fts_table: str, label_col: str, content_col: str, src_col: str) -> list[dict]:
        # Validate identifiers against whitelist before any SQL interpolation
        for ident in (table, fts_table, label_col, content_col, src_col):
            if ident not in _KNOWLEDGE_TABLES and ident not in _KNOWLEDGE_COLUMNS:
                log.warning("memory: unknown SQL identifier rejected: %r", ident)
                return []
        try:
            rows = conn.execute(
                f"SELECT rowid, rank FROM {fts_table} "
                f"WHERE {fts_table} MATCH ? ORDER BY rank LIMIT ?",
                (q, top_n),
            ).fetchall()
            if not rows:
                # LIKE fallback
                pattern = f"%{q}%"
                rows = conn.execute(
                    f"SELECT {label_col}, {content_col}, {src_col} FROM {table} "
                    f"WHERE {content_col} LIKE ? OR {label_col} LIKE ? LIMIT ?",
                    (pattern, pattern, top_n),
                ).fetchall()
                return [
                    {"label": r[0], "content": r[1][:300], "source": r[2]}
                    for r in rows
                ]
            ids = [r[0] for r in rows]
            placeholders = ",".join("?" * len(ids))
            cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
            col_names = [c[1] for c in cols]
            detail_rows = conn.execute(
                f"SELECT * FROM {table} WHERE id IN ({placeholders})", ids
            ).fetchall()
            result = []
            for r in detail_rows:
                row_dict = dict(zip(col_names, r))
                result.append({
                    "label": row_dict.get(label_col, ""),
                    "content": str(row_dict.get(content_col, ""))[:300],
                    "source": row_dict.get(src_col, ""),
                    "status": row_dict.get("status", ""),
                })
            return result
        except sqlite3.Error:
            return []

    try:
        return {
            "facts": search_table("facts", "facts_fts", "name", "content", "source_page"),
            "concepts": search_table("concepts", "concepts_fts", "name", "summary", "source_pages"),
            "research_questions": search_table(
                "research_questions", "research_questions_fts", "question", "question", "source_page"
            ),
        }
    finally:
        conn.close()


@app.get("/api/conversations")
async def api_conversations(request: Request) -> list[dict]:
    """List conversation groups from the episode store. Requires auth token."""
    if not _check_token(request):
        raise HTTPException(status_code=401, detail="auth_required")
    return _load_conversation_groups()


@app.get("/api/conversations/{conversation_id:int}")
async def api_conversation_detail(conversation_id: int, request: Request) -> dict:
    """Get a single conversation with its messages. Requires auth token."""
    if not _check_token(request):
        raise HTTPException(status_code=401, detail="auth_required")
    conv = _load_conversation_by_id(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    return conv


@app.get("/api/memory/search")
async def api_memory_search(request: Request, q: str = "") -> dict:
    """Semantic / text search over the knowledge base. Requires auth token."""
    if not _check_token(request):
        raise HTTPException(status_code=401, detail="auth_required")
    if not q.strip():
        raise HTTPException(status_code=400, detail="missing_query")
    return _search_knowledge(q.strip())


if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
else:
    # Dashboard is served by the separate AXIS repo at axis-dash.vercel.app.
    # The static/ directory is not required for bridge operation.
    log.info("static dir not present — dashboard served by external AXIS frontend")


def run(host: str = "0.0.0.0", port: int = 8080) -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    if not HELIOS_TOKEN:
        log.warning(
            "HELIOS_TOKEN is not set — all authenticated endpoints will reject "
            "every request. Set HELIOS_TOKEN in the environment before starting."
        )
    log.info("orb web server starting on %s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run()
