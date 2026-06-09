# Helios — Aegis v1


**Aegis** is a Linux-resident AI symbiote. v1 is a minimal end-to-end loop:
text in → NCP brain → renderer chain → text out, with SQLite episodic memory
and a 6-scalar neuromodulator bus.

Runs as a long-lived daemon on Helios1 (16 GB no-GPU GCP VM, europe-west3-a).
Communicates over a unix socket at `/tmp/aegis.sock` (the default in
`aegis/main.py:35`; override via the `AEGIS_SOCK` environment variable).
Connect with `aegis-cli`.

## Architecture
- Nexus — pub/sub bus + clock + neuromodulator state
  (6 scalars: reward, novelty, attention, patience, threat, trust)
- Hive — sensory encoders (text via MiniLM in v1)
- Brain — 41,361-param Liquid Neural Network (CfC + AutoNCP);
  random-initialised in v1 (untrained until the Crucible run)
- Mnemosyne — SQLite episode store + top-k cosine retrieval
  (~/.local/share/aegis/mnemosyne.db)
- Renderer — Gemini primary → Groq → Template fallback chain;
  budget 240 calls/day, Pacific reset

### Renderer Modules (aegis/renderer/)

| Block | File | Role |
|-------|------|------|
| 1.1 | `_quota.py` | Gemini daily budget cap (240 calls/day default, Pacific TZ, split reserve/record_success) |
| 4 | `dispatcher.py` | Chain owner — walks CHAIN=`[Gemini, Groq, Template]`, publishes `action.speak` on BUS, records provider attempts to `renderer_state.json` |
| 4 | `gemini.py` | Gemini adapter (`gemini-2.5-flash` via Google AI API), disabled thinking, transitional `run()` coroutine (post-cutover delete target) |
| 5 | `openai_compat.py` | Shared `OpenAICompatRenderer` base — reusable across Groq, Cerebras, etc. Configurable model, endpoint, env var, timeout. Shares prompt template with `gemini.py` |
| 5 | `groq.py` | Groq adapter — thin wrapper over `OpenAICompatRenderer` (`llama-3.3-70b-versatile` via Groq API) |
| — | `fallback.py` | Template fallback — offline/rate-limited terminator. Random greetings via `str.format()`, never raises |
| — | `__init__.py` | Exception taxonomy (`RendererError`, `QuotaExhausted`, `TransientError`) + `is_speaking()` flag |

Chain semantics: dispatcher walks adapters in order. Each adapter either returns text (success) or raises `RendererError`/`QuotaExhausted`/`TransientError`. The chain terminates at `fallback.py` (Template), which never raises. All attempts are recorded to `renderer_state.json` (see `aegis/observability/renderer_state.py`).

## Status
v1 live (2026-05-23). v1.1 polish in progress. Full docs in the Notion workspace.

## Install (Helios1)
    cd /opt/aegis
    uv venv                 # creates /opt/aegis/.venv (Python >= 3.11)
    uv pip install -e .
    mkdir -p ~/.config/aegis && $EDITOR ~/.config/aegis/secrets.env   # git-ignored keys
    nohup python -m aegis.main &   # current launch path (socket: /tmp/aegis.sock)
Then `aegis-cli` to talk to it over the socket.

> A systemd/aegis.service unit ships in the repo but is NOT the live launch path
> yet — the daemon currently runs via nohup.

## License
All rights reserved (for now).
