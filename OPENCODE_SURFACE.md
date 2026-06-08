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
4. Route model calls through opencode.json config pointing at budgeted backend
5. Cleanup via `DELETE /session/:id`

This avoids per-task cold boot and shares MCP/LSP connections across tasks.
