# Merge Runbook — `ci/gate-ladder-phase4-step1`

## 1. Merge Order

### PR #26 `fix/7-codebase-bugs` → `main` (Helios Backend fixes)

| Field | Value |
|-------|-------|
| Branch | `fix/7-codebase-bugs` |
| Status | OPEN, MERGEABLE |
| CI Lint | IN_PROGRESS |
| CodeRabbit | PASSED + PENDING advisory |
| Conflicts with bridge? | None — touches `server.py` only at the static-files log message (F6). The bridge PR touches `_detect_launch_method` and `_git_short_commit` in entirely different sections of the file. Git handles the merge automatically. |

**Order**: Merge PR #26 first (it's a narrow bug-fix PR on `main`). The `ci/gate-ladder-phase4-step1` branch already has `main` merged in and auto-resolves.

### `ci/gate-ladder-phase4-step1` → `main` (Bridge PR)

| Field | Value |
|-------|-------|
| Branch | `ci/gate-ladder-phase4-step1` |
| Base | `main` |
| Contains | Forge routes, runtime metadata, drift guards, cgroup-based launch_method detection, AEGIS_COMMIT env var fallback, merged renderer/test files from origin/main |

**Procedure:**
```
git checkout main
git merge ci/gate-ladder-phase4-step1    # fast-forward or trivial merge
git push origin main
```

### Potential conflicts

**None.** The gate-ladder branch already includes `main` (merged at commit `99116e1`). Merging PR #26 first adds a few narrow changes that the gate-ladder branch picks up automatically. No manual conflict resolution needed.

---

## 2. Bridge Restart Checklist

### PIDs

| Process | PID | Type | Needs restart? |
|---------|-----|------|----------------|
| Daemon | 216760 | `python -m aegis.main` | **No** — only bridge code changed |
| Bridge | 219039 | `python -m aegis.web.server` | **Yes** — `_build_state()`, `_detect_launch_method()`, forge routes all live in the bridge process |
| Bridge shell | 219038 | `bash -c "cd /opt/aegis && HELIOS_TOKEN=... setsid ..."` | **No** — spawner shell, will re-spawn on bridge restart |

### Safe restart procedure

```bash
# 1. SNAPSHOT — record pre-restart state
echo "=== PRE-RESTART ==="
curl -s -o /dev/null -w 'health: %{http_code}\n' 'http://localhost:8080/health' \
  -H 'Authorization: Bearer test-token-12345'
ps aux | grep -E 'aegis' | grep -v grep
ls -la /var/lib/aegis/*.json
echo "=== END PRE-RESTART ==="

# 2. STOP — graceful SIGTERM to bridge only
kill 219039
# Wait for bridge to exit (uvicorn handles SIGTERM gracefully)
sleep 3
# Verify daemon is still up
ps -p 216760 > /dev/null && echo "daemon OK" || echo "daemon DOWN!"

# 3. VERIFY — old socket and files are intact
ls -la /tmp/aegis.sock
ls -la /var/lib/aegis/orb_state.json

# 4. START — same launch as current (setsid, nohup, env)
cd /opt/aegis && \
HELIOS_TOKEN=test-token-12345 setsid \
  /opt/aegis/.venv/bin/python -m aegis.web.server \
  </dev/null >/tmp/bridge.log 2>&1 & disown

# 5. POST-RESTART SMOKE TESTS
sleep 2  # give bridge time to boot
echo "=== POST-RESTART ==="

# Health endpoint (should be 200)
http_code=$(curl -s -o /dev/null -w '%{http_code}' \
  'http://localhost:8080/health' \
  -H 'Authorization: Bearer test-token-12345')
echo "health: $http_code"

# /state WebSocket (should connect and receive frame)
timeout 3 python3 -c "
import asyncio, json
async def check():
    import websockets
    async with websockets.connect('ws://localhost:8080/state?token=test-token-12345') as ws:
        frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
        keys = sorted(frame.keys())
        print(f'state keys ({len(keys)}): {keys}')
        rt = frame.get('runtime', {})
        print(f'launch_method: {rt.get(\"launch_method\", \"MISSING\")}')
        print(f'connected: {frame.get(\"connected\", \"MISSING\")}')
asyncio.run(check())
" 2>&1 || echo "WS check failed (expected if Python3/websockets not installed)"

# Forge submit smoke test
forge_test=$(curl -s -X POST 'http://localhost:8080/forge/submit' \
  -H 'Authorization: Bearer test-token-12345' \
  -H 'Content-Type: application/json' \
  -d '{"spec":"add a python hello world script"}' 2>&1)
echo "forge/submit: $forge_test"

# Logs SSE smoke test
sse_test=$(timeout 2 curl -s -N \
  'http://localhost:8080/logs?token=test-token-12345' 2>&1 | head -3)
echo "logs SSE: $sse_test"

echo "=== END POST-RESTART ==="
```

