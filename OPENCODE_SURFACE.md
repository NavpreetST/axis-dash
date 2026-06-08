# OpenCode Programmatic Surface — Confirmed v1.16.2

## Invocation Modes

### 1. Server Mode (preferred for Helios)
```bash
opencode serve --port 4096 --hostname 127.0.0.1
# Auth: OPENCODE_SERVER_PASSWORD=secret opencode serve
```
- Headless HTTP server, OpenAPI 3.1 spec at `/doc`
- SSE event stream at `/event` and `/global/event`
- Attach mode: `opencode run --attach http://localhost:4096 "prompt"` reuses server sessions

### 2. One-shot CLI
```bash
opencode run --format json --dangerously-skip-permissions \
  --model provider/model "your prompt" --dir /workdir
```
- Spawns ephemeral server internally, runs prompt, exits
- `--format json` streams raw JSON events to stdout
- `--attach` skips cold-boot by reusing existing server

## Session Lifecycle

| Step | Server Mode | CLI Mode |
|------|-------------|----------|
| Create | `POST /session` → `{id}` | Auto-created |
| Send prompt | `POST /session/:id/message` with `{parts: [{type:"text", text:"..."}]}` | Arg is the prompt |
| Async send | `POST /session/:id/prompt_async` → 204, poll SSE | N/A |
| Get diffs | `GET /session/:id/diff` → `FileDiff[]` | Captured in JSON stream |
| Get messages | `GET /session/:id/message` → `Message[]` | In stdout |
| Abort | `POST /session/:id/abort` | Ctrl+C |
| Cleanup | `DELETE /session/:id` | Auto on exit |

## Structured Result Capture

- **Diffs**: `GET /session/:id/diff` returns file-level diffs (paths + hunks)
- **JSON output**: `opencode run --format json` streams events: `message.updated`, `session.created`, `session.idle`, etc.
- **Export**: `opencode export <sessionID>` → full session JSON (with `--sanitize`)
- **DB query**: `opencode db query --format json` → raw SQLite access

## Model Configuration

### Per-run override
```bash
opencode run --model openrouter/anthropic/claude-sonnet-4 "prompt"
```

### Config file (opencode.json)
```jsonc
{
  "provider": {
    "my-proxy": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Routed Backend",
      "options": { "baseURL": "http://127.0.0.1:PORT/v1" },
      "models": {
        "routed-model": {
          "name": "Routed Model",
          "limit": { "context": 128000, "output": 65536 }
        }
      }
    }
  }
}
```

### Auth
- Stored in `~/.local/share/opencode/auth.json`
- Also loaded from env vars or `.env` files
- Server auth: `OPENCODE_SERVER_PASSWORD` / `OPENCODE_SERVER_USERNAME`

## Key Environment Variables

| Variable | Purpose |
|----------|---------|
| `OPENCODE_SERVER_PASSWORD` | Basic auth for serve |
| `OPENCODE_CONFIG` | Path to config file |
| `OPENCODE_CONFIG_CONTENT` | Inline JSON config |
| `OPENCODE_PERMISSION` | Inline permissions JSON |
| `OPENCODE_LOG_LEVEL` | DEBUG/INFO/WARN/ERROR |
| `OPENCODE_DISABLE_AUTOCOMPACT` | Disable context compaction |

## Known Issues

