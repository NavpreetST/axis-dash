# Helios / Aegis — TODO & Handoff Log

Persistent handoff for the authenticated web bridge work on
`feat/bridge-query-auth` (PR #2). Generated 2026-06-07.

This file tracks resolved items, deferred items, and known issues for
future agents. Update it when you close or discover something.

The canonical version lives at `/opt/aegis/TODO.md` (tracked in the
branch). This local copy is for quick reference.

---

## Resolved This Session (2026-06-06 → 2026-06-07)

### P0 bridge endpoints (`aegis/web/server.py`)
- `GET /health` — header-only auth, returns daemon pid/uptime/state-file freshness
- `WS /state` — 1 Hz push, auth via `Authorization: Bearer` or `?token=`
- `WS /chat` — bridges browser to daemon unix socket, request/reply
- `SSE /logs` — tails `/var/lib/aegis/events/YYYY-MM-DD.jsonl` with day rollover

### Auth + CORS
- Token from `HELIOS_TOKEN` env var, constant-time comparison (`hmac.compare_digest`)
- WS/SSE accept token via header OR `?token=` query param
- WS bad token → close code 4401 (app-defined auth failure)
- HTTP bad token → 401
- CORS: explicit `ALLOWED_ORIGINS` env allowlist, never `"*"`
- **WS origin check**: added to both `state_ws` and `chat_ws` (BaseHTTPMiddleware
  doesn't run on WS upgrades). Bad origin → close 4401. Non-browser clients
  (no Origin header) pass through.
- **Startup warning**: `log.warning` emitted if `HELIOS_TOKEN` is unset.
- SSE CORS: initial `: connected\n\n` comment flushes headers immediately

### State-writer fix (`aegis/nexus/neurobus.py`)
- Consolidated triplicated try/except blocks in `on_tick` into two clean blocks
- Added `TypeError` to except clauses (json.dumps can raise it)
- Narrowed broad `except Exception` in `_build_orb_snapshot` to
  `(ImportError, ModuleNotFoundError)` with debug logging
- **Separated import guard from function call** in `_build_orb_snapshot` so a
  runtime ImportError inside `hidden_state_vec()` / `pop_last_event()` is not
  misclassified as a missing module.
- `orb_state.json` and `neurobus_state.json` update every tick (1 Hz)

### CodeRabbit review items resolved
- Removed unused constant `WS_CLOSE_POLICY_VIOLATION`
- Removed unused constant `_FILENAME_RE`
- Removed redundant explicit CORS headers from SSE (CORSMiddleware handles it)
- README: documented `AEGIS_SOCK` env var
- README: fixed intro to match arch section (Groq primary, template fallback)
- `coherence` field added to `/state` and `/health` responses (was defined
  as constant but never included)

### CodeRabbit bug report — 9 of 10 bugs fixed
**Resolved (commit `cb77c86`):**
- **Bug 1 (High)**: `mkdir` in `_tail_eventlog` blocked event loop → wrapped
  in `asyncio.to_thread` via `_open_log` helper
- **Bug 2 (High)**: SSE client disconnect never checked → added
  `request.is_disconnected()` check in event_stream generator
- **Bug 3 (High)**: TOCTOU in `/chat` (exists() then connect) → removed
  pre-check, rely on try/except around `open_unix_connection`
- **Bug 4 (High)**: No startup warning for missing `HELIOS_TOKEN` → added
  `log.warning` in `run()`
- **Bug 5 (Medium)**: `/health` double `/proc` scan → compute `daemon_pid`
  once, thread through `_daemon_uptime_seconds_for_pid()`
- **Bug 6 (Medium)**: `last_action_type` `or` chain drops valid falsy values
  → use explicit `_first_str()` helper
- **Bug 7 (Medium)**: CORS doesn't apply to WS upgrades → added origin check
  in both `state_ws` and `chat_ws`
- **Bug 8 (Medium)**: `_check_token` type annotation `Request` vs `WebSocket`
  → changed to `HTTPConnection` (common base)
- **Bug 9 (Low)**: Double `time.time()` in `_daemon_uptime_seconds` → capture
  once as `now`

### Infrastructure
- `gh` CLI authenticated on box as `NavpreetST` (token has `repo` scope)
- Branch `feat/bridge-query-auth` pushed to remote (8 commits)
- PR #2 title updated: "Add authenticated web bridge with /state, /chat,
  /logs endpoints and fix stale state-writer"

---

## Deferred / Future Work (Handoff)

### CodeRabbit bug — intentionally deferred
- **Bug 10 (Low)**: `_is_speaking` imported as value, not reference. CodeRabbit's
  own assessment: "this will always read the correct current value on each
  call" because Python re-fetches module attributes. Style concern only, not
  a bug. The `_build_orb_snapshot` fix in Bug 11 already reads `_is_speaking`
  as a value from the module on each call, which is the current semantics.

### CodeRabbit items intentionally skipped
- **Sync file I/O in SSE tail** (server.py `open()`/`f.read()`) — CodeRabbit
  suggested `aiofiles`. Skipped per CodeRabbit's own guidance: "acceptable
  for current low concurrency". The blocking read is already wrapped in
  `asyncio.to_thread` (and `mkdir` is now too). Re-evaluate if SSE
  connection count grows.
- **Docstring coverage (44% vs 80% threshold)** — project-wide issue, not
  specific to this PR. My new functions are documented; most pre-existing
  code in `aegis/` lacks docstrings. If you want to clear the check, add
  docstrings to the legacy modules (`aegis/nexus/bus.py`,
  `aegis/observability/paths.py`, etc.) first.

### Bridge design issues
- **`connected: false` when daemon is idle** — `_connected()` requires BOTH
  `orb_state.json` AND `renderer_state.json` to be fresh. Renderer only
  writes on chat turns, so `connected` will be `false` during idle periods
  even though the daemon is alive and neurobus is writing. AXIS UI keys off
  WebSocket lifecycle, not `connected`, so this is currently a cosmetic
  issue. If AXIS wants `connected: true` when the daemon is up but idle,
  relax `_connected()` to require only `orb_state.json` freshness.
  File: `aegis/web/server.py:293` (`_connected`).
- **`tick_id` is always 0** — the bridge reads `tick_id` from `orb_state.json`,
  but neurobus doesn't write it. The clock increments a counter internally
  but never persists it. If AXIS wants a live tick counter, add `tick_id`
  to the neurobus state write in `aegis/nexus/neurobus.py:on_tick`.
- **`_find_daemon_pid()` scans /proc on every WS tick** — runs at 1 Hz per
  connected client. Fine for 1-2 clients, but will add up if AXIS opens
  multiple WebSockets. Consider caching the PID with a TTL.

### Infrastructure / operational
- **`/run/aegis/` directory missing** — the live launch uses
  `AEGIS_SOCK=/run/aegis/aegis.sock` but `/run/aegis/` no longer exists
  and can't be created by the `itznavpreet` user (PermissionError on mkdir).
  Currently running daemon with `AEGIS_SOCK=/tmp/aegis.sock` (code default).
  This is a regression from the documented launch path. To fix: either
  create `/run/aegis/` with proper permissions (needs root), or update
  the launch to use `/tmp/aegis.sock` consistently.
- **Stale unix socket after daemon crash** — if the daemon dies but the
  socket file remains (`/tmp/aegis.sock`), the bridge gets "Connection
  refused" instead of "socket not found". Fix: on `ConnectionRefusedError`,
  remove the stale socket file before reporting the error. Or use a
  watchdog that recreates the socket.
- **Leaked `GROQ_API_KEY` in `aegis.txt`** — the operator runbook at
  `/opt/aegis/aegis.txt` contains a real Groq API key. File is untracked
  (not in git) but still on disk. **Rotate the key** and remove the file.
  Flagged in `helios-first-contact-findings.md` §12 but not yet done.
- **Uncommitted changes in `aegis/main.py`** — adds `eventlog.log_event`
  calls in socket handler and main-loop error path. Pre-existing, not
  staged. `aegis/eventlog.py` is the corresponding new module (untracked).
  Decide whether to commit these as part of the eventlog feature.

### Runtime / NCP (out of scope for this PR)
- **`pam` and `coherence` are hardcoded `null`** — no source in the runtime
  (see `helios-first-contact-findings.md` §11). If these are real planned
  fields, implement them in the neurobus/NCP layer. If not, remove from the
  AXIS contract to avoid promising a field that never resolves.
- **`uptime_seconds` is derived from `/proc/<pid>/stat`** — bridge-side
  computation, not a runtime field. If the runtime ever exposes its own
  uptime, switch the bridge to read it. Currently documented as "daemon
  process uptime" in the response.

### Static UI
- **`aegis/web/static/orb/`** — the existing in-repo orb UI is still served
  by the bridge's static mount. AXIS is on Vercel and doesn't need it.
  Removing the mount would be a breaking change for whatever was using it.
  Leave as-is unless explicitly told to remove.

---

## Verification (current state, 2026-06-07)

```
Auth tests: 9/9 pass
  WS /state ?token=  fields=14  (was 13, +coherence)
  WS /state Bearer   fields=14
  WS /chat ?token=   reply received
  SSE /logs ?token=  text/event-stream
  SSE /logs Bearer   text/event-stream
  /health Bearer     200
  WS /state bad      close 4401
  WS /chat bad       close 4401
  SSE /logs bad      401

WS origin check (Bug 7 fix):
  Origin: https://evil.example.com  → rejected, close 4401
  (non-browser clients without Origin header pass through)

SSE CORS (no explicit headers, CORSMiddleware only):
  Origin: https://axis-dash.vercel.app
  → ACAO: https://axis-dash.vercel.app
  → Vary: Origin
  → ACAC: true

State files:
  /var/lib/aegis/orb_state.json        updating every 1s
  /var/lib/aegis/neurobus_state.json   updating every 1s
  /var/lib/aegis/renderer_state.json   stale (no chat turns since restart)
```

---

## Commits on `feat/bridge-query-auth`

```
cb77c86 fix: address 9 CodeRabbit bugs in helios bridge
f98a8e9 docs: add TODO.md handoff for bridge work and deferred items
5c00ca0 fix(web): include coherence field in /state and /health responses
bb9aa18 fix: address CodeRabbit review feedback
0b8f5ab fix(nexus): consolidate triplicated on_tick state-writer in neurobus
cf9d2f7 web: fix SSE CORS and flush headers immediately
74321fc web: accept token via query param for WS/SSE + explicit CORS allowlist
14b82e6 web: add P0 bridge endpoints and state freshness
```

PR: https://github.com/NavpreetST/helios/pull/2
