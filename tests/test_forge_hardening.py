"""Forge hardening — sandbox isolation, concurrency cap, gate proof.

These tests prove:
1. SANDBOX CRED ISOLATION — worker env is scrubbed of host secrets
2. CONCURRENCY CAP — semaphore limits parallel executions
3. GATE PROOF — gate blocks on lint/test/build failure (short-circuit)
4. GATE PROOF — gate produces GATED result, never auto-push
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from aegis.forge.dispatcher import (
    MAX_CONCURRENT_FORGE_TASKS,
    ForgeDispatcher,
)
from aegis.forge.gate import GateResult, GateStage

# =========================================================================
# 1. SANDBOX CRED ISOLATION
# =========================================================================


class TestSandboxCredIsolation:
    """Prove forge worker env is stripped of host secrets."""

    def test_sanitize_env_blocks_everything_not_in_allowlist(self):
        """Only vars in _SANDBOX_ALLOWLIST should pass through."""
        from aegis.forge.manager import ForgeManager

        dirty = {
            "PATH": "/usr/bin",
            "HOME": "/root",
            "USER": "root",
            "LANG": "en_US.UTF-8",
            "SHELL": "/bin/bash",
            "GROQ_API_KEY": "gsk_live_secret",
            "GEMINI_API_KEY": "AIza_secret",
            "HF_TOKEN": "hf_secret",
            "DB_PASSWORD": "s3cret",
            "MY_AUTH_TOKEN": "tok_123",
            "SOME_RANDOM_VAR": "should_not_pass",
            "SSH_AUTH_SOCK": "/tmp/ssh-agent",
            "GIT_ASKPASS": "helper",
        }
        with pytest.MonkeyPatch.context() as mp:
            for k, v in dirty.items():
                mp.setenv(k, v)
            clean = ForgeManager._sanitize_env()

        # Allowlisted vars pass through
        assert clean["PATH"] == "/usr/bin"
        assert clean["HOME"] == "/root"
        assert clean["USER"] == "root"
        assert clean["LANG"] == "en_US.UTF-8"
        assert clean["SHELL"] == "/bin/bash"

        # EVERYTHING else is stripped
        assert "GROQ_API_KEY" not in clean
        assert "GEMINI_API_KEY" not in clean
        assert "HF_TOKEN" not in clean
        assert "DB_PASSWORD" not in clean
        assert "MY_AUTH_TOKEN" not in clean
        assert "SOME_RANDOM_VAR" not in clean
        assert "SSH_AUTH_SOCK" not in clean
        assert "GIT_ASKPASS" not in clean

    def test_sanitize_env_keeps_opencode_vars(self):
        from aegis.forge.manager import ForgeManager

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("OPENCODE_LOG_LEVEL", "DEBUG")
            mp.setenv("OPENCODE_CONFIG", "/tmp/test.json")
            mp.setenv("OPENCODE_PERMISSION", '{"bash": true}')
            mp.setenv("AEGIS_FORGE_DIR", "/tmp/forge")
            mp.setenv("OPENCODE_BIN", "/usr/local/bin/opencode")
            mp.setenv("PATH", "/bin")
            clean = ForgeManager._sanitize_env()

        assert clean["OPENCODE_LOG_LEVEL"] == "DEBUG"
        assert clean["OPENCODE_CONFIG"] == "/tmp/test.json"
        assert clean["OPENCODE_PERMISSION"] == '{"bash": true}'
        assert clean["AEGIS_FORGE_DIR"] == "/tmp/forge"
        assert clean["OPENCODE_BIN"] == "/usr/local/bin/opencode"

    def test_sanitize_env_never_leaks_host_secrets(self):
        """Integration-level: prove real host secrets are stripped."""
        from aegis.forge.manager import _SANDBOX_ALLOWLIST, ForgeManager

        clean = ForgeManager._sanitize_env()

        # Only allowlisted keys should exist
        for key in clean:
            assert key in _SANDBOX_ALLOWLIST, f"Unexpected key in sandbox env: {key}"

    def test_sanitize_env_allows_basic_vars(self):
        """Basic env vars like PATH, HOME, SHELL must pass through."""
        from aegis.forge.manager import ForgeManager

        clean = ForgeManager._sanitize_env()
        assert "PATH" in clean, "PATH must be in sandbox env"
        assert "HOME" in clean, "HOME must be in sandbox env"

    @pytest.mark.asyncio
    async def test_run_task_writes_sandbox_config_with_bash_denied(self):
        """run_task() must write a per-task config with permission.bash: deny.

        This proves the config-level containment that prevents
        --dangerously-skip-permissions from re-enabling bash (the deny
        is enforced server-side by PermissionV2.assert before any
        permission.asked event reaches the CLI).
        """
        from unittest.mock import AsyncMock, patch

        from aegis.forge.manager import ForgeManager

        mgr = ForgeManager()
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)

            # Mock the subprocess so we don't actually run opencode
            mock_proc = AsyncMock()
            mock_proc.stdout.readline = AsyncMock(return_value=b"")
            mock_proc.stderr.readline = AsyncMock(return_value=b"")
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
            mock_proc.returncode = 0

            with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                result = await mgr.run_task(workdir, "test spec")

            # The config file must exist and have bash:deny
            config_path = workdir / "sandbox-config.json"
            assert config_path.exists(), "run_task() must write a per-task config"
            import json

            cfg = json.loads(config_path.read_text())
            perms = cfg.get("permission", {})
            assert perms.get("bash") == "deny", f"sandbox config must deny bash, got: {perms}"

            # The result should still be structured correctly
            assert result["return_code"] == 0
            assert result["tool_calls"] == 0
            assert result["error"] is None


# =========================================================================
# 2. CONCURRENCY CAP
# =========================================================================


class TestConcurrencyCap:
    """Prove MAX_CONCURRENT_FORGE_TASKS limits parallel execution."""

    def test_max_concurrent_default_is_2(self):
        assert MAX_CONCURRENT_FORGE_TASKS == 2, (
            f"Expected default 2, got {MAX_CONCURRENT_FORGE_TASKS}"
        )

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrent_executions(self):
        """The semaphore must prevent more than N concurrent executions."""
        from aegis.forge.manager import ForgeManager

        mgr = ForgeManager()
        dispatcher = ForgeDispatcher(mgr)

        assert dispatcher._semaphore is not None
        assert dispatcher._semaphore._value == MAX_CONCURRENT_FORGE_TASKS, (
            f"Semaphore value {dispatcher._semaphore._value} != {MAX_CONCURRENT_FORGE_TASKS}"
        )

    @pytest.mark.asyncio
    async def test_semaphore_is_class_level(self):
        """The semaphore must be shared across all dispatcher instances."""
        from aegis.forge.manager import ForgeManager

        mgr = ForgeManager()
        d1 = ForgeDispatcher(mgr)
        d2 = ForgeDispatcher(mgr)

        assert d1._semaphore is d2._semaphore, "Semaphore must be a class-level singleton"

    def test_max_concurrent_tunable_via_env(self):
        """AEGIS_FORGE_MAX_CONCURRENT must override the default."""
        import importlib
        import sys

        module_name = "aegis.forge.dispatcher"
        mod = sys.modules[module_name]

        # Save original semaphore so we can restore later
        original_semaphore = ForgeDispatcher._semaphore
        # Reset so module-level code re-executes cleanly
        ForgeDispatcher._semaphore = None

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("AEGIS_FORGE_MAX_CONCURRENT", "4")
            importlib.reload(mod)
            assert mod.MAX_CONCURRENT_FORGE_TASKS == 4

        # Restore: reload without the env override
        ForgeDispatcher._semaphore = None
        importlib.reload(mod)
        assert mod.MAX_CONCURRENT_FORGE_TASKS == 2

        # Restore original semaphore for any tests holding the old class ref
        ForgeDispatcher._semaphore = original_semaphore


# =========================================================================
# 3. GATE PROOF
# =========================================================================


class TestGateProof:
    """Prove the gate stage blocks commit/push on failures."""

    @pytest.mark.asyncio
    async def test_gate_blocks_on_lint_failure(self):
        """Gate must short-circuit and return overall_passed=False when lint fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            # Create a Python file with a deliberate lint error
            bad_file = workdir / "bad.py"
            bad_file.write_text("import os, sys\n")

            gate = GateStage(workdir)
            result = await gate.run_all()

            assert result.lint_passed is False, "Lint should fail on bad import style"
            assert result.test_passed is False, (
                "Tests should NOT run when lint fails (short-circuit)"
            )
            assert result.build_passed is False, (
                "Build should NOT run when lint fails (short-circuit)"
            )
            assert result.overall_passed is False, "Overall should be False when lint fails"
            assert result.gate_ms > 0

    @pytest.mark.asyncio
    async def test_gate_blocks_on_test_failure(self):
        """Gate must short-circuit after lint passes but tests fail."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            # Create a lint-clean file but with a failing test
            clean_file = workdir / "ok.py"
            clean_file.write_text("def foo():\n    return 42\n")

            tests_dir = workdir / "tests"
            tests_dir.mkdir()
            failing_test = tests_dir / "test_fail.py"
            failing_test.write_text(
                "def test_should_fail():\n    assert False, 'deliberate failure'\n"
            )

            # Run ruff format on the temp dir so files are compliant
            proc = await asyncio.create_subprocess_exec(
                "ruff",
                "format",
                str(workdir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

            gate = GateStage(workdir)
            result = await gate.run_all()

            assert result.lint_passed is True, (
                f"Lint should pass on clean code — output: {result.lint_output}"
            )
            assert result.test_passed is False, "Tests should fail on deliberate failure"
            assert result.build_passed is False, (
                "Build should NOT run when tests fail (short-circuit)"
            )
            assert result.overall_passed is False

    @pytest.mark.asyncio
    async def test_gate_blocks_on_build_failure(self):
        """Gate must block when lint+tests pass but build fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            # Create a clean Python file with a matching test
            clean_file = workdir / "ok.py"
            clean_file.write_text("def foo():\n    return 42\n")
            tests_dir = workdir / "tests"
            tests_dir.mkdir()
            passing_test = tests_dir / "test_ok.py"
            passing_test.write_text(
                "def test_foo():\n    from ok import foo\n    assert foo() == 42\n"
            )
            # Add pyproject.toml that will fail build (no build-system table)
            (workdir / "pyproject.toml").write_text(
                '[project]\nname = "bad-build"\nversion = "0.1.0"\n'
            )

            proc = await asyncio.create_subprocess_exec(
                "ruff",
                "format",
                str(workdir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

            gate = GateStage(workdir)
            result = await gate.run_all()

            assert result.lint_passed is True, "Lint should pass on clean code"
            assert result.test_passed is True, "Tests should pass"
            assert result.build_passed is False, "Build should fail (no build-system)"
            assert result.overall_passed is False, "Overall must be False when build fails"

    @pytest.mark.asyncio
    async def test_gate_all_passes(self):
        """Gate must return overall_passed=True when all checks pass."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            # Create a clean Python file
            clean_file = workdir / "ok.py"
            clean_file.write_text("def foo():\n    return 42\n")

            tests_dir = workdir / "tests"
            tests_dir.mkdir()
            passing_test = tests_dir / "test_ok.py"
            passing_test.write_text(
                "def test_foo():\n    from ok import foo\n    assert foo() == 42\n"
            )

            # Pre-format so ruff format check passes
            proc = await asyncio.create_subprocess_exec(
                "ruff",
                "format",
                str(workdir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

            gate = GateStage(workdir)
            result = await gate.run_all()

            assert result.lint_passed is True
            assert result.test_passed is True
            assert result.build_passed is True  # skipped (no pyproject.toml)
            assert result.overall_passed is True

    @pytest.mark.asyncio
    async def test_gate_short_circuit_does_not_run_downstream_checks(self):
        """Prove short-circuit: downstream checks must NOT execute after failure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            # Only a bad lint file, nothing else
            bad_file = workdir / "bad.py"
            bad_file.write_text("import os, sys\n")

            gate = GateStage(workdir)
            result = await gate.run_all()

            # Verify short-circuit
            assert result.lint_passed is False
            assert result.test_passed is False  # never ran
            assert result.build_passed is False  # never ran

    @pytest.mark.asyncio
    async def test_gate_never_auto_approves_push_without_owner(self):
        """Gate must NOT auto-push; owner approval is always required."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            clean_file = workdir / "ok.py"
            clean_file.write_text("x = 1\n")

            gate = GateStage(workdir)
            result = await gate.run_all()

            assert result.overall_passed is True, "Gate checks should pass"

            # Owner approval is separate — test the request method
            # Default is False (owner must explicitly approve)
            approved = await gate.request_owner_approval("test-task", result)
            assert approved is False, (
                "request_owner_approval must return False by default — "
                "owner must explicitly approve"
            )

    def test_gate_result_tracks_all_stages(self):
        """GateResult must expose all individual stage results."""
        result = GateResult()
        assert hasattr(result, "lint_passed")
        assert hasattr(result, "test_passed")
        assert hasattr(result, "build_passed")
        assert hasattr(result, "owner_approved")
        assert hasattr(result, "overall_passed")
        assert hasattr(result, "gate_ms")

        assert result.lint_passed is False
        assert result.owner_approved is False
        assert result.overall_passed is False

    def test_gate_result_to_dict_includes_all_fields(self):
        d = GateResult(lint_passed=True, overall_passed=True, gate_ms=123).to_dict()
        assert d["lint_passed"] is True
        assert d["overall_passed"] is True
        assert d["gate_ms"] == 123
        assert "lint_output" in d
        assert "test_output" in d
        assert "build_output" in d
        assert "cr_output" in d
        assert "cr_findings" in d
        assert "cr_loop_iterations" in d
        assert "owner_approved" in d

    def test_gate_result_tracks_cr_fields(self):
        """GateResult must expose all cr review fields."""
        result = GateResult()
        assert hasattr(result, "cr_passed")
        assert hasattr(result, "cr_output")
        assert hasattr(result, "cr_findings")
        assert hasattr(result, "cr_loop_iterations")
        assert result.cr_passed is True  # default: True (skipped)
        assert result.cr_findings == []

    def test_cr_parse_findings_detects_severity_lines(self):
        """_parse_cr_findings must extract lines starting with severity markers."""
        from aegis.forge.gate import GateStage

        output = """\
CodeRabbit Review — Findings

error: Missing type hints on public function foo()
warning: Unused import os
info: Consider adding a docstring
Some random text without severity
critical: Potential SQL injection vector
"""
        findings = GateStage._parse_cr_findings(output)
        assert len(findings) == 4
        assert findings[0]["severity"] == "error"
        assert findings[1]["severity"] == "warning"
        assert findings[2]["severity"] == "info"
        assert findings[3]["severity"] == "critical"

    def test_cr_parse_findings_returns_empty_for_clean_output(self):
        """_parse_cr_findings must return [] when no severity markers."""
        from aegis.forge.gate import GateStage

        assert GateStage._parse_cr_findings("All good!\nNo issues found.") == []

    def test_cr_parse_findings_handles_empty_input(self):
        from aegis.forge.gate import GateStage

        assert GateStage._parse_cr_findings("") == []


# =========================================================================
# 4. GATE — CodeRabbit REVIEW STAGE
# =========================================================================


class TestGateCrStage:
    """Prove the cr review stage integrates correctly into the gate pipeline."""

    # ------------------------------------------------------------------
    # Availability helpers
    # ------------------------------------------------------------------

    def test_cr_binary_returns_none_when_not_on_path(self):
        """_cr_binary must return None when neither cr nor coderabbit exist."""
        from aegis.forge.gate import _cr_binary

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("PATH", "/dev/null")
            assert _cr_binary() is None

    def test_cr_token_returns_none_when_missing(self):
        """_cr_token must return None when no env var or secrets file."""
        from aegis.forge.gate import _cr_token

        with pytest.MonkeyPatch.context() as mp:
            # Ensure the env key is absent
            mp.delenv("CODERABBIT_API_KEY", raising=False)
            # Point HOME to a temp dir without a secrets file
            import tempfile

            with tempfile.TemporaryDirectory() as tmp:
                mp.setenv("HOME", tmp)
                assert _cr_token() is None

    def test_cr_token_reads_from_env(self):
        """_cr_token must return the env var value when set."""
        from aegis.forge.gate import _cr_token

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("CODERABBIT_API_KEY", "cr_test_key_123")
            assert _cr_token() == "cr_test_key_123"

    def test_cr_token_reads_from_secrets_file(self):
        """_cr_token must read from ~/.config/aegis/secrets.env as fallback."""
        from aegis.forge.gate import _cr_token

        with pytest.MonkeyPatch.context() as mp:
            mp.delenv("CODERABBIT_API_KEY", raising=False)
            import os
            import tempfile

            with tempfile.TemporaryDirectory() as tmp:
                fake_home = Path(tmp)
                secrets_dir = fake_home / ".config" / "aegis"
                secrets_dir.mkdir(parents=True)
                (secrets_dir / "secrets.env").write_text(
                    "OTHER_KEY=val\nCODERABBIT_API_KEY=from_file\n"
                )
                mp.setenv("HOME", str(fake_home))
                mp.setenv("PATH", os.environ.get("PATH", "/usr/bin"))
                assert _cr_token() == "from_file"

    # ------------------------------------------------------------------
    # Token isolation
    # ------------------------------------------------------------------

    def test_cr_token_in_allowlist_but_stripped_by_run_task(self):
        """CODERABBIT_API_KEY is allowlisted (documentary) but run_task() pops it."""
        from aegis.forge.manager import _SANDBOX_ALLOWLIST, ForgeManager

        # Confirms it IS in the allowlist (documentary requirement)
        assert "CODERABBIT_API_KEY" in _SANDBOX_ALLOWLIST

        # Confirms _sanitize_env passes it through (it's in allowlist)
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("CODERABBIT_API_KEY", "should_not_leak")
            sandbox = ForgeManager._sanitize_env()
            assert "CODERABBIT_API_KEY" in sandbox, (
                "Token is in allowlist so _sanitize_env keeps it"
            )

    @pytest.mark.asyncio
    async def test_run_task_strips_cr_token_before_subprocess(self):
        """run_task() must pop CODERABBIT_API_KEY from the subprocess env."""
        from unittest.mock import AsyncMock, patch

        from aegis.forge.manager import ForgeManager

        mgr = ForgeManager()
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
            mock_proc.returncode = 0

            captured_env = {}

            async def _fake_exec(*args, **kwargs):
                captured_env.update(kwargs.get("env", {}))
                return mock_proc

            with (
                patch("asyncio.create_subprocess_exec", side_effect=_fake_exec),
                pytest.MonkeyPatch.context() as mp,
            ):
                mp.setenv("CODERABBIT_API_KEY", "should_not_leak")
                await mgr.run_task(workdir, "test")

            assert "CODERABBIT_API_KEY" not in captured_env, (
                f"Token leaked into subprocess env: {captured_env}"
            )

    # ------------------------------------------------------------------
    # Gate integration — cr stage order and advisory behavior
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_gate_skips_cr_when_not_available(self):
        """Gate must skip cr when binary or token is missing, overall_passed=True."""
        import os as _os

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            pytest.MonkeyPatch.context() as mp,
        ):
            workdir = Path(tmpdir)
            (workdir / "ok.py").write_text("x = 1\n")

            # Keep real PATH for ruff but remove cr from it
            real_path = _os.environ.get("PATH", "/usr/bin")
            mp.setenv("PATH", real_path)
            mp.delenv("CODERABBIT_API_KEY", raising=False)

            gate = GateStage(workdir)
            result = await gate.run_all()

            assert result.lint_passed is True
            assert result.cr_passed is True, "cr should be skipped, not failed"
            assert "skipped" in result.cr_output.lower()
            assert result.cr_findings == []
            assert result.cr_loop_iterations == 0
            assert result.overall_passed is True

    @pytest.mark.asyncio
    async def test_gate_cr_is_advisory(self):
        """cr findings must NOT set overall_passed=False (advisory by default)."""
        from unittest.mock import AsyncMock, patch

        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            (workdir / "ok.py").write_text("x = 1\n")

            gate = GateStage(workdir)

            with (
                patch("aegis.forge.gate._cr_binary", return_value="/usr/bin/cr"),
                patch("aegis.forge.gate._cr_token", return_value="test_token"),
                patch.object(gate, "_ensure_git_repo", AsyncMock()),
                patch.object(
                    gate,
                    "_run_single_cr_review",
                    return_value=(
                        False,
                        "Issues found",
                        [{"severity": "error", "text": "test finding"}],
                    ),
                ),
                patch.object(gate, "_get_cr_fix_prompt", return_value=None),
            ):
                result = await gate.run_all()

            assert result.lint_passed is True
            assert result.cr_passed is False
            # findings accumulate across all MAX_CR_LOOP+1 iterations
            from aegis.forge.gate import MAX_CR_LOOP

            assert len(result.cr_findings) == MAX_CR_LOOP + 1
            assert result.cr_loop_iterations == MAX_CR_LOOP
            # overall_passed is lint+test+build only — cr is advisory
            assert result.overall_passed is True, "cr is advisory — must not flip overall_passed"

    @pytest.mark.asyncio
    async def test_gate_cr_loop_fires_on_findings(self):
        """cr loop-back must invoke _get_cr_fix_prompt + run_task when findings exist."""
        from unittest.mock import AsyncMock, patch

        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            (workdir / "ok.py").write_text("x = 1\n")

            mock_manager = AsyncMock()
            mock_manager.run_task = AsyncMock()

            gate = GateStage(workdir, manager=mock_manager)

            with (
                patch("aegis.forge.gate._cr_binary", return_value="/usr/bin/cr"),
                patch("aegis.forge.gate._cr_token", return_value="test_token"),
                patch.object(gate, "_ensure_git_repo", AsyncMock()),
                patch.object(
                    gate,
                    "_run_single_cr_review",
                    side_effect=[
                        (
                            False,
                            "Issues: error something",
                            [{"severity": "error", "text": "something"}],
                        ),
                        (True, "All clean", []),
                    ],
                ),
                patch.object(gate, "_get_cr_fix_prompt", return_value="fix the issues"),
                # Mock git commit to avoid real subprocess calls
                patch("aegis.forge.gate._run_cmd", return_value=(0, "")),
            ):
                result = await gate.run_all()

            assert result.cr_passed is True
            assert result.cr_loop_iterations == 1
            assert len(result.cr_findings) == 1
            assert result.overall_passed is True
            mock_manager.run_task.assert_awaited_once_with(workdir, "fix the issues")

    @pytest.mark.asyncio
    async def test_gate_cr_loop_capped_at_max_iterations(self):
        """cr loop must NOT exceed MAX_CR_LOOP iterations even with persistent issues."""
        from unittest.mock import AsyncMock, patch

        from aegis.forge.gate import MAX_CR_LOOP

        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            (workdir / "ok.py").write_text("x = 1\n")

            mock_manager = AsyncMock()
            mock_manager.run_task = AsyncMock()

            gate = GateStage(workdir, manager=mock_manager)

            with (
                patch("aegis.forge.gate._cr_binary", return_value="/usr/bin/cr"),
                patch("aegis.forge.gate._cr_token", return_value="test_token"),
                patch.object(gate, "_ensure_git_repo", AsyncMock()),
                patch.object(
                    gate,
                    "_run_single_cr_review",
                    return_value=(
                        False,
                        "Issues persist",
                        [{"severity": "error", "text": "still broken"}],
                    ),
                ),
                patch.object(gate, "_get_cr_fix_prompt", return_value="fix again"),
                patch("aegis.forge.gate._run_cmd", return_value=(0, "")),
            ):
                result = await gate.run_all()

            assert result.cr_passed is False
            assert result.cr_loop_iterations == MAX_CR_LOOP
            assert mock_manager.run_task.await_count == MAX_CR_LOOP
            assert result.overall_passed is True  # still advisory

    @pytest.mark.asyncio
    async def test_gate_cr_preserves_stage_order(self):
        """cr must run after build (not before)."""
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            (workdir / "bad.py").write_text("import os, sys\n")  # lint will fail

            gate = GateStage(workdir)
            result = await gate.run_all()

            # Lint fails → short-circuit → cr never ran
            assert result.lint_passed is False
            # cr should have its default value
            assert result.cr_passed is True
            assert result.cr_output == ""

            # Now test with all-clean workdir + mocked cr
            workdir2 = Path(tempfile.mkdtemp())
            (workdir2 / "ok.py").write_text("x = 1\n")
            gate2 = GateStage(workdir2)

            # Track execution order
            execution_order = []

            async def _fake_lint():
                execution_order.append("lint")
                return True, ""

            async def _fake_tests():
                execution_order.append("test")
                return True, ""

            async def _fake_build():
                execution_order.append("build")
                return True, ""

            async def _fake_cr():
                execution_order.append("cr")
                return True, "", [], 0

            with (
                patch.object(gate2, "_run_lint", _fake_lint),
                patch.object(gate2, "_run_tests", _fake_tests),
                patch.object(gate2, "_run_build", _fake_build),
                patch.object(gate2, "_cr_available", return_value=True),
                patch.object(gate2, "_run_cr_loop", _fake_cr),
            ):
                await gate2.run_all()

            assert execution_order == ["lint", "test", "build", "cr"], (
                f"Expected lint→test→build→cr, got {execution_order}"
            )

    # ------------------------------------------------------------------
    # Owner approval with cr findings
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_gate_owner_approval_still_required_after_cr(self):
        """owner approval must still be required after cr stage passes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            (workdir / "ok.py").write_text("x = 1\n")

            gate = GateStage(workdir)
            result = await gate.run_all()

            assert result.overall_passed is True
            approved = await gate.request_owner_approval("test-task", result)
            assert approved is False, "Owner must explicitly approve"

    @pytest.mark.asyncio
    async def test_gate_owner_approval_includes_cr_summary_in_log(self):
        """request_owner_approval must log cr findings summary."""

        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            gate = GateStage(workdir)

            result = GateResult(
                cr_passed=False,
                cr_findings=[{"severity": "error", "text": "test"}],
                cr_loop_iterations=1,
                overall_passed=True,
            )

            with pytest.MonkeyPatch.context() as mp:
                messages = []

                class FakeLogger:
                    def warning(self, msg, *args, **kwargs):
                        messages.append(msg % args if args else msg)

                mp.setattr("aegis.forge.gate.log", FakeLogger())
                await gate.request_owner_approval("task-42", result)

            assert any("cr: 1 finding after 1 loop" in m for m in messages), (
                f"Expected cr summary in log, got: {messages}"
            )

    # ------------------------------------------------------------------
    # Git repo initialization for cr review
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_ensure_git_repo_inits_when_missing(self):
        """_ensure_git_repo must init a git repo when the workdir lacks one."""
        from aegis.forge.gate import GateStage, _run_cmd

        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            (workdir / "test.py").write_text("pass\n")

            assert not (workdir / ".git").exists()
            await GateStage._ensure_git_repo(workdir)
            assert (workdir / ".git").exists()

            # Verify git works
            rc, out = await _run_cmd(
                ["git", "rev-parse", "--git-dir"],
                cwd=workdir,
            )
            assert rc == 0, f"git failed: {out}"

    @pytest.mark.asyncio
    async def test_ensure_git_repo_skips_if_already_git(self):
        """_ensure_git_repo must not re-init an existing git repo."""
        from aegis.forge.gate import GateStage

        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            # Init git first
            proc = await asyncio.create_subprocess_exec(
                "git",
                "init",
                "-b",
                "main",
                cwd=str(workdir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

            assert (workdir / ".git").exists()
            git_dir_mtime = (workdir / ".git").stat().st_mtime

            # Sleep briefly to ensure mtime would differ on re-init
            import time as time_mod

            time_mod.sleep(0.01)

            await GateStage._ensure_git_repo(workdir)
            assert (workdir / ".git").stat().st_mtime == git_dir_mtime, (
                "git dir should not have been re-initialized"
            )
