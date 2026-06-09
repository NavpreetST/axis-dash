# Systemd Hardening Runbook — Aegis Daemon

## Goal
Make `systemd aegis.service` safe to use without breaking state writes or socket
path alignment.

## Preconditions
- `systemd/aegis.service` patched with:
  - `AEGIS_SOCK=/tmp/aegis.sock` (aligns with bridge default)
  - `/var/lib/aegis` in `ReadWritePaths` (fixes `[Errno 30]` state writes)
- Live runtime is healthy under nohup before migration.

---

## Safe Stop Sequence

```bash
pkill -f 'aegis.web.server'          # stop bridge first
sudo systemctl stop aegis.service     # stop daemon (if running under systemd)
pkill -9 -f 'python.*aegis.main'      # kill any leftover nohup daemons
pkill -9 -f 'python.*aegis.web.server' # kill any leftover bridges
```

## Safe Start Sequence

```bash
sudo systemctl daemon-reload                           # pick up service file changes
sudo systemctl start aegis.service                     # start daemon under systemd
# Wait for /tmp/aegis.sock to appear (daemon boot ~5s)
sleep 5 && ls -l /tmp/aegis.sock
# Start bridge separately (systemd does not manage bridge)
HELIOS_TOKEN=test-token-12345 setsid \
  /opt/aegis/.venv/bin/python -m aegis.web.server \
  </dev/null >/tmp/bridge.log 2>&1 &
```

## Duplicate-Process Prevention
- `ExecStart` in `Type=simple` guarantees exactly one systemd-managed instance.
- The Stop sequence above kills leftover nohup processes before systemd start.
- Do NOT mix nohup and systemd — pick one runtime path.

## Post-Restart Smoke Checklist

```bash
# 1. Health
curl -s 'http://localhost:8080/health' -H 'Authorization: Bearer test-token-12345'
# Expected: 200, daemon_pid matches systemd PID, socket_path=/tmp/aegis.sock

# 2. Logs
timeout 3 curl -s 'http://localhost:8080/logs?token=test-token-12345'
# Expected: SSE stream with ": connected" and real events

# 3. Forge — list
curl -s 'http://localhost:8080/forge/list?token=test-token-12345'
# Expected: 200, {"tasks":[...]}

# 4. Forge — submit + status
curl -s -X POST 'http://localhost:8080/forge/submit?token=test-token-12345' \
  -H 'Content-Type: application/json' \
  -d '{"spec":"Add input validation"}'
# Expected: {"task_id":"..."}
curl -s 'http://localhost:8080/forge/<task_id>/status?token=test-token-12345'
# Expected: 200, "status":"completed" or "failed"

# 5. Auth rejection
curl -s 'http://localhost:8080/health'
# Expected: 401, {"detail":"auth_required"}
```

## Rollback to Nohup

```bash
sudo systemctl stop aegis.service
cd /opt/aegis && nohup /opt/aegis/.venv/bin/python -m aegis.main \
  </dev/null >/dev/null 2>&1 &
# Then start bridge with HELIOS_TOKEN=test-token-12345
```

## Bridge Note
The bridge is still manually nohup-managed. It is NOT covered by systemd.
Future work: add a separate `helios-bridge.service` or define explicit env/runbook
for the bridge lifecycle so both daemon and bridge are systemd-managed together.
