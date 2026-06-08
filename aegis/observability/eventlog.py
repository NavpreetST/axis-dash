"""Event log — append-only JSONL writer with frozen 8-field schema.

Schema is FROZEN at schema_version 1.  DO NOT add fields.
Source of truth: contracts/event.schema.json

Architecture:
  1. JSONL append (always) — writes to STATE_DIR/events/YYYY-MM-DD.jsonl
  2. Supabase mirror (optional) — batched upserts when SUPABASE_URL + key set
  3. B2 cold backup (optional) — periodic upload when B2 credentials set

Single-writer guarantee: only this module writes to the JSONL files.
No threading.Lock() needed — all writes go through append_event() which
is called from the async run() task or via the log_event() helper.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
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
    """Append a single event to today's JSONL file with fsync (crash-safe)."""
    # Validate the event has exactly the 8 frozen fields
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

    path = _today_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except (OSError, ValueError) as e:
        log.warning("eventlog: failed to append %s — %s", path, e)


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
    """Async wrapper: build event, append to JSONL, publish to BUS.

    Called from main.py's handle() and error handler.  The blocking
    fsync runs in a thread via asyncio.to_thread so the event loop
    is never stalled.
    """
    event = make_event(
        source=source,
        event_type=event_type,
        payload=_sanitize_for_json(payload),
        severity=severity,
        provenance=provenance,
        sensitivity=sensitivity,
    )
    await asyncio.to_thread(append_event, event)
    _warn_if_large()
    try:
        await BUS.publish("eventlog.write", event)
    except Exception as e:
        log.debug("eventlog: failed to publish to eventlog.write — %s", e)


# ---------------------------------------------------------------------------
# Async run entry point — subscribes to BUS events and writes them
# ---------------------------------------------------------------------------

async def run() -> None:
    """Listen to the BUS and append matching events to JSONL.

    This is the single writer task.  It subscribes to action.speak and
    intent.packet, writes JSONL, and publishes to eventlog.write for
    supabase_sync and b2_sync to consume.
    """
    log.info("eventlog writer running")

    # Subscribe to all bus topics we care about
    subs = {
        "action.speak": "chat_turn",
        "intent.packet": "chat_turn",
    }

    try:
        queues = {}
        for topic in subs:
            queues[topic] = BUS.subscribe(topic)
    except Exception as e:
        log.error("eventlog: failed to subscribe to BUS — %s", e)
        return

    async def _listen(topic: str, event_type: str) -> None:
        q = queues[topic]
        while True:
            try:
                msg = await q.get()
                raw_payload = dict(msg.payload) if msg.payload else {}
                payload = _sanitize_for_json(raw_payload)
                event = make_event(
                    source="aegis",
                    event_type=event_type,
                    payload=payload,
                    severity="info",
                )
                await asyncio.to_thread(append_event, event)
                _warn_if_large()
                try:
                    await BUS.publish("eventlog.write", event)
                except Exception as e:
                    log.debug("eventlog: failed to publish to eventlog.write — %s", e)
            except Exception as e:
                log.warning("eventlog: failed for topic %s — %s", topic, e)

    tasks = [asyncio.create_task(_listen(t, et)) for t, et in subs.items()]
    await asyncio.gather(*tasks, return_exceptions=True)
