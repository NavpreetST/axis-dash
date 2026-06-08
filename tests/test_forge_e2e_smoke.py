"""Forge E2E smoke — real opencode run, trivial task, full lifecycle.
 
These tests are OPT-IN.  CI never runs them.  To run locally:
 
    AEGIS_FORGE_E2E=1 pytest tests/test_forge_e2e_smoke.py -v
 
Backend: ``opencode run --format json`` (not serve).  The serve API doesn't
surface tool-calling for no-login free models; ``run`` drives opencode's own
agent loop and produces real diffs.
 
Lifecycle: SUBMIT -> (task_created event) -> EXECUTE -> (task_done event) ->
GATE -> (gate_result event) -> CLEANUP.  Gate MUST block push
(request_owner_approval returns False).  All events use the frozen
8-field schema — no new event_types invented.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

import pytest

from aegis.forge import dispatcher as forge_dispatcher_mod
from aegis.forge import manager as forge_manager_mod
from aegis.forge.dispatcher import ForgeDispatcher, TaskStatus
from aegis.forge.gate import GateStage
from aegis.forge.manager import ForgeManager
from aegis.observability import eventlog

log = logging.getLogger(__name__)

_SKIP_REASON = "set AEGIS_FORGE_E2E=1 to run the real forge e2e smoke"


def _make_forge_event(
    event_type: str,
    payload: dict,
    *,
    severity: str = "info",
    sensitivity: str = "internal",
) -> dict:
    """Build a frozen-schema event for forge lifecycle.

    Uses source='aegis' (forge is an aegis subsystem; 'forge' is not
    in the event schema's source enum).  event_type must be one of
    the valid schema types: task_created, task_done, gate_result, error.
    """
    return eventlog.make_event(
        source="aegis",
        event_type=event_type,
        payload=payload,
        severity=severity,
        provenance={"test": "e2e_smoke", "runner": "pytest"},
        sensitivity=sensitivity,
    )


class TestForgeE2ESmoke:
    """End-to-end forge smoke against the real opencode binary.

    Requires:
      - ``opencode`` binary on PATH (or ``OPENCODE_BIN`` env var)
      - ``AEGIS_FORGE_E2E=1`` env var (opt-in)
    """

    @pytest.mark.asyncio
    async def test_e2e_lifecycle(self, monkeypatch, tmp_path: Path) -> None:
        if not os.getenv("AEGIS_FORGE_E2E"):
            pytest.skip(_SKIP_REASON)

        events_dir = tmp_path / "forge-events"
        monkeypatch.setattr(eventlog, "EVENTS_DIR", events_dir)

        # Load the Groq API key from secrets.env so the forge server can
        # authenticate with Groq when processing prompts.
        _secrets_path = Path.home() / ".config" / "aegis" / "secrets.env"
        if _secrets_path.exists():
            for line in _secrets_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    monkeypatch.setenv(k.strip(), v.strip())

        # Use a temp forge base so opencode doesn't discover the project
        # opencode.json (which causes 500 on session creation in opencode 1.16.2)
        forge_base = tmp_path / "forge-sandbox"
        monkeypatch.setattr(forge_manager_mod, "FORGE_BASE", forge_base)
        monkeypatch.setattr(forge_dispatcher_mod, "FORGE_BASE", forge_base)

        # NOTE: The forge manager's sandbox HOME + OPENCODE_CONFIG env var
        # (set by ForgeManager._ensure_sandbox) prevents opencode from
        # loading the user-level or project-level config.  No swap needed.
        # No serve server is started — each task runs as an ephemeral
        # ``opencode run`` subprocess in the sandbox workdir.

        t_start = time.perf_counter()

        try:
            dispatcher = ForgeDispatcher(ForgeManager())

            # 2. SUBMIT trivial task
            spec = (
                "Create a file called hello.py with a function hello() "
                "that returns the string 'hello from forge'"
            )
            task = await dispatcher.submit(spec)
            assert task.id
            assert task.status == TaskStatus.PENDING

            await eventlog.write_and_mirror(
                _make_forge_event(
                    "task_created",
                    {"task_id": task.id, "spec": spec[:80]},
                )
            )
            log.info("e2e: task submitted — %s", task.id)

            # 3. EXECUTE — real opencode run with big-pickle
            task = await dispatcher.execute(task.id)
            assert task.status == TaskStatus.COMPLETED, f"task {task.id} failed: {task.error}"
            assert task.error is None, f"task {task.id} has error: {task.error}"
            assert len(task.diffs) > 0, "expected at least 1 real diff — big-pickle must call write/edit"

            log.info(
                "e2e: task completed — %d diffs, +%d ~%d files",
                len(task.diffs),
                len(task.files_created),
                len(task.files_modified),
            )

            await eventlog.write_and_mirror(
                _make_forge_event(
                    "task_done",
                    {
                        "task_id": task.id,
                        "status": task.status.value,
                        "diffs": len(task.diffs),
                        "files_created": len(task.files_created),
                        "files_modified": len(task.files_modified),
                    },
                )
            )

            # 4. VERIFY artifact
            workdir = Path(task.workdir)
            hello_py = workdir / "hello.py"
            assert hello_py.exists(), "hello.py should exist after task"
            content = hello_py.read_text()
            assert "def hello(" in content
            assert "hello from forge" in content

            # 5. GATE — must BLOCK push on lint failure
            # First: write bad-format code to trigger lint failure (gate blocking)
            hello_py.write_text(
                "def hello():\n   return \"hello from forge\"\n"
            )
            gate = GateStage(task.workdir)
            gate_result = await gate.run_all()
            assert not gate_result.overall_passed, (
                "gate MUST block — lint should reject 3-space indent"
            )
            assert not gate_result.lint_passed, "lint MUST fail on 3-space indent"
            log.info(
                "e2e: gate BLOCKED on lint failure — lint=%s, tests=%s, build=%s",
                gate_result.lint_passed,
                gate_result.test_passed,
                gate_result.build_passed,
            )

            # 6. Owner approval gate — must block too
            approved = await gate.request_owner_approval(task.id, gate_result)
            assert approved is False, (
                "gate must NOT auto-approve — request_owner_approval must return False by default"
            )

            await dispatcher.complete_gate(task.id, gate_result, approved)

            await eventlog.write_and_mirror(
                _make_forge_event(
                    "gate_result",
                    {
                        "task_id": task.id,
                        "overall_passed": gate_result.overall_passed,
                        "owner_approved": approved,
                        "gate_ms": gate_result.gate_ms,
                    },
                )
            )
            log.info(
                "e2e: gate done — overall_passed=%s, owner_approved=%s, %dms",
                gate_result.overall_passed,
                approved,
                gate_result.gate_ms,
            )

            # 7. CLEANUP — prove sandbox removed
            await dispatcher.cleanup(task.id)
            assert not workdir.exists(), "workdir should be removed after cleanup"
            log.info("e2e: sandbox cleaned")

            # 8. Verify events persisted to JSONL
            today_path = eventlog._today_path()
            assert today_path.exists(), "event JSONL should exist"

            raw = today_path.read_text(encoding="utf-8").strip()
            lines = [json.loads(ln) for ln in raw.split("\n") if ln.strip()]
            forge_events = [
                e
                for e in lines
                if e.get("source") == "aegis"
                and e.get("event_type") in ("task_created", "task_done", "gate_result")
            ]
            assert len(forge_events) >= 3, f"expected >= 3 forge events, got {len(forge_events)}"
            event_types = {e["event_type"] for e in forge_events}
            for expected in ("task_created", "task_done", "gate_result"):
                assert expected in event_types, (
                    f"expected {expected} event in JSONL, got {event_types}"
                )
            log.info("e2e: forge events in JSONL — %s", sorted(event_types))

        except Exception:
            log.exception("e2e smoke failed")
            raise
        finally:
            elapsed = time.perf_counter() - t_start
            log.info("e2e: complete in %.1fs", elapsed)
