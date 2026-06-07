import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

# Event directory: defaults to /var/lib/aegis/events
STATE_DIR = Path(os.getenv("AEGIS_STATE_DIR", "/var/lib/aegis"))
EVENTS_DIR = STATE_DIR / "events"

SCHEMA_VERSION = 1
_LOCK = threading.Lock()

# Strictly validate fields against the frozen schema contract (contracts/event.schema.json)
VALID_SOURCES = {"notion", "antigravity", "opencode", "helios", "aegis", "coderabbit", "ci", "navpreets"}
VALID_EVENT_TYPES = {"chat_turn", "error", "task_created", "task_updated", "task_done", "pr_opened", "review_posted", "gate_result", "merge", "drift_flag"}
VALID_SEVERITIES = {"info", "warn", "error", "critical"}
VALID_SENSITIVITIES = {"public", "internal", "secret"}


def log_event(
    source: str,
    event_type: str,
    payload: dict,
    severity: str = 'info',
    sensitivity: str = 'internal',
    provenance: dict | None = None
) -> None:
    # Explicit schema validations
    if source not in VALID_SOURCES:
        raise ValueError(f"Invalid source: {source}")
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"Invalid event_type: {event_type}")
    if severity not in VALID_SEVERITIES:
        raise ValueError(f"Invalid severity: {severity}")
    if sensitivity not in VALID_SENSITIVITIES:
        raise ValueError(f"Invalid sensitivity: {sensitivity}")
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")
    if provenance is not None and not isinstance(provenance, dict):
        raise ValueError("provenance must be a dict")

    timestamp = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    prov = provenance if provenance is not None else {}
    
    # Strictly conform to the 8 required fields, schema_version 1
    rec = {
        'schema_version': SCHEMA_VERSION,
        'timestamp': timestamp,
        'source': source,
        'event_type': event_type,
        'payload': payload,
        'severity': severity,
        'provenance': prov,
        'sensitivity': sensitivity
    }
    
    line = json.dumps(rec, ensure_ascii=False, separators=(',', ':')) + '\n'
    try:
        EVENTS_DIR.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            day = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            path = EVENTS_DIR / f"{day}.jsonl"
            with open(path, 'a', encoding='utf-8') as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
    except Exception as e:
        print(f"[log_event FAILED] {e}: {line}", file=sys.stderr)
