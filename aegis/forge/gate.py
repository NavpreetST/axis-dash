"""Forge Gate Stage — lint → test → build → owner gate.

Runs after opencode completes a task. Nothing commits/pushes without
clearing all gates. Git credentials stay OUT of opencode's reach.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class GateResult:
    lint_passed: bool = False
    lint_output: str = ""
    test_passed: bool = False
    test_output: str = ""
    build_passed: bool = False
    build_output: str = ""
    owner_approved: bool = False
    overall_passed: bool = False
    gate_ms: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class GateStage:
    """Lint → test → build → owner gate for forge task results."""

    def __init__(self, workdir: Path | str) -> None:
        self.workdir = Path(workdir)

    async def run_all(self) -> GateResult:
        """Run all gate checks sequentially. Short-circuit on first failure."""
        result = GateResult()
        t0 = time.perf_counter()

        # Gate 1: Lint
        result.lint_passed, result.lint_output = await self._run_lint()
        if not result.lint_passed:
            log.warning("gate: lint FAILED in %s", self.workdir)
            result.gate_ms = int((time.perf_counter() - t0) * 1000)
            return result

        # Gate 2: Tests
        result.test_passed, result.test_output = await self._run_tests()
        if not result.test_passed:
            log.warning("gate: tests FAILED in %s", self.workdir)
            result.gate_ms = int((time.perf_counter() - t0) * 1000)
            return result

        # Gate 3: Build
        result.build_passed, result.build_output = await self._run_build()
        if not result.build_passed:
            log.warning("gate: build FAILED in %s", self.workdir)
            result.gate_ms = int((time.perf_counter() - t0) * 1000)
            return result

        result.overall_passed = True
        result.gate_ms = int((time.perf_counter() - t0) * 1000)
        log.info("gate: ALL PASSED for %s (%dms)", self.workdir, result.gate_ms)
        return result

    async def _run_lint(self) -> tuple[bool, str]:
        """Run ruff check + format check on changed .py files."""
        changed_py = list(self.workdir.rglob("*.py"))
        if not changed_py:
            return True, "no Python files to lint"

        # Ruff check
        proc = await asyncio.create_subprocess_exec(
            "ruff",
            "check",
            *[str(f) for f in changed_py],
            cwd=str(self.workdir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        check_ok = proc.returncode == 0

        # Ruff format check
        proc2 = await asyncio.create_subprocess_exec(
            "ruff",
            "format",
            "--check",
            *[str(f) for f in changed_py],
            cwd=str(self.workdir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout2, _ = await proc2.communicate()
        format_ok = proc2.returncode == 0

        output = f"ruff check: {stdout.decode()}\nruff format: {stdout2.decode()}"
        return check_ok and format_ok, output

    async def _run_tests(self) -> tuple[bool, str]:
        """Run pytest if tests/ exists in workdir."""
        tests_dir = self.workdir / "tests"
        if not tests_dir.exists():
            return True, "no tests/ directory — skipped"

        proc = await asyncio.create_subprocess_exec(
            "python",
            "-m",
            "pytest",
            "-v",
            "--tb=short",
            cwd=str(self.workdir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        return proc.returncode == 0, stdout.decode()

    async def _run_build(self) -> tuple[bool, str]:
        """Run python -m build if setup.py/pyproject.toml exists."""
        has_setup = (self.workdir / "pyproject.toml").exists()
        has_setup_py = (self.workdir / "setup.py").exists()
        if not has_setup and not has_setup_py:
            return True, "no pyproject.toml or setup.py — skipped"

        proc = await asyncio.create_subprocess_exec(
            "python",
            "-m",
            "build",
            "--no-isolation",
            cwd=str(self.workdir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        return proc.returncode == 0, stdout.decode()

    async def request_owner_approval(self, task_id: str, gate_result: GateResult) -> bool:
        """Placeholder for owner approval gate.

        In production this would notify Navpreet via the socket or webhook
        and wait for explicit approval. For now, returns True (auto-approve
        for smoke testing).
        """
        log.info("gate: owner approval requested for %s", task_id)
        # TODO: integrate with notification system / socket
        # For smoke test: auto-approve
        return True
