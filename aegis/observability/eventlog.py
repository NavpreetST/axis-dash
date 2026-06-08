"""Event log — append-only JSONL writer with frozen 8-field schema.

Schema is FROZEN at schema_version 1.  DO NOT add fields.
Source of truth: contracts/event.schema.json

Architecture (single-writer, single-path):

  main.py (chat_turn / error) ──► log_event()
                                       │
                                       ▼
                                 BUS "eventlog.append"
                                       │
                                       ▼
                                  run() ──► append_event() ──► JSONL (fsync)
                                       │
                                       ▼
                                 BUS "eventlog.write"
                                  ╱            ╲
                          supabase_sync     b2_sync (reads JSONL files)

Every event enters via log_event(), hits local JSONL exactly once
(via the sole append_event() caller in run()), and is mirrored to
Supabase via the eventlog.write BUS topic.  B2 reads JSONL files
directly on a timer.

Single-writer guarantee: only append_event() in run() touches JSONL.
No threading.Lock() needed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from aegis.nexus.bus import BUS

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# FROZEN — do not add fields. 8 required fields only.
REQUIRED_FIELDS = frozenset({
    "schema_version",
    "timestamp",
    "source",
    "event_type",
    "payload",
    "severity",
    "provenance",
    "sensitivity",
})

# ---------------------------------------------------------------------------
# Load enum validation sets from contracts/event.schema.json (source of truth)
# ---------------------------------------------------------------------------

_CONTRACTS_PATH = (
    Path(__file__).resolve().parent.parent.parent / "contracts" / "event.schema.json"
)


def _load_enum_from_schema(property_name: str) -> frozenset[str]:
    """Load an enum set from the frozen JSON schema contract.

    Falls back to a hardcoded default if the schema file is missing
    (e.g. during tests that mock the path).
    """
    _DEFAULTS = {
        "source": frozenset({
            "notion", "antigravity", "opencode", "helios",
            "aegis", "coderabbit", "ci",
        }),
        "event_type": frozenset({
            "chat_turn", "error", "task_created", "task_updated", "task_done",
            "pr_opened", "review_posted", "gate_result", "merge", "drift_flag",
        }),
        "severity": frozenset({"info", "warn", "error", "critical"}),
        "sensitivity": frozenset({"public", "internal", "secret"}),
    }
    try:
        schema = json.loads(_CONTRACTS_PATH.read_text(encoding="utf-8"))
        values = schema["properties"][property_name]["enum"]
        return frozenset(values)
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as e:
        log.debug("eventlog: could not load %s from schema — using default: %s", property_name, e)
        return _DEFAULTS[property_name]


VALID_SOURCES = _load_enum_from_schema("source")
VALID_EVENT_TYPES = _load_enum_from_schema("event_type")
VALID_SEVERITIES = _load_enum_from_schema("severity")
VALID_SENSITIVITIES = _load_enum_from_schema("sensitivity")

STATE_DIR = Path(os.getenv("AEGIS_STATE_DIR", "/var/lib/aegis"))
EVENTS_DIR = STATE_DIR / "events"

MAX_FILE_BYTES = 50 * 1024 * 1024


def _sanitize_for_json(obj):
    """Recursively sanitize object to ensure JSON serializability."""
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    if isinstance(obj, dict):
        return {str(k): _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(item) for item in obj]
    return str(obj)


def make_event(
    *,
    source: str,
    event_type: str,
    payload: dict,
    severity: str = "info",
    provenance: dict | None = None,
    sensitivity: str = "internal",
) -> dict:
    """Construct a frozen-schema event dict.

    Validates all fields at write time — catches contract violations
    before they hit the JSONL file.
    """
    if source not in VALID_SOURCES:
        raise ValueError(f"invalid source: {source!r}")
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"invalid event_type: {event_type!r}")
    if severity not in VALID_SEVERITIES:
        raise ValueError(f"invalid severity: {severity!r}")
    if sensitivity not in VALID_SENSITIVITIES:
        raise ValueError(f"invalid sensitivity: {sensitivity!r}")

    return {
        "schema_version": SCHEMA_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "event_type": event_type,
        "payload": payload,
        "severity": severity,
        "provenance": provenance or {},
        "sensitivity": sensitivity,
    }


def _today_path() -> Path:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return EVENTS_DIR / f"{day}.jsonl"


def append_event(event: dict) -> None:
    """Append a single event to today's JSONL file with fsync (crash-safe).

    This is the SOLE code path that writes to JSONL files.
    Called only from run() via asyncio.to_thread — never from the event loop.

    If sensitivity == "secret", the payload is replaced with "<REDACTED>"
    before writing — secret payloads are never persisted to disk in plaintext.

    Raises on write/fsync failure so run() can skip the cloud mirror.
    """
    actual_keys = set(event.keys())
    if actual_keys != REQUIRED_FIELDS:
        missing = REQUIRED_FIELDS - actual_keys
        extra = actual_keys - REQUIRED_FIELDS
        parts = []
        if missing:
            parts.append(f"missing: {sorted(missing)}")
        if extra:
            parts.append(f"extra: {sorted(extra)}")
        raise ValueError(f"event schema violation: {', '.join(parts)}")

    if event["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {SCHEMA_VERSION}, got {event['schema_version']}")

    # Redact secret payloads before persisting to disk
    write_event = event
    if event.get("sensitivity") == "secret":
        write_event = dict(event)
        write_event["payload"] = {"redacted": True, "reason": "sensitivity=secret"}

    path = _today_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(write_event, ensure_ascii=False, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _log_append_error(event: dict, error: Exception) -> None:
    """Log append failures to stderr with sensitivity-aware redaction."""
    sensitivity = event.get("sensitivity", "internal")
    try:
        if sensitivity == "secret":
            redacted = dict(event)
            redacted["payload"] = "<REDACTED>"
            detail = json.dumps(redacted, ensure_ascii=False)
        else:
            detail = json.dumps({
                "timestamp": event.get("timestamp"),
                "source": event.get("source"),
                "event_type": event.get("event_type"),
            }, ensure_ascii=False)
        log.warning("eventlog: append failed — %s: %s", error, detail)
    except Exception:
        log.warning("eventlog: append failed — %s (redaction error)", error)


def _warn_if_large() -> None:
    try:
        size = _today_path().stat().st_size
        if size > MAX_FILE_BYTES:
            log.warning(
                "eventlog: %s is %d MB (threshold %d MB)",
                _today_path().name,
                size // (1024 * 1024),
                MAX_FILE_BYTES // (1024 * 1024),
            )
    except (FileNotFoundError, OSError):
        pass


# ---------------------------------------------------------------------------
# Async helpers — for main.py to call from async context
# ---------------------------------------------------------------------------

async def log_event(
    *,
    source: str,
    event_type: str,
    payload: dict,
    severity: str = "info",
    provenance: dict | None = None,
    sensitivity: str = "internal",
) -> None:
    """Publish an event to the internal BUS for sole-writer append.

    This does NOT call append_event() directly (no thread-pool race).
    It publishes to 'eventlog.append'; run() picks it up and is the
    sole caller of append_event().
    """
    event = make_event(
        source=source,
        event_type=event_type,
        payload=_sanitize_for_json(payload),
        severity=severity,
        provenance=provenance,
        sensitivity=sensitivity,
    )
    try:
        await BUS.publish("eventlog.append", event)
    except Exception as e:
        log.debug("eventlog: failed to publish to eventlog.append — %s", e)


# ---------------------------------------------------------------------------
# Async run entry point — sole writer, single path
# ---------------------------------------------------------------------------

async def run() -> None:
    """Sole JSONL writer — subscribes to eventlog.append, writes, mirrors.

    This is the ONLY task that calls append_event().  All events
    (chat_turn, error, task_created, etc.) enter via log_event() which
    publishes to the 'eventlog.append' BUS topic.  After writing to
    JSONL, this task publishes to 'eventlog.write' for supabase_sync
    and b2_sync to consume.
    """
    log.info("eventlog writer running")

    try:
        q = BUS.subscribe("eventlog.append")
    except Exception as e:
        log.error("eventlog: failed to subscribe to eventlog.append — %s", e)
        return

    while True:
        try:
            msg = await q.get()
            event = dict(msg.payload) if msg.payload else {}
            if not event:
                continue
            try:
                await asyncio.to_thread(append_event, event)
            except (OSError, ValueError) as e:
                _log_append_error(event, e)
                continue  # skip cloud mirror — local append failed
            _warn_if_large()
            try:
                await BUS.publish("eventlog.write", event)
            except Exception as e:
                log.debug("eventlog: failed to publish to eventlog.write — %s", e)
        except Exception as e:
            log.warning("eventlog: writer error — %s", e)
