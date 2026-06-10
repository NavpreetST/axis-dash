# /api/status — Project State Endpoint

## Route

```http
GET /api/status
```

## Auth

`Authorization: Bearer <HELIOS_TOKEN>` header (same as `/health`).  
Rejects with 401 if token missing or wrong.

## Response Shape

```json
{
  "phase": "Phase 1 — Memory & Daily Use",
  "exit_criteria": {
    "T1_chat_memory": true,
    "T2_preference": true,
    "T3_update_supersede": true,
    "T4_recall_ranking": true,
    "T5_decay": true,
    "T6_project_awareness": false,
    "T7_website": true
  },
  "last_merge": {
    "sha": "3432f97",
    "pr": "#53 — mobile responsive",
    "merged_at": "2026-06-10T00:08:45Z"
  },
  "open_prs": 0,
  "daemon_uptime_seconds": 12345,
  "renderer_chain": ["gemini", "nim_nano", "groq", "template"],
  "memory": {
    "t1_episodic": true,
    "t2_semantic": true,
    "t4_skills": true,
    "recency_bias": true,
    "upsert_conflict": true,
    "gc_retention": true
  }
}
```

## Field Descriptions

| Field | Type | Sourced From | Description |
|-------|------|-------------|-------------|
| `phase` | string | Hardcoded (update per phase) | Current phase name from DRIFT.md §1 |
| `exit_criteria` | object | Hardcoded (update per phase exit) | Map of T1-T7 booleans matching DRIFT.md §2 Phase 1 exit criteria |
| `last_merge.sha` | string | `git log -1 --format="%H"` | SHA of most recent commit on main |
| `last_merge.pr` | string | `git log -1 --format="%s"` parsed | PR reference extracted from commit message |
| `last_merge.merged_at` | string | `git log -1 --format="%cI"` | ISO 8601 timestamp of last commit |
| `open_prs` | int | `gh pr list --state open --json number \| jq length` | Count of currently open PRs |
| `daemon_uptime_seconds` | int | `/proc/<pid>/stat` (reuse `_daemon_uptime_seconds_for_pid`) | Seconds since daemon started |
| `renderer_chain` | string[] | Hardcoded | Ordered list of renderers in fallback chain |
| `memory.t1_episodic` | bool | Hardcoded (true once T1 write/retrieve live) | Episodic memory tier active |
| `memory.t2_semantic` | bool | Hardcoded (true once T2 module deployed) | Semantic fact store active |
| `memory.t4_skills` | bool | Hardcoded (true once T4 module deployed) | Procedural skill store active |
| `memory.recency_bias` | bool | Hardcoded (true after recency formula applied) | Recency-boosted scoring in retrieve |
| `memory.upsert_conflict` | bool | Hardcoded (true after upsert_conflict deployed) | T2 conflict resolution active |
| `memory.gc_retention` | bool | Hardcoded (true after reap_old_episodes deployed) | Episode retention GC active |

## Field Sourcing Details

### Hardcoded fields
`phase`, `exit_criteria`, `renderer_chain`, `memory.*` are hardcoded constants updated manually per phase/merge. This is intentional — they change infrequently and hardcoding avoids fragile runtime detection. Automatable later via DRIFT.md parser.

### Git-sourced fields
`last_merge` is populated by running:

```python
import subprocess, json
def _git_last_merge() -> dict:
    try:
        sha = subprocess.run(["git", "log", "-1", "--format=%H"], capture_output=True, text=True, timeout=5).stdout.strip()
        msg = subprocess.run(["git", "log", "-1", "--format=%s"], capture_output=True, text=True, timeout=5).stdout.strip()
        dt  = subprocess.run(["git", "log", "-1", "--format=%cI"], capture_output=True, text=True, timeout=5).stdout.strip()
        # Parse PR number from message: "feat: ... (#NN)" or "Merge pull request #NN"
        import re
        m = re.search(r'#(\d+)', msg)
        pr = f"#{m.group(1)}" if m else ""
        return {"sha": sha, "pr": pr, "merged_at": dt}
    except Exception:
        return {"sha": "", "pr": "", "merged_at": ""}
```

### GitHub CLI
`open_prs` runs `gh pr list --state open --json number --jq 'length'` with a 5s timeout. Returns 0 on failure (offline/unauth).

### Daemon uptime
Reuses existing `_daemon_uptime_seconds_for_pid()` from `server.py` — reads `/proc/<pid>/stat` create_time, subtracts from `time.time()`.

## Error Handling

- Missing `HELIOS_TOKEN` → 401
- Git commands fail → `last_merge` returned as empty strings (never 500)
- `gh` command fails → `open_prs` returned as 0 (never 500)
- All other fields are static/hardcoded — never 500

## Box Agent Build Prompt

```markdown
Target: Helios, File: aegis/web/server.py
Branch: feat/api-status-endpoint (create from main)

Add a new FastAPI route after /health (around line 757):

@app.get("/api/status")
async def api_status(request: Request) -> dict:
    \"\"\"Project state snapshot for "what's going on?" context.\"\"\"
    # Auth
    if not _token_matches(_extract_bearer(request.headers.get("authorization"))):
        raise HTTPException(401, detail="auth_required")

    # Git last merge
    last_merge = _git_last_merge()  # helper function

    # Open PR count via gh CLI
    open_prs = _count_open_prs()    # helper function

    # Daemon uptime (reuse existing)
    pid = _find_daemon_pid()
    uptime = _daemon_uptime_seconds_for_pid(pid)

    return {
        "phase": "Phase 1 — Memory & Daily Use",
        "exit_criteria": {...},
        "last_merge": last_merge,
        "open_prs": open_prs,
        "daemon_uptime_seconds": uptime,
        "renderer_chain": ["gemini", "nim_nano", "groq", "template"],
        "memory": {...},
    }

Add two helper functions at module level:
- _git_last_merge() -> dict — runs git log -1, parses PR number
- _count_open_prs() -> int — runs gh pr list --state open --json number

Timeout both at 5s, return empty/0 on failure.

Do NOT change /health, /chat, or any existing route.
Do NOT add new dependencies.
Do NOT restart the daemon — code only.

Verify:
- python -c "compile(open('aegis/web/server.py').read(), 'aegis/web/server.py', 'exec')" → OK
- python -m pytest tests/ --tb=short -q | tail -5 → 0 new failures
```

## Wiring into Chat Context

After `/api/status` is deployed, modify `aegis/mnemosyne/retrieve.py`:

1. On startup (in `run()`), fetch `GET http://localhost:8080/api/status` with `Authorization: Bearer <HELIOS_TOKEN>`.
2. Store the response as a seed row in episodes with `action='seed'` and text `"STATUS: {json}"`.
3. Refresh every 60s via a background asyncio task.
4. When user asks "what's going on?", the seed row is retrieved (action='seed' rows are always included) and prepended to context — the Gemini prompt then reads the status and answers naturally.

This avoids changing the retrieval pipeline — seed rows already get a score of 1.0 and are always included in results.
