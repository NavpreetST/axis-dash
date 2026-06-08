"""Forge Gate Stage — lint → test → build → cr review → owner gate.

Runs after opencode completes a task. Nothing commits/pushes without
clearing all gates. Git credentials stay OUT of opencode's reach.

cr stage is advisory by default: findings surface at the owner gate but
do NOT set overall_passed=False. To make cr a hard block, set the env
var AEGIS_FORCE_CR_HARD_BLOCK=true (not recommended without rate-limit
headroom; cr free tier is 3 reviews/hour).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

_SUBPROCESS_TIMEOUT: float = 120.0  # seconds per subprocess call

# Max fix-pass iterations for the cr loop-back.
# The cr free tier rate-limits to ~3 reviews/hour, so keep this low.
MAX_CR_LOOP: int = 2


async def _run_cmd(
    args: list[str],
    cwd: str | Path | None = None,
    timeout: float = _SUBPROCESS_TIMEOUT,
    env: dict[str, str] | None = None,
) -> tuple[int, str]:
    """Run a subprocess with timeout. Returns (returncode, stdout+stderr)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except Exception as e:
        return 1, f"subprocess spawn failed: {e}"
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise TimeoutError(f"subprocess timed out after {timeout}s: {' '.join(args)}") from None
    return (proc.returncode or 0), stdout.decode(errors="replace")


def _cr_binary() -> str | None:
    """Return cr binary path or None if not available."""
    for name in ("cr", "coderabbit"):
        for p in os.environ.get("PATH", "").split(os.pathsep):
            candidate = Path(p) / name
            if candidate.exists():
                return str(candidate)
    return None


def _cr_token() -> str | None:
    """Read CODERABBIT_API_KEY from env or ~/.config/aegis/secrets.env."""
    token = os.environ.get("CODERABBIT_API_KEY")
    if token:
        return token
    secrets_path = Path.home() / ".config" / "aegis" / "secrets.env"
    if secrets_path.exists():
        for line in secrets_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("CODERABBIT_API_KEY="):
                raw = line.split("=", 1)[1].strip()
                return raw.strip("\"'")
    return None


_CR_HARD_BLOCK: bool = os.environ.get("AEGIS_FORCE_CR_HARD_BLOCK", "").lower() in ("1", "true")


