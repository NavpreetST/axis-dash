# Helios Bridge — Complete Operator Handoff Summary

**Date:** 2026-06-07
**Branch:** `feat/post-merge-cleanup`
**PR:** https://github.com/NavpreetST/helios/pull/6
**Status:** Ready for merge. All 4 CodeRabbit reviews resolved. 9/9 auth tests pass.

---

## TL;DR

Connected the Helios/Aegis daemon to the AXIS dashboard on Vercel via a
FastAPI bridge. Fixed an 11-day-stale state-writer bug in the daemon.
Added token auth (header + query param), explicit CORS allowlist, WS
origin checking. Resolved all CodeRabbit review feedback (4 reviews,
13 actionable items, 12 fixed + 1 deferred per CodeRabbit's own
assessment that it's not a bug).

---

## 1. The Problem (Before)

- No web bridge between the Helios daemon and AXIS dashboard
- `orb_state.json` and `neurobus_state.json` had been stale since
  2026-05-26 (11 days) — daemon was running but not writing state
- `renderer_state.json` only wrote on chat turns (no turns = no update)
- Leaked `GROQ_API_KEY` in `/opt/aegis/aegis.txt` (untracked but on disk)
- Root cause of stale state: `aegis/nexus/neurobus.py:on_tick` had the
  same `try/except` block copy-pasted three times with three duplicate
  imports — pre-existing bug, not introduced by this work

---

## 2. What Was Built: The Bridge

Extended `aegis/web/server.py` in place (established bridge module, no
new package). Lives as a separate process from the daemon — no systemd,
no `main.py` task injection. Launched via `nohup` matching the daemon
pattern.

### Endpoints

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health` | `Authorization: Bearer` header only | Daemon liveness, pid, uptime, state-file freshness |
| `WS /state` | Bearer or `?token=` | 1 Hz state push (neurobus scalars, h vector, renderer fields) |
| `WS /chat` | Bearer or `?token=` | Bidirectional bridge to daemon unix socket (request/reply) |
| `SSE /logs` | Bearer or `?token=` | Tails `/var/lib/aegis/events/YYYY-MM-DD.jsonl` with day rollover |

### Response Shape (WS /state, 14 fields)

```text
neurobus: {reward, novelty, attention, patience, threat, trust}
h: [64 floats]              # NCP hidden state (empty if NCP not initialized)
is_speaking: bool
last_action_type: str
tick_id: int                # always 0 — not persisted by neurobus
mnemosyne_event: dict|null
provider: str|null          # from renderer_state.json last_success
rpd_used: int|null
rpd_budget: int|null
connected: bool             # both orb_state + renderer_state fresh
uptime_seconds: int|null    # derived from /proc/<pid>/stat
tick_rate: 1.0              # documented constant from clock.py:30
pam: null                   # no runtime source
coherence: null             # no runtime source
```

---

## 3. Auth Implementation (Full Detail)

### Token Storage
- Read from `HELIOS_TOKEN` env var
- Never hardcoded, never logged, never committed
- Fail-closed: if unset, all auth endpoints reject everything
- Startup warning emitted: `log.warning("HELIOS_TOKEN is not set...")`

### Token Validation
- Constant-time comparison via `hmac.compare_digest`
- Accepts BOTH `Authorization: Bearer <token>` header AND `?token=<token>` query param
- WS/SSE: query param is the primary path because `EventSource` and
  browser WS APIs can't set `Authorization` headers
- `/health`: header-only (ops tools, not browsers)

### Failure Modes
- WS bad token → `accept()` then `close(code=4401, reason="auth_failed")`
  (must accept first to avoid opaque HTTP 403, then close with app-defined code)
- HTTP bad token → 401 with `{"detail": "auth_required"}`
- WS bad origin → `close(code=4401, reason="origin_not_allowed")`
- Non-browser clients (no Origin header) pass through origin check

---

## 4. CORS Implementation (Full Detail)

### The Journey (3 iterations)

**Iteration 1 — CORSMiddleware with explicit allowlist:**
```python
class CORSMiddleware(BaseHTTPMiddleware):
    """Reflects request Origin if in allowlist; never '*' because auth is involved."""
    async def dispatch(self, request, call_next):
        origin = request.headers.get("origin")
        allow_origin = origin if origin in self.allowed_origins else None
        # ...sets ACAO, Vary, ACAC, methods, headers, max-age=600...
```

**Iteration 2 — AXIS SSE CORS issue (commit `cf9d2f7`):**
- AXIS reported SSE was CORS-blocked despite middleware
- Added `: connected\n\n` comment to flush headers immediately
- Wrapped file I/O in `asyncio.to_thread` to avoid blocking event loop
- Added explicit CORS headers on `StreamingResponse` as belt-and-suspenders

**Iteration 3 — CodeRabbit flagged redundant CORS (commit `bb9aa18`):**
- CodeRabbit said the explicit headers on SSE are redundant with middleware
- Verified: `ACAO`, `Vary`, `ACAC` all present on EventSource handshake after removal
- Removed the explicit header block, kept middleware + initial comment flush

### WS Origin Check (commit `cb77c86`, Bug 7)
- `BaseHTTPMiddleware.dispatch` only runs for HTTP requests, not WS upgrades
- Added explicit origin check in both `state_ws` and `chat_ws`:
  ```python
  origin = ws.headers.get("origin")
  if origin and origin not in ALLOWED_ORIGINS:
      await ws.close(code=4401, reason="origin_not_allowed")
  ```

### Configuration
- `ALLOWED_ORIGINS` env var, comma-separated
- Default: `http://localhost:5173,https://axis-dash.vercel.app`
- Live: `https://axis-dash.vercel.app,http://localhost:5173`
- Never `"*"` because credentials mode is involved

---

## 5. State-Writer Fix (The Real Blocker)

### Diagnosis
`aegis/nexus/neurobus.py:on_tick` had:
- 3 identical `try/except (OSError, ValueError)` blocks
- 3 duplicate `from aegis.observability.paths import ...` imports
- 3 inline `__import__("datetime")` calls when `datetime` was already imported

### Fix (commit `0b8f5ab`)
- Consolidated into one `on_tick` coroutine with two clean try blocks
- One for lightweight `neurobus_state.json`, one for richer `orb_state.json`
- Replaced `__import__` with proper module-level imports
- No change to decay rates, subscriber logic, or NCP behavior

### Verification
- `orb_state.json` mtime: updates every 1s
- Content: real decaying values (`attention: 0.038`, `patience: 0.139`, `trust: 0.440`)
- `neurobus_state.json` also updating

---

## 6. CodeRabbit Review Resolution (Full Detail)

### Review 1 (commit 74321fc) — 2 actionable, 3 nitpicks
- ✅ Removed unused `WS_CLOSE_POLICY_VIOLATION` constant
- ✅ Removed unused `_FILENAME_RE` constant
- ⏭️ Sync file I/O in SSE tail — skipped per CodeRabbit's own guidance
- ✅ README: documented `AEGIS_SOCK` env var
- ✅ README: fixed intro to match arch section (Groq primary, template fallback)

### Review 2 (commit 0b8f5ab) — 2 actionable, 1 nitpick
- ✅ Added `TypeError` to `except` clauses in neurobus (json.dumps can raise it)
- ✅ Narrowed broad `except Exception` to `(ImportError, ModuleNotFoundError)` + debug logging
- ✅ Removed redundant explicit CORS headers from SSE

### Review 3 (commit bb9aa18) — 1 actionable
- ✅ Separated import guard from function call in `_build_orb_snapshot`
  so runtime ImportError isn't misclassified

### Review 4 (commit f98a8e9, on TODO.md) — 1 actionable, 2 nitpicks
- ✅ Cross-referenced Bug 5 fix in TODO (double-call was resolved)
- ✅ Added `text` language specifiers to fenced code blocks

### Bug Report (triggered by Navpreet "@codeRabbit review bugs") — 10 bugs

| # | Severity | Issue | Resolution |
|---|---|---|---|
| 1 | 🔴 High | `mkdir` blocks event loop | ✅ Wrapped in `asyncio.to_thread` via `_open_log` helper |
| 2 | 🔴 High | SSE client disconnect never checked | ✅ Added `request.is_disconnected()` in generator |
| 3 | 🔴 High | TOCTOU in `/chat` (exists() then connect) | ✅ Removed pre-check, rely on try/except |
| 4 | 🔴 High | No startup warning for missing `HELIOS_TOKEN` | ✅ Added `log.warning` in `run()` |
| 5 | 🟡 Medium | `/health` double `/proc` scan | ✅ Compute `daemon_pid` once, thread through `_daemon_uptime_seconds_for_pid()` |
| 6 | 🟡 Medium | `last_action_type` `or` chain drops falsy | ✅ Use explicit `_first_str()` helper |
| 7 | 🟡 Medium | CORS doesn't apply to WS upgrades | ✅ Added origin check in both WS handlers |
| 8 | 🟡 Medium | `_check_token` type mismatch | ✅ Changed to `HTTPConnection` (common base) |
| 9 | 🟢 Low | Double `time.time()` in uptime | ✅ Capture once as `now` |
| 10 | 🟢 Low | `_is_speaking` reference semantics | ⏭️ Deferred — CodeRabbit's own assessment: "always reads correct value" |

**Score: 9 fixed, 1 deferred (not a bug).**

---

## 7. Verification (Current State)

```text
Auth tests: 9/9 pass
  WS /state ?token=  fields=14
  WS /state Bearer   fields=14
  WS /chat ?token=   reply received (e.g. "hello, it's nice to meet you, navpreet...")
  SSE /logs ?token=  text/event-stream; charset=utf-8
  SSE /logs Bearer   text/event-stream; charset=utf-8
  /health Bearer     200
  WS /state bad      close 4401
  WS /chat bad       close 4401
  SSE /logs bad      401

WS origin check: disallowed origin → close 4401
SSE CORS: ACAO + Vary + ACAC all present from CORSMiddleware
State files: orb_state.json + neurobus_state.json updating every 1s
```

---

## 8. Commit Log (11 Commits, All Pushed)

```text
7e98829 docs: add OPERATOR_SUMMARY.md handoff for Navpreet
dcdf95f docs(todo): address CodeRabbit review 4 on TODO.md
495e159 docs: update TODO.md with CodeRabbit bug report resolutions
cb77c86 fix: address 9 CodeRabbit bugs in helios bridge
f98a8e9 docs: add TODO.md handoff for bridge work and deferred items
5c00ca0 fix(web): include coherence field in /state and /health responses
bb9aa18 fix: address CodeRabbit review feedback
0b8f5ab fix(nexus): consolidate triplicated on_tick state-writer in neurobus
cf9d2f7 web: fix SSE CORS and flush headers immediately
74321fc web: accept token via query param for WS/SSE + explicit CORS allowlist
14b82e6 web: add P0 bridge endpoints and state freshness
```

---

## 9. Operator Action Items

### Required (Block Merge)
1. **Merge PR #2** — branch is ready, all tests pass, all reviews resolved
2. **Rotate the leaked `GROQ_API_KEY`** in `/opt/aegis/aegis.txt` and
   delete the file. Flagged in `helios-first-contact-findings.md` §12.
   File is untracked but still on disk.

### Recommended (Post-Merge)
3. **Fix `/run/aegis/` vs `/tmp/aegis.sock`** — the documented launch
   path uses `/run/aegis/` but that directory no longer exists and
   can't be created by `itznavpreet` (PermissionError). Currently
   running with code default `/tmp/aegis.sock`. Either:
   - `sudo mkdir /run/aegis && sudo chown itznavpreet /run/aegis` and
     revert to the documented launch, or
   - Update the launch to use `/tmp/aegis.sock` consistently.

4. **Commit or discard uncommitted `aegis/main.py`** — adds
   `eventlog.log_event` calls. Pre-existing, not staged.
   `aegis/eventlog.py` module is also untracked. Decide whether to
   land the eventlog feature.

### Nice-to-Have (Logged in TODO.md)
5. **`pam` / `coherence`** are hardcoded `null` (no runtime source).
   Implement in NCP layer or remove from AXIS contract.
6. **`tick_id`** is always 0 (neurobus doesn't persist it). Add to
   state write if AXIS wants a live tick counter.
7. **`connected: false` when idle** — `_connected()` requires both
   `orb_state.json` AND `renderer_state.json` to be fresh. Renderer
   only writes on chat turns, so this reads `false` during idle
   periods even though the daemon is alive. AXIS UI keys off WS
   lifecycle, not `connected`, so currently cosmetic. Relax
   `_connected()` if you want `connected: true` when daemon is up
   but idle.
8. **`_find_daemon_pid()` scans /proc on every WS tick** — fine for
   1-2 clients, add up with many WebSockets. Consider TTL cache.
9. **Docstring coverage (44% vs 80%)** — project-wide. Add docstrings
   to legacy modules if you want to clear the check.
10. **Stale unix socket after daemon crash** — if daemon dies but
    `/tmp/aegis.sock` remains, bridge gets "Connection refused"
    instead of "socket not found". Add cleanup in chat handler.
11. **`aiofiles` for SSE tail** — CodeRabbit suggested, but
    `asyncio.to_thread` is sufficient per CodeRabbit's own guidance.
    Re-evaluate if SSE connection count grows.

---

## 10. Live State on Box

```text
Daemon:  <virtualenv_path>/bin/python -m aegis.main  (PID <pid>)
Socket:  /tmp/aegis.sock
Bridge:  <virtualenv_path>/bin/python -m aegis.web.server  (PID <pid>)
Env:     HELIOS_TOKEN=<REDACTED_TOKEN>
         AEGIS_SOCK=/tmp/aegis.sock
         ALLOWED_ORIGINS=https://axis-dash.vercel.app,http://localhost:5173
Tunnel:  <tunnel_url> → localhost:8080
Vercel:  PUBLIC_HELIOS_TOKEN=<REDACTED_TOKEN>
         Bridge URL points at the tunnel
```

### Launch Commands

```bash
# Daemon
cd <project_dir> && nohup <virtualenv_path>/bin/python -m aegis.main \
  > /tmp/aegis-main.log 2>&1 & disown

# Bridge
cd <project_dir> && HELIOS_TOKEN=<your-token> \
  AEGIS_SOCK=/tmp/aegis.sock \
  ALLOWED_ORIGINS='https://axis-dash.vercel.app,http://localhost:5173' \
  PYTHONPATH=<project_dir> \
  nohup <virtualenv_path>/bin/python -m aegis.web.server \
  > /tmp/aegis-web.log 2>&1 & disown
```

---

## 11. Handoff Documents

- **`OPERATOR_SUMMARY.md`** (this file) — comprehensive handoff
- **`TODO.md`** — full deferred-items log with rationale
- **`helios-first-contact-findings.md`** — original 2026-06-06 inspection notes

Locations:
- `/opt/aegis/OPERATOR_SUMMARY.md` (tracked in branch)
- `/opt/aegis/TODO.md` (tracked in branch)
- `C:\Users\Navdeep\Desktop\Code\Helios\OPERATOR_SUMMARY.md` (local)
- `C:\Users\Navdeep\Desktop\Code\Helios\TODO.md` (local)
- `C:\Users\Navdeep\Desktop\Code\Helios\helios-first-contact-findings.md` (local)
