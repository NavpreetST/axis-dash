# Helios Bridge — Operator Handoff Summary

**Date:** 2026-06-07
**Branch:** `feat/bridge-query-auth`
**PR:** https://github.com/NavpreetST/helios/pull/2
**Status:** Ready for merge. All CodeRabbit reviews resolved.

---

## What Was Built

A FastAPI bridge (`aegis/web/server.py`) that connects the Helios/Aegis
daemon to the AXIS dashboard on Vercel. Lives alongside the daemon as a
separate process — no systemd, no main.py task injection.

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health` | Bearer header only | Daemon liveness, pid, uptime, state-file freshness |
| `WS /state` | Bearer or `?token=` | 1 Hz state push (neurobus, h, renderer fields, connected) |
| `WS /chat` | Bearer or `?token=` | Bidirectional bridge to daemon unix socket |
| `SSE /logs` | Bearer or `?token=` | Tails `/var/lib/aegis/events/YYYY-MM-DD.jsonl` |

**Security:** `HELIOS_TOKEN` env var, constant-time comparison, explicit
CORS allowlist (`ALLOWED_ORIGINS`), WS origin check (browser clients only),
WS close 4401 for auth/origin failures.

---

## What Was Fixed

### State-writer (the real blocker)
`aegis/nexus/neurobus.py` had the same `try/except` block triplicated in
`on_tick`, causing `orb_state.json` and `neurobus_state.json` to go stale
on 2026-05-26. Consolidated into two clean blocks. State files now
update every tick (1 Hz), verified by mtime and bridge reads.

### Auth + CORS
- Token from `HELIOS_TOKEN` env, never hardcoded
- WS/SSE accept `Authorization: Bearer` OR `?token=` query param
- Explicit allowlist (never `"*"`) with WS origin check
- Bad token → WS close 4401, HTTP 401
- Startup warning if `HELIOS_TOKEN` is unset

### CodeRabbit reviews — all resolved
**4 reviews posted, 13 actionable items, 12 fixed + 1 deferred (not a bug).**

- 3 nitpicks: dead constants removed, redundant SSE CORS removed
- 2 README fixes: socket path docs, renderer description
- 2 neurobus fixes: `TypeError` catch, narrow exception handling
- 10-bug report: **9 fixed**, 1 deferred (CodeRabbit's own assessment says not a bug)
- TODO.md: 1 cross-reference fix, 2 markdown formatting fixes

---

## Verification

```
Auth tests: 9/9 pass
  WS /state ?token=  fields=14
  WS /state Bearer   fields=14
  WS /chat ?token=   reply received
  SSE /logs ?token=  text/event-stream
  SSE /logs Bearer   text/event-stream
  /health Bearer     200
  WS /state bad      close 4401
  WS /chat bad       close 4401
  SSE /logs bad      401

WS origin check: disallowed origin → close 4401
SSE CORS: ACAO + Vary + ACAC all present from CORSMiddleware
State files: orb_state.json + neurobus_state.json updating every 1s
```

---

## Commits (9 total, all pushed)

```
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

## Operator Action Items

### Required
1. **Merge PR #2** — branch is ready, all tests pass, all reviews resolved.
2. **Rotate the leaked `GROQ_API_KEY`** in `/opt/aegis/aegis.txt` and
   delete the file. Flagged in `helios-first-contact-findings.md` §12.
   File is untracked but still on disk.

### Recommended
3. **Decide on `/run/aegis/` vs `/tmp/aegis.sock`** — the documented
   launch path uses `/run/aegis/` but that directory no longer exists
   and can't be created by the `itznavpreet` user. Currently running
   daemon with the code default `/tmp/aegis.sock`. Either:
   - `sudo mkdir /run/aegis && sudo chown itznavpreet /run/aegis` and
     revert to the documented launch, or
   - Update the launch to use `/tmp/aegis.sock` consistently.

4. **Commit or discard uncommitted `aegis/main.py` changes** — adds
   `eventlog.log_event` calls. Pre-existing, not staged. The
   `aegis/eventlog.py` module is also untracked. Decide whether to
   land the eventlog feature as-is.

### Nice-to-have (logged in TODO.md)
5. **`pam` / `coherence`** are hardcoded `null` (no runtime source).
   Either implement in the NCP layer or remove from the AXIS contract.
6. **`tick_id`** is always 0 (neurobus doesn't persist it). Add to the
   state write if AXIS wants a live tick counter.
7. **`connected: false` when idle** — `_connected()` requires both
   `orb_state.json` AND `renderer_state.json` to be fresh. Renderer
   only writes on chat turns, so the field reads `false` during idle
   periods. AXIS UI keys off WebSocket lifecycle, not `connected`, so
   this is currently cosmetic. Relax `_connected()` if you want
   `connected: true` when the daemon is up but idle.
8. **Docstring coverage (44% vs 80%)** — project-wide. Add docstrings
   to legacy modules (`aegis/nexus/bus.py`, `aegis/observability/paths.py`)
   if you want to clear the check.
9. **Stale unix socket after daemon crash** — if the daemon dies but
   `/tmp/aegis.sock` remains, the bridge gets "Connection refused"
   instead of "socket not found". Add cleanup in the chat handler or
   use a watchdog.

---

## Live State on Box

```
Daemon:  /opt/aegis/.venv/bin/python -m aegis.main  (PID 124842)
Socket:  /tmp/aegis.sock
Bridge:  /opt/aegis/.venv/bin/python -m aegis.web.server  (PID 123388)
Env:     HELIOS_TOKEN=test-token-12345
         AEGIS_SOCK=/tmp/aegis.sock
         ALLOWED_ORIGINS=https://axis-dash.vercel.app,http://localhost:5173
Tunnel:  https://shoot-effect-seeker-marvel.trycloudflare.com → localhost:8080
Vercel:  PUBLIC_HELIOS_TOKEN=test-token-12345
         Bridge URL points at the tunnel
```

Launch commands (matching daemon pattern, no systemd):

```bash
# Daemon
cd /opt/aegis && nohup /opt/aegis/.venv/bin/python -m aegis.main \
  > /tmp/aegis-main.log 2>&1 & disown

# Bridge
cd /opt/aegis && HELIOS_TOKEN=<your-token> \
  AEGIS_SOCK=/tmp/aegis.sock \
  ALLOWED_ORIGINS='https://axis-dash.vercel.app,http://localhost:5173' \
  PYTHONPATH=/opt/aegis \
  nohup /opt/aegis/.venv/bin/python -m aegis.web.server \
  > /tmp/aegis-web.log 2>&1 & disown
```

---

## Handoff Doc

Full TODO with rationale for every deferred item:
- `/opt/aegis/TODO.md` (tracked in the branch)
- `C:\Users\Navdeep\Desktop\Code\Helios\TODO.md` (local copy)
- `C:\Users\Navdeep\Desktop\Code\Helios\helios-first-contact-findings.md`
  (original inspection notes from 2026-06-06)