### Expected post-restart /state frame

```json
{
  "neurobus": {...}, "h": [...], "is_speaking": false,
  "last_action_type": "idle", "tick_id": 0,
  "mnemosyne_event": null, "provider": "gemini",
  "rpd_used": 7, "rpd_budget": 240,
  "connected": false,
  "uptime_seconds": 86400,
  "tick_rate": 1.0,
  "pam": null, "coherence": null,
  "runtime": {
    "commit": "bc3338a",
    "socket_path": "/tmp/aegis.sock",
    "launch_method": "nohup",
    "renderer_chain": ["gemini", "groq", "template"],
    "memory_backend": {"type": "sqlite", "path": "mnemosyne.db", "exists": true},
    "ncp": {"params": 41361, "hidden_size": 64},
    "budget": {"gemini": {"used": 7, "budget": 240, "window": "America/Los_Angeles"}},
    "known_issues": ["state_stale:renderer_state.json"]
  }
}
```

Key assertions:
- `runtime.launch_method` = `"nohup"` (cgroup-based detection, confirmed live)
- `runtime.commit` = short SHA from git or `AEGIS_COMMIT` env var
- `connected` = `false` (expected — renderer_state.json is stale between chat turns)
- `known_issues` includes `state_stale:renderer_state.json` (benign, by-design)

---

## 3. CI Verification

### Python drift guard (`scripts/ci_state_guard.py`)

Expected output:
```
Detected 15 /state fields: ['coherence', 'connected', 'h', ... 'runtime']
OK — /state contract is intact (frozen fields present, no removals).
```

**Runs on:** CI Gate 4 step in `.github/workflows/ci.yml`, also runnable manually:
```bash
python scripts/ci_state_guard.py
```

**Failure mode:** Hard exit (1) if any frozen field is removed. Warnings for additive fields.

### Frontend drift guard (`scripts/ci_state_guard.mjs`)

Expected output:
```
TelemetryData fields: uptime_seconds, tick_rate, ... runtime
applyLiveFrame reads:  neurobus, uptime_seconds, ... runtime
OK — frontend ↔ /state contract is intact (no regressions).
```

**Runs on:** AXIS CI Gate 4 step, also runnable manually:
```bash
node scripts/ci_state_guard.mjs
```

**Failure mode:** Hard exit (1) if any expected field is missing from `TelemetryData` interface or `applyLiveFrame()`.

### Verification against live state (pre-merge)

Both guards pass against the current bridge code (`99116e1`). After merge + restart, both guards must still pass. Run them against the checked-out code before merging.

---

## 4. Quick reference

```bash
# On live box
su - itznavpreet
cd /opt/aegis
git fetch origin
git checkout origin/main    # after merge
# Restart bridge per section 2 above
```

**Rollback:** If bridge fails to start, the old code is still on disk at the previous HEAD. Checkout the previous commit and restart with the same command.
