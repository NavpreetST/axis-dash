"""Forge Dispatcher — submits coding tasks to opencode and captures results.

Each task runs in an isolated sandbox workdir under /opt/aegis/forge/<task-id>/.
The dispatcher creates the session, sends the prompt, captures diffs/files/logs,
and stores results for the gate stage.

CONCURRENCY: A semaphore caps parallel task execution at
MAX_CONCURRENT_FORGE_TASKS (default 2, tunable via env var) to avoid
OOM on the 16 GB host. Additional submissions are queued automatically.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path

from aegis.forge.manager import FORGE_BASE, ForgeManager

log = logging.getLogger(__name__)

# Max parallel forge tasks. This host has 16 GB RAM, no GPU — each
# opencode worker consumes ~2-4 GB. Cap at 2 by default to prevent OOM.
MAX_CONCURRENT_FORGE_TASKS = int(os.getenv("AEGIS_FORGE_MAX_CONCURRENT", "2"))


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    GATED = "gated"  # passed gate, ready for owner review
    REJECTED = "rejected"  # failed gate


@dataclass
class ForgeTask:
    id: str
    spec: str  # the coding task description
    status: TaskStatus = TaskStatus.PENDING
    session_id: str | None = None
    workdir: str | None = None
    diffs: list[dict] = field(default_factory=list)
    files_created: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    logs: str = ""
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    gate_result: dict | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


# In-memory task registry (persisted to JSON on disk)
_tasks: dict[str, ForgeTask] = {}
_tasks_file = FORGE_BASE / "tasks.json"


def _load_tasks() -> None:
    global _tasks
    if _tasks_file.exists():
        try:
            data = json.loads(_tasks_file.read_text())
            _tasks = {k: ForgeTask(**v) for k, v in data.items()}
        except Exception:
            _tasks = {}


def _save_tasks() -> None:
    _tasks_file.parent.mkdir(parents=True, exist_ok=True)
    _tasks_file.write_text(
        json.dumps(
            {k: v.to_dict() for k, v in _tasks.items()},
            indent=2,
            default=str,
        )
    )


def get_task(task_id: str) -> ForgeTask | None:
    return _tasks.get(task_id)


def list_tasks() -> list[ForgeTask]:
    return list(_tasks.values())


class ForgeDispatcher:
    """Dispatches coding tasks to opencode in isolated sandboxes.

    Max ``MAX_CONCURRENT_FORGE_TASKS`` run in parallel; additional
    submissions queue automatically behind the semaphore.
    """

    _semaphore: asyncio.Semaphore | None = None

    def __init__(self, manager: ForgeManager) -> None:
        self._manager = manager
        _load_tasks()
        if ForgeDispatcher._semaphore is None:
            ForgeDispatcher._semaphore = asyncio.Semaphore(MAX_CONCURRENT_FORGE_TASKS)

    async def submit(self, spec: str) -> ForgeTask:
        """Submit a new coding task. Returns task with ID."""
        task_id = uuid.uuid4().hex[:12]
        workdir = FORGE_BASE / task_id
        workdir.mkdir(parents=True, exist_ok=True)

        task = ForgeTask(
            id=task_id,
            spec=spec,
            workdir=str(workdir),
        )
        _tasks[task_id] = task
        _save_tasks()

        log.info("forge task submitted: %s — %s", task_id, spec[:80])
        return task

    async def execute(self, task_id: str) -> ForgeTask:
        """Execute a task: create session, send prompt, capture results."""
        task = _tasks.get(task_id)
        if task is None:
            raise KeyError(f"unknown task: {task_id}")
        if task.status != TaskStatus.PENDING:
            raise ValueError(f"task {task_id} already {task.status.value}")

        sem = ForgeDispatcher._semaphore
        if sem is None:
            raise RuntimeError("ForgeDispatcher not initialized")
        async with sem:
            workdir = Path(task.workdir)
            task.status = TaskStatus.RUNNING
            _save_tasks()

            try:
                # Create opencode session
                session_id = await self._manager.create_session(workdir)
                task.session_id = session_id

                # Build the prompt with workdir context
                prompt = (
                    f"Work in directory: {workdir}\n\n"
                    f"Task: {task.spec}\n\n"
                    "Make the necessary changes. Show me the diff when done."
                )

                # Send prompt and wait for response
                await self._manager.send_prompt(session_id, prompt)

                # Capture diffs
                diffs = await self._manager.get_diffs(session_id)
                task.diffs = diffs

                # Parse files from diffs
                for diff in diffs:
                    path = diff.get("path", diff.get("filePath", ""))
                    if diff.get("status") == "added":
                        task.files_created.append(path)
                    elif diff.get("status") == "modified":
                        task.files_modified.append(path)

                # Capture messages for logs
                messages = await self._manager.get_messages(session_id)
                task.logs = json.dumps(messages, indent=2, default=str)

                task.status = TaskStatus.COMPLETED
                task.completed_at = time.time()
                log.info(
                    "forge task completed: %s — %d diffs, +%d ~%d files",
                    task_id,
                    len(diffs),
                    len(task.files_created),
                    len(task.files_modified),
                )

            except Exception as e:
                task.status = TaskStatus.FAILED
                task.error = str(e)
                task.completed_at = time.time()
                log.error("forge task failed: %s — %s", task_id, e)

            finally:
                _save_tasks()
                # Cleanup: delete session but keep workdir for gate stage
                if task.session_id:
                    with contextlib.suppress(Exception):
                        await self._manager.delete_session(task.session_id)

        return task

    async def cleanup(self, task_id: str) -> None:
        """Remove sandbox workdir and task record."""
        task = _tasks.get(task_id)
        if task and task.workdir:
            workdir = Path(task.workdir)
            if workdir.exists():
                shutil.rmtree(workdir, ignore_errors=True)
                log.info("forge sandbox cleaned: %s", task_id)
        _tasks.pop(task_id, None)
        _save_tasks()

    def reap_completed(self, max_age_seconds: float = 3600) -> int:
        """Remove completed tasks older than max_age. Returns count removed."""
        now = time.time()
        to_remove = []
        for tid, task in _tasks.items():
            if (
                task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.REJECTED)
                and task.completed_at
                and (now - task.completed_at) > max_age_seconds
            ):
                to_remove.append(tid)
        for tid in to_remove:
            asyncio.create_task(self.cleanup(tid))
        return len(to_remove)