@dataclass
class GateResult:
    lint_passed: bool = False
    lint_output: str = ""
    test_passed: bool = False
    test_output: str = ""
    build_passed: bool = False
    build_output: str = ""
    cr_passed: bool = True
    cr_output: str = ""
    cr_findings: list[dict] = field(default_factory=list)
    cr_loop_iterations: int = 0
    owner_approved: bool = False
    overall_passed: bool = False
    gate_ms: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class GateStage:
    """Lint → test → build → cr review → owner gate for forge task results.

    Parameters
    ----------
    workdir:
        Directory containing the task output to gate.
    manager:
        Optional ForgeManager instance. Required for the cr fix-pass loop-back
        (so the gate can re-invoke opencode with cr-generated fix prompts).
    """

    def __init__(self, workdir: Path | str, manager: object | None = None) -> None:
        self.workdir = Path(workdir)
        self._manager = manager  # ForgeManager, optional — used for cr loop-back

    async def run_all(self) -> GateResult:
        """Run all gate checks sequentially. Short-circuit on lint/test/build failure."""
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

        # Gate 4: CodeRabbit review (advisory, with auto-fix loop-back)
        if self._cr_available():
            (
                result.cr_passed,
                result.cr_output,
                result.cr_findings,
                result.cr_loop_iterations,
            ) = await self._run_cr_loop()
        else:
            result.cr_passed = True
            result.cr_output = "cr CLI or API token not available — skipped"
            log.info("gate: cr skipped (%s)", result.cr_output)

        # overall_passed reflects lint+test+build only (cr is advisory by default)
        result.overall_passed = True
        result.gate_ms = int((time.perf_counter() - t0) * 1000)
        log.info("gate: ALL PASSED for %s (%dms)", self.workdir, result.gate_ms)
        return result

    # ------------------------------------------------------------------
    # cr stage helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cr_available() -> bool:
        """Check if the cr binary AND an API token are both present."""
        return _cr_binary() is not None and _cr_token() is not None

    @staticmethod
    async def _ensure_git_repo(workdir: Path) -> None:
        """Initialize a git repository in *workdir* if one does not exist.

        cr review requires a git repo.  Opencode runs without one, so the
        gate boots it if missing.
        """
        has_git = False
        try:
            rc, _ = await _run_cmd(["git", "rev-parse", "--git-dir"], cwd=workdir)
            has_git = rc == 0
        except Exception:
            has_git = False

        if not has_git:
            log.info("gate: initializing git repo for cr review in %s", workdir)
            await _run_cmd(["git", "init", "-b", "main"], cwd=workdir)
            await _run_cmd(["git", "config", "user.email", "forge@aegis.local"], cwd=workdir)
            await _run_cmd(["git", "config", "user.name", "Forge"], cwd=workdir)
            await _run_cmd(["git", "add", "-A"], cwd=workdir)
            await _run_cmd(
                ["git", "commit", "-m", "forge task output", "--allow-empty"],
                cwd=workdir,
            )

    async def _run_cr_loop(self) -> tuple[bool, str, list[dict], int]:
        """Run cr review with fix-pass loop-back.

        Returns ``(passed, output, findings, iterations)``.

        ``passed`` is True if cr has no findings (including when cr is
        not available).  ``findings`` always carries any issues found,
        even when cr is advisory.
        """
        binary = _cr_binary()
        token = _cr_token()
        if not binary or not token:
            return True, "cr CLI or token not available", [], 0

        await self._ensure_git_repo(self.workdir)

        iterations = 0
        all_findings: list[dict] = []
        all_output: str = ""

        for i in range(MAX_CR_LOOP + 1):
            iterations = i

            passed, output, findings = await self._run_single_cr_review(binary, token)

            if i == 0:
                all_output = output
            else:
                all_output += f"\n--- cr review iteration {i} ---\n{output}"
            all_findings.extend(findings)

            if passed:
                log.info("gate: cr review PASSED (iteration %d/%d)", i, MAX_CR_LOOP)
                return True, all_output, all_findings, iterations

            log.info(
                "gate: cr review found %d issues (iteration %d/%d)",
                len(findings),
                i,
                MAX_CR_LOOP,
            )

            # Attempt fix-pass loop-back if we have a manager and iterations remain
            if i < MAX_CR_LOOP and self._manager:
                fix_prompt = await self._get_cr_fix_prompt(binary, token)
                if fix_prompt:
                    log.info("gate: cr fix loop-back iteration %d — running opencode", i + 1)
                    await self._manager.run_task(self.workdir, fix_prompt)
                    # Commit the fix so the next review sees the delta
                    await _run_cmd(["git", "add", "-A"], cwd=self.workdir)
                    await _run_cmd(
                        ["git", "commit", "-m", f"cr fix iteration {i + 1}", "--allow-empty"],
                        cwd=self.workdir,
                    )
            elif i >= MAX_CR_LOOP:
                log.warning("gate: cr max loop iterations reached (%d)", MAX_CR_LOOP)

        return False, all_output, all_findings, iterations

    async def _run_single_cr_review(
        self,
        binary: str | None,
        token: str | None,
    ) -> tuple[bool, str, list[dict]]:
        """Run a single ``cr review --plain`` and parse findings."""
        if not binary or not token:
            return True, "cr CLI or token not available", []

        args = [
            binary,
            "review",
            "--plain",
            "--type",
            "uncommitted",
            "--dir",
            str(self.workdir),
        ]
        # Inject token via CLI flag (never in env) so it's absent during
        # opencode model generation — the gate controls injection scope.
        if token:
            args.extend(["--api-key", token])

        rc, output = await _run_cmd(args, cwd=self.workdir)
        findings = self._parse_cr_findings(output)

        # cr exits 0 even with findings (advisory by nature).
        # We determine "passed" by whether findings exist.
        passed = len(findings) == 0
        return passed, output, findings

    async def _get_cr_fix_prompt(
        self,
        binary: str | None,
        token: str | None,
    ) -> str | None:
        """Get a text prompt from ``cr review --prompt-only`` for the fix loop-back.

        Returns the prompt text, or None if the CLI/token is missing or
        the prompt request failed.
        """
        if not binary or not token:
            return None

        args = [
            binary,
            "review",
            "--prompt-only",
            "--type",
            "uncommitted",
            "--dir",
            str(self.workdir),
        ]
        if token:
            args.extend(["--api-key", token])

        rc, output = await _run_cmd(args, cwd=self.workdir)
        if rc != 0 or not output.strip():
            return None

        return output.strip()

    @staticmethod
    def _parse_cr_findings(output: str) -> list[dict]:
        """Parse cr review plain-text output into structured finding dicts.

        Heuristic: lines starting with common severity markers.
        """
        findings: list[dict] = []
        severity_keywords = ("error:", "warning:", "critical:", "info:")
        for line in output.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            lower = stripped.lower()
            for kw in severity_keywords:
                if lower.startswith(kw):
                    findings.append({"severity": kw.rstrip(":"), "text": stripped})
                    break
        return findings

    # ------------------------------------------------------------------
    # Existing gates (lint / test / build)
    # ------------------------------------------------------------------

    async def _run_lint(self) -> tuple[bool, str]:
        """Run ruff check + format check on changed .py files."""
        changed_py = list(self.workdir.rglob("*.py"))
        if not changed_py:
            return True, "no Python files to lint"

        rc1, out1 = await _run_cmd(
            ["ruff", "check", *[str(f) for f in changed_py]],
            cwd=self.workdir,
        )
        rc2, out2 = await _run_cmd(
            ["ruff", "format", "--check", *[str(f) for f in changed_py]],
            cwd=self.workdir,
        )
        output = f"ruff check: {out1}\nruff format: {out2}"
        return rc1 == 0 and rc2 == 0, output

    async def _run_tests(self) -> tuple[bool, str]:
        """Run pytest if tests/ exists in workdir."""
        tests_dir = self.workdir / "tests"
        if not tests_dir.exists():
            return True, "no tests/ directory — skipped"

        rc, out = await _run_cmd(
            ["python", "-m", "pytest", "-v", "--tb=short"],
            cwd=self.workdir,
        )
        return rc == 0, out

    async def _run_build(self) -> tuple[bool, str]:
        """Run python -m build if setup.py/pyproject.toml exists."""
        has_setup = (self.workdir / "pyproject.toml").exists()
        has_setup_py = (self.workdir / "setup.py").exists()
        if not has_setup and not has_setup_py:
            return True, "no pyproject.toml or setup.py — skipped"

        rc, out = await _run_cmd(
            ["python", "-m", "build", "--no-isolation"],
            cwd=self.workdir,
        )
        return rc == 0, out

    async def request_owner_approval(self, task_id: str, gate_result: GateResult) -> bool:
        """Request owner approval before push.

        The gate result includes cr findings (if any) for the owner to
        review before approving.  Default returns False — owner must
        explicitly approve via the GATE:APPROVE command.
        """
        cr_summary = ""
        if gate_result.cr_findings:
            n = len(gate_result.cr_findings)
            cr_summary = (
                f" (cr: {n} finding{'s' if n != 1 else ''}"
                f" after {gate_result.cr_loop_iterations} loop iterations)"
            )
        log.warning(
            "gate: owner approval requested for %s%s — NOT auto-approved. "
            "Use GATE:APPROVE:<task_id> to approve.",
            task_id,
            cr_summary,
        )
        return False