- `opencode run` had session-creation bugs in older versions (#28407, #13851)
- Default permissions are restrictive; use `--dangerously-skip-permissions` or configure in opencode.json
- Server mode with `--attach` is more reliable for CI than raw `run`

## Chosen Integration Pattern for Helios

**Server mode** (`opencode serve`) running as a managed asyncio subprocess:
1. Start `opencode serve --port 0` (OS picks port) at daemon boot
2. Submit tasks via HTTP `POST /session` + `POST /session/:id/message`
3. Capture results via `GET /session/:id/diff`
4. Route model calls through opencode.json config pointing at Groq (free tier — no DAILY_BUDGET drain)
5. Cleanup via `DELETE /session/:id`

This avoids per-task cold boot and shares MCP/LSP connections across tasks.

### Forge Server Hardening (v1.16.2)

**Bind address**: The ForgeManager always starts `opencode serve` with
`--hostname 127.0.0.1`. The server is NEVER exposed on 0.0.0.0. Confirmed by
source inspection (`aegis/forge/manager.py` line 132).

**Auth**: A random 32-byte `OPENCODE_SERVER_PASSWORD` is generated at module
load (`secrets.token_urlsafe(32)`) and injected into the server subprocess env.
The httpx client uses `BasicAuth("opencode", password)` for every request. An
unauth'd request to the server will be rejected. This prevents the pre-1.1.10
RCE vector (unauth'd local server).

**Sandbox env scrubbing**: The server subprocess receives a sanitized
environment. `_sanitize_env()` in `manager.py` is a **strict allowlist** —
ONLY keys in `_SANDBOX_ALLOWLIST` (PATH, HOME, USER, LANG, LC_ALL, SHELL,
TERM, TMPDIR, OPENCODE_BIN, OPENCODE_LOG_LEVEL, OPENCODE_CONFIG,
OPENCODE_CONFIG_CONTENT, OPENCODE_PERMISSION, AEGIS_FORGE_DIR) reach the
worker. Everything else (API keys, tokens, SSH agent, git credentials) is
STRIPPED. `CODERABBIT_API_KEY` is explicitly NOT in the allowlist — it is
declared as `_CR_TOKEN_VAR` in manager.py for reference but is passed to
the cr CLI via `--api-key` flag in the gate step, never via environment.

**Concurrency cap**: `MAX_CONCURRENT_FORGE_TASKS` (default 2, env override
`AEGIS_FORGE_MAX_CONCURRENT`) limits parallel opencode runs via an asyncio
Semaphore. The host has 16 GB RAM, no GPU; each opencode worker consumes
~2-4 GB. This prevents OOM.

**Gate stage**: After a forge task completes, `GateStage.run_all()` runs
lint → test → build → cr review → owner sequentially with short-circuit on
lint/test/build failure. The CodeRabbit CLI (`cr` v0.5.4) reviews diffs via
`cr review --plain --type uncommitted --dir <workdir> --api-key <token>`.
cr is advisory by default (findings surface at the owner gate, no hard block).
If cr finds issues, a fix-pass loop-back feeds `cr --prompt-only` output to the
opencode agent (max 2 iterations). Only after all pass AND the owner explicitly
approves (`request_owner_approval`) is a push permitted. The smoke path produces
a GATED result, never an auto-push.

## Budgeter Seam

**Current choice**: Model calls route directly to Groq (free tier, no
DAILY_BUDGET drain) via `opencode.json`. This is deliberate — the budgeter
(P3.5, Helios renderer) chains its own API calls and does NOT route through
the opencode server. The forge worker has unlimited Groq access during the
free-tier phase; no metering is applied.

**Provider config** (`opencode.json` — the single switch):
```jsonc
{
  "provider": {
    "groq": {
      "npm": "@ai-sdk/groq",
      "name": "Groq Direct",
      "models": {
        "llama-3.3-70b-versatile": {
          "name": "Llama 3.3 70B",
          "limit": { "context": 128000, "output": 32768 }
        }
      }
    }
  },
  "model": "groq/llama-3.3-70b-versatile"
}
```

**How to switch to metered** (single seam — no code changes):
Replace only the `provider` + `model` keys in `opencode.json` with a
P3.5-compatible `openai-compatible` provider pointing at the budgeter
endpoint. Nothing in `manager.py` or `dispatcher.py` needs changing.

```jsonc
{
  "provider": {
    "budgeter-proxy": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "P3.5 Budgeter",
      "options": { "baseURL": "http://127.0.0.1:PORT/v1" },
      "models": {
        "metered-model": {
          "name": "Budgeted Model",
          "limit": { "context": 128000, "output": 32768 }
        }
      }
    }
  },
  "model": "budgeter-proxy/metered-model"
}
```

This is the documented seam for runtime metering when moving off the free
tier — one file, two keys, zero code changes.
