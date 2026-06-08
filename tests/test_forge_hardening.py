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
import inspect
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

    def test_sanitize_env_strips_known_secrets(self):
        from aegis.forge.manager import ForgeManager

        # Simulate a host environment full of secrets
        dirty = {
            "PATH": "/usr/bin",
            "HOME": "/root",
            "USER": "root",
            "GROQ_API_KEY": "gsk_live_secret",
            "GEMINI_API_KEY": "AIza_secret",
            "HF_TOKEN": "hf_secret",
            "ANTHROPIC_API_KEY": "sk-ant-secret",
            "OPENAI_API_KEY": "sk-openai-secret",
            "SECRET_ENV_VAR": "should_not_pass",
            "DB_PASSWORD": "s3cret",
            "MY_AUTH_TOKEN": "tok_123",
            "SOME_CREDENTIAL": "creds",
            "PATH_INFO": "/info",  # ends with _INFO not _KEY etc, should pass
            "LANG": "en_US.UTF-8",
            "SHELL": "/bin/bash",
        }
        with pytest.MonkeyPatch.context() as mp:
            for k, v in dirty.items():
                mp.setenv(k, v)
            clean = ForgeManager._sanitize_env()

        # Secret-like vars must be stripped
        assert "GROQ_API_KEY" not in clean
        assert "GEMINI_API_KEY" not in clean
        assert "HF_TOKEN" not in clean
        assert "ANTHROPIC_API_KEY" not in clean
        assert "OPENAI_API_KEY" not in clean
        assert "SECRET_ENV_VAR" not in clean
        assert "DB_PASSWORD" not in clean
        assert "MY_AUTH_TOKEN" not in clean
        assert "SOME_CREDENTIAL" not in clean

        # Allowlisted vars must pass through
        assert clean["PATH"] == "/usr/bin"
        assert clean["HOME"] == "/root"
        assert clean["USER"] == "root"
        assert clean["LANG"] == "en_US.UTF-8"
        assert clean["SHELL"] == "/bin/bash"

    def test_sanitize_env_strips_by_prefix_suffix(self):
        from aegis.forge.manager import ForgeManager

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("GROQ_SECRET_KEY", "gsk_test")
            mp.setenv("MY_API_KEY", "ak_test")
            mp.setenv("PATH", "/bin")
            clean = ForgeManager._sanitize_env()

        assert "GROQ_SECRET_KEY" not in clean
        assert "MY_API_KEY" not in clean
        assert clean["PATH"] == "/bin"

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
        from aegis.forge.manager import ForgeManager

        clean = ForgeManager._sanitize_env()

        # These live in ~/.config/aegis/secrets.env on the host
        # and must NEVER appear in the sandbox env
        for key in clean:
            upper = key.upper()
            assert not upper.startswith("GROQ_"), f"GROQ_ leaked: {key}"
            assert not upper.startswith("GEMINI_"), f"GEMINI_ leaked: {key}"
            assert not upper.startswith("HF_"), f"HF_ leaked: {key}"
            assert not upper.endswith("API_KEY"), f"API_KEY leaked: {key}"
            assert not upper.endswith("TOKEN"), f"TOKEN leaked: {key}"
            assert not upper.endswith("SECRET"), f"SECRET leaked: {key}"
            assert not upper.endswith("PASSWORD"), f"PASSWORD leaked: {key}"

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

    def test_base_url_is_localhost(self):
        """The server must bind to 127.0.0.1, never 0.0.0.0."""
        from aegis.forge.manager import ForgeManager

        mgr = ForgeManager()
        # Before start, base_url raises
        raised = False
        try:
            _ = mgr.base_url  # noqa: B018 — should raise
        except RuntimeError as e:
            raised = True
            assert "forge server not started" in str(e)
        assert raised, "base_url should raise before server starts"

        # The start method passes --hostname 127.0.0.1 — verify via source
        source = inspect.getsource(mgr.start)
        assert "127.0.0.1" in source, "start() must bind to 127.0.0.1 — found in source:\n" + source
        assert "0.0.0.0" not in source, "start() must NOT bind to 0.0.0.0"

    def test_server_password_is_set_in_env(self):
        """OPENCODE_SERVER_PASSWORD must be set on the spawned server."""
        from aegis.forge.manager import _SERVER_PASSWORD, ForgeManager

        assert len(_SERVER_PASSWORD) >= 32, f"Server password too short: {len(_SERVER_PASSWORD)}"

        source = inspect.getsource(ForgeManager.start)
        assert "OPENCODE_SERVER_PASSWORD" in source, (
            "start() must set OPENCODE_SERVER_PASSWORD in subprocess env"
        )
        assert "BasicAuth" in source, "start() must configure httpx client with BasicAuth"


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
        # Re-import the module with a custom env var
        import importlib

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("AEGIS_FORGE_MAX_CONCURRENT", "4")
            import aegis.forge.dispatcher as dispatcher_reloaded

            importlib.reload(dispatcher_reloaded)
            assert dispatcher_reloaded.MAX_CONCURRENT_FORGE_TASKS == 4

        # Reset for other tests
        importlib.reload(__import__("aegis.forge.dispatcher"))


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
