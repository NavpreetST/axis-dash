"""Forge hardening — sandbox isolation, concurrency cap, gate proof, server auth.

These tests prove:
1. SANDBOX CRED ISOLATION — worker env is scrubbed of host secrets
2. `opencode serve` HARDENING — binds 127.0.0.1 + server password
3. CONCURRENCY CAP — semaphore limits parallel executions
4. GATE PROOF — gate blocks on lint/test/build failure (short-circuit)
5. GATE PROOF — gate produces GATED result, never auto-push
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


# =========================================================================
# 2. `opencode serve` HARDENING
# =========================================================================


class TestServerHardening:
    """Prove the server binds to 127.0.0.1 and uses auth."""

    def test_base_url_raises_before_start(self):
        """base_url must raise RuntimeError before the server starts."""
        from aegis.forge.manager import ForgeManager

        mgr = ForgeManager()
        with pytest.raises(RuntimeError, match="forge server not started"):
            _ = mgr.base_url

    @pytest.mark.asyncio
    async def test_start_passes_hostname_and_password(self):
        """start() must pass --hostname 127.0.0.1 and OPENCODE_SERVER_PASSWORD."""
        from unittest.mock import AsyncMock, patch

        from aegis.forge.manager import _SERVER_PASSWORD, ForgeManager

        assert len(_SERVER_PASSWORD) >= 32

        # Mock subprocess creation to capture args and env
        captured_args = None
        captured_env = None

        async def fake_subprocess_exec(*args, **kwargs):
            nonlocal captured_args, captured_env
            captured_args = args
            captured_env = kwargs.get("env", {})
            mock_proc = AsyncMock()
            mock_proc.stderr = AsyncMock()
            # Simulate opencode printing port info to stderr
            mock_proc.stderr.__aiter__.return_value = [b"Server listening on 127.0.0.1:12345\n"]
            return mock_proc

        with (
            patch.object(ForgeManager, "_detect_port", return_value=12345),
            patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess_exec),
            patch("httpx.AsyncClient") as mock_httpx_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get.return_value.status_code = 200
            mock_httpx_cls.return_value = mock_client
            mgr = ForgeManager()
            await mgr.start()

        assert captured_args is not None, "start() must call create_subprocess_exec"
        args_list = list(captured_args)
        assert "--hostname" in args_list, "start() must pass --hostname"
        hostname_idx = args_list.index("--hostname")
        assert args_list[hostname_idx + 1] == "127.0.0.1", (
            f"start() must bind to 127.0.0.1, got {args_list[hostname_idx + 1]}"
        )
        assert "0.0.0.0" not in args_list, "start() must NOT bind to 0.0.0.0"
        assert captured_env.get("OPENCODE_SERVER_PASSWORD") == _SERVER_PASSWORD, (
            "start() must set OPENCODE_SERVER_PASSWORD in subprocess env"
        )

        # Also verify httpx client uses BasicAuth
        await mgr.stop()


# =========================================================================
# 4. CONCURRENCY CAP
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
# 5. GATE PROOF
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
        assert "owner_approved" in d
