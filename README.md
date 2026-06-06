# Helios — Aegis v1

**Aegis** is a Linux-resident AI symbiote. v1 is a minimal end-to-end loop:
text in → NCP brain → Gemini renderer → text out, with SQLite episodic memory
and a 6-scalar neuromodulator bus.

Runs as a long-lived daemon on Helios1 (16 GB no-GPU GCP VM, europe-west3-a).
Communicates over a unix socket at /run/aegis/aegis.sock. Connect with `aegis-cli`.

## Architecture
- Nexus — pub/sub bus + clock + neuromodulator state
  (6 scalars: reward, novelty, attention, patience, threat, trust)
- Hive — sensory encoders (text via MiniLM in v1)
- Brain — 41,361-param Liquid Neural Network (CfC + AutoNCP);
  random-initialised in v1 (untrained until the Crucible run)
- Mnemosyne — SQLite episode store + top-k cosine retrieval
  (~/.local/share/aegis/mnemosyne.db)
- Renderer — gemini-2.5-flash → Groq → template fallback chain
  (budget 240 calls/day, Pacific reset)

## Status
v1 live (2026-05-23). v1.1 polish in progress. Full docs in the Notion workspace.

## Install (Helios1)
    cd /opt/aegis
    uv venv                 # creates /opt/aegis/.venv (Python >= 3.11)
    uv pip install -e .
    mkdir -p ~/.config/aegis && $EDITOR ~/.config/aegis/secrets.env   # git-ignored keys
    nohup python -m aegis.main &        # current launch path
Then `aegis-cli` to talk to it over the socket.

> A systemd/aegis.service unit ships in the repo but is NOT the live launch path
> yet — the daemon currently runs via nohup.

## License
All rights reserved (for now).