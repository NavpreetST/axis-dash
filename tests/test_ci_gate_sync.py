"""Tests for scripts/ci_gate_sync.py (CI gate results → Supabase)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from scripts.ci_gate_sync import (
    _post,
    upsert_gate_status,
    post_task_activity,
    sync_all_gates,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    """Set SUPABASE_URL and SUPABASE_SERVICE_KEY for all tests."""
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key-123")
    # Patch module-level constants (already read at import time)
    import scripts.ci_gate_sync as mod
    monkeypatch.setattr(mod, "SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setattr(mod, "SUPABASE_SERVICE_KEY", "test-key-123")


# ---------------------------------------------------------------------------
# _post helper
# ---------------------------------------------------------------------------


class TestPost:
    def test_post_success(self):
        mock_resp = MagicMock()
        mock_resp.status = 201
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            code = _post("gate_status", {"repo": "test"})
            assert code == 201
            mock_open.assert_called_once()

    def test_post_upsert_header(self):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            _post("gate_status", {"repo": "test"}, upsert=True)
            req = mock_open.call_args[0][0]
            assert req.get_header("Prefer") == "resolution=merge-duplicates"

    def test_post_no_upsert_header(self):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            _post("task_activity", {"repo": "test"}, upsert=False)
            req = mock_open.call_args[0][0]
            assert req.get_header("Prefer") == "return=minimal"

    def test_post_http_error_returns_code(self):
        import urllib.error

        with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
            None, 409, "Conflict", {}, None
        )):
            code = _post("gate_status", {"repo": "test"})
            assert code == 409

    def test_post_network_error_returns_zero(self):
        with patch("urllib.request.urlopen", side_effect=ConnectionError("refused")):
            code = _post("gate_status", {"repo": "test"})
            assert code == 0


# ---------------------------------------------------------------------------
# upsert_gate_status
# ---------------------------------------------------------------------------


class TestUpsertGateStatus:
    def test_upsert_success(self):
        mock_resp = MagicMock()
        mock_resp.status = 201
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("scripts.ci_gate_sync._post", return_value=201) as mock_post:
            code = upsert_gate_status(
                repo="NavpreetST/helios",
                pr_number=39,
                gate_name="lint",
                status="success",
                run_url="https://github.com/actions/runs/123",
            )
            assert code == 201
            args, kwargs = mock_post.call_args
            assert args[0] == "gate_status"
            row = args[1]
            assert row["repo"] == "NavpreetST/helios"
            assert row["pr_number"] == 39
            assert row["gate_name"] == "lint"
            assert row["status"] == "success"
            assert kwargs["upsert"] is True

    def test_upsert_invalid_status_returns_400(self):
        code = upsert_gate_status(
            repo="test/repo",
            pr_number=1,
            gate_name="lint",
            status="invalid_status",
        )
        assert code == 400

    def test_upsert_failure_status(self):
        with patch("scripts.ci_gate_sync._post", return_value=200) as mock_post:
            code = upsert_gate_status(
                repo="test/repo",
                pr_number=42,
                gate_name="tests",
                status="failure",
            )
            assert code == 200
            row = mock_post.call_args[0][1]
            assert row["status"] == "failure"
            assert row["conclusion"] == "failure"

    def test_upsert_custom_conclusion(self):
        with patch("scripts.ci_gate_sync._post", return_value=200) as mock_post:
            upsert_gate_status(
                repo="test/repo",
                pr_number=42,
                gate_name="tests",
                status="failure",
                conclusion="2 failed, 34 passed",
            )
            row = mock_post.call_args[0][1]
            assert row["conclusion"] == "2 failed, 34 passed"


# ---------------------------------------------------------------------------
# post_task_activity
# ---------------------------------------------------------------------------


class TestPostTaskActivity:
    def test_post_merge_activity(self):
        with patch("scripts.ci_gate_sync._post", return_value=201) as mock_post:
            code = post_task_activity(
                repo="NavpreetST/helios",
                pr_number=39,
                action="merged",
                detail="Merged feat/nim-context-pack",
            )
            assert code == 201
            args, kwargs = mock_post.call_args
            assert args[0] == "task_activity"
            row = args[1]
            assert row["action"] == "merged"
            assert row["detail"] == "Merged feat/nim-context-pack"
            assert kwargs["upsert"] is False

    def test_post_merge_minimal(self):
        with patch("scripts.ci_gate_sync._post", return_value=201) as mock_post:
            post_task_activity(
                repo="test/repo",
                pr_number=1,
                action="merged",
            )
            row = mock_post.call_args[0][1]
            assert row["detail"] == ""


# ---------------------------------------------------------------------------
# sync_all_gates (bulk)
# ---------------------------------------------------------------------------


class TestSyncAllGates:
    def test_bulk_calls_upsert_for_each_gate(self):
        with patch("scripts.ci_gate_sync.upsert_gate_status", return_value=201) as mock_upsert:
            sync_all_gates(
                repo="test/repo",
                pr_number=10,
                lint="success",
                tests="failure",
                drift_guard="success",
                run_url="https://example.com",
            )
            assert mock_upsert.call_count == 3
            calls = {c.kwargs["gate_name"]: c.kwargs["status"] for c in mock_upsert.call_args_list}
            assert calls["lint"] == "success"
            assert calls["tests"] == "failure"
            assert calls["drift_guard"] == "success"

    def test_bulk_skips_pending_gates(self):
        with patch("scripts.ci_gate_sync.upsert_gate_status", return_value=201) as mock_upsert:
            sync_all_gates(
                repo="test/repo",
                pr_number=10,
                lint="success",
                tests="pending",
                drift_guard="pending",
            )
            assert mock_upsert.call_count == 1
            assert mock_upsert.call_args.kwargs["gate_name"] == "lint"


# ---------------------------------------------------------------------------
# Missing env vars
# ---------------------------------------------------------------------------


class TestMissingEnv:
    def test_returns_zero_when_env_missing(self, monkeypatch):
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)

        import scripts.ci_gate_sync as mod
        monkeypatch.setattr(mod, "SUPABASE_URL", "")
        monkeypatch.setattr(mod, "SUPABASE_SERVICE_KEY", "")

        result = mod.main()
        assert result == 0
