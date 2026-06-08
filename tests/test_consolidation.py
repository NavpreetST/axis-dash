"""Tests for NIM overnight memory consolidation (aegis.consolidation).

All tests use mocks — live NIM verification deferred until Navpreet sets
NVIDIA_API_KEY in secrets.env.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path: Path) -> sqlite3.Connection:
    """Create a temporary SQLite DB with the episodes schema."""
    db_path = tmp_path / "mnemosyne.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE episodes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          REAL    NOT NULL,
            text        TEXT    NOT NULL,
            embedding   BLOB    NOT NULL,
            neurobus    TEXT    NOT NULL,
            action      TEXT,
            consolidated INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    return conn


@pytest.fixture
def sample_episodes(tmp_db: sqlite3.Connection) -> list[dict]:
    """Insert sample episodes and return them."""
    import array

    episodes = []
    for i in range(5):
        emb = [0.1] * 384  # dummy embedding
        cur = tmp_db.execute(
            "INSERT INTO episodes (ts, text, embedding, neurobus, action, consolidated) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (time.time() - 100 + i, f"USER: test message {i}",
             array.array("f", emb).tobytes(), "{}", None, 0),
        )
        episodes.append({"id": cur.lastrowid, "ts": time.time() - 100 + i,
                         "text": f"USER: test message {i}", "action": None})
    tmp_db.commit()
    return episodes


# ---------------------------------------------------------------------------
# Tests: NimBudget
# ---------------------------------------------------------------------------

class TestNimBudget:
    def test_allow_within_cap(self):
        from aegis.nim_budget import NimBudget
        budget = NimBudget(rpm_cap=5, window_s=60.0)
        for _ in range(5):
            assert budget.allow() is True

    def test_deny_over_cap(self):
        from aegis.nim_budget import NimBudget
        budget = NimBudget(rpm_cap=3, window_s=60.0)
        for _ in range(3):
            assert budget.allow() is True
        assert budget.allow() is False

    def test_remaining_property(self):
        from aegis.nim_budget import NimBudget
        budget = NimBudget(rpm_cap=10, window_s=60.0)
        assert budget.remaining == 10
        budget.allow()
        assert budget.remaining == 9

    def test_wait_s_immediate_when_under_cap(self):
        from aegis.nim_budget import NimBudget
        budget = NimBudget(rpm_cap=10, window_s=60.0)
        assert budget.wait_s() == 0.0

    def test_wait_s_positive_when_at_cap(self):
        from aegis.nim_budget import NimBudget
        budget = NimBudget(rpm_cap=2, window_s=60.0)
        budget.allow()
        budget.allow()
        assert budget.wait_s() > 0.0

    def test_window_eviction(self):
        from aegis.nim_budget import NimBudget
        budget = NimBudget(rpm_cap=2, window_s=0.1)
        budget.allow()
        budget.allow()
        assert budget.allow() is False
        time.sleep(0.15)
        assert budget.allow() is True


# ---------------------------------------------------------------------------
# Tests: consolidation module — flag-off
# ---------------------------------------------------------------------------

class TestConsolidationFlagOff:
    @pytest.mark.asyncio
    async def test_flag_off_no_api_key(self):
        """Without NVIDIA_API_KEY, run() should sleep forever (no-op)."""
        from aegis import consolidation

        with patch.object(consolidation, "_enabled", False):
            task = asyncio.create_task(consolidation.run())
            await asyncio.sleep(0.05)
            assert not task.done()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


# ---------------------------------------------------------------------------
# Tests: consolidation module — get_unconsolidated
# ---------------------------------------------------------------------------

class TestGetUnconsolidated:
    def test_returns_unconsolidated_episodes(self, tmp_db, sample_episodes):
        from aegis.consolidation import _get_unconsolidated
        result = _get_unconsolidated(tmp_db)
        assert len(result) == 5

    def test_excludes_consolidated(self, tmp_db, sample_episodes):
        from aegis.consolidation import _get_unconsolidated
        tmp_db.execute("UPDATE episodes SET consolidated = 1 WHERE id = ?",
                       (sample_episodes[0]["id"],))
        tmp_db.commit()
        result = _get_unconsolidated(tmp_db)
        assert len(result) == 4
        assert all(ep["id"] != sample_episodes[0]["id"] for ep in result)

    def test_excludes_seed_rows(self, tmp_db, sample_episodes):
        from aegis.consolidation import _get_unconsolidated
        import array
        tmp_db.execute(
            "INSERT INTO episodes (ts, text, embedding, neurobus, action, consolidated) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (time.time() - 200, "FACT: test seed",
             array.array("f", [0.1] * 384).tobytes(), "{}", "seed", 0),
        )
        tmp_db.commit()
        result = _get_unconsolidated(tmp_db)
        assert all(ep["action"] != "seed" for ep in result)

    def test_empty_when_all_consolidated(self, tmp_db, sample_episodes):
        from aegis.consolidation import _get_unconsolidated
        tmp_db.execute("UPDATE episodes SET consolidated = 1")
        tmp_db.commit()
        result = _get_unconsolidated(tmp_db)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Tests: consolidation module — mark_consolidated
# ---------------------------------------------------------------------------

class TestMarkConsolidated:
    def test_marks_episodes(self, tmp_db, sample_episodes):
        from aegis.consolidation import _mark_consolidated
        ids = [ep["id"] for ep in sample_episodes[:3]]
        _mark_consolidated(tmp_db, ids)
        cur = tmp_db.execute("SELECT consolidated FROM episodes WHERE id IN ({})".format(
            ",".join("?" for _ in ids)), ids)
        assert all(row[0] == 1 for row in cur.fetchall())

    def test_empty_ids_noop(self, tmp_db, sample_episodes):
        from aegis.consolidation import _mark_consolidated
        _mark_consolidated(tmp_db, [])
        cur = tmp_db.execute("SELECT consolidated FROM episodes")
        assert all(row[0] == 0 for row in cur.fetchall())


# ---------------------------------------------------------------------------
# Tests: consolidation module — format_episodes
# ---------------------------------------------------------------------------

class TestFormatEpisodes:
    def test_formats_user_episodes(self):
        from aegis.consolidation import _format_episodes
        episodes = [
            {"id": 1, "ts": 1.0, "text": "hello", "action": None},
            {"id": 2, "ts": 2.0, "text": "world", "action": "speak"},
        ]
        result = _format_episodes(episodes)
        assert "[User] hello" in result
        assert "[Aegis] world" in result


# ---------------------------------------------------------------------------
# Tests: consolidation module — NIM call (mocked)
# ---------------------------------------------------------------------------

class TestCallNim:
    @pytest.mark.asyncio
    async def test_success(self):
        from aegis.consolidation import _call_nim

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "summary text"}}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("aegis.consolidation.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                post=AsyncMock(return_value=mock_response)
            ))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("aegis.consolidation.NVIDIA_API_KEY", "test-key"):
                from aegis.nim_budget import NIM_BUDGET
                with patch.object(NIM_BUDGET, "allow", return_value=True), \
                     patch.object(NIM_BUDGET, "wait_s", return_value=0.0):
                    result = await _call_nim({"model": "test", "messages": []})

            assert result is not None
            assert result["choices"][0]["message"]["content"] == "summary text"

    @pytest.mark.asyncio
    async def test_returns_none_on_network_error(self):
        import httpx
        from aegis.consolidation import _call_nim

        with patch("aegis.consolidation.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                post=AsyncMock(side_effect=httpx.NetworkError("connection failed"))
            ))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("aegis.consolidation.NVIDIA_API_KEY", "test-key"), \
                 patch("aegis.consolidation.MAX_RETRIES", 1):
                result = await _call_nim({"model": "test", "messages": []})

            assert result is None


# ---------------------------------------------------------------------------
# Tests: consolidation module — consolidate_batch (mocked)
# ---------------------------------------------------------------------------

class TestConsolidateBatch:
    @pytest.mark.asyncio
    async def test_consolidate_batch_success(self, tmp_db, sample_episodes):
        from aegis.consolidation import _consolidate_batch

        mock_response = {
            "choices": [{"message": {"content": "consolidated summary"}}]
        }

        with patch("aegis.consolidation._call_nim", new_callable=AsyncMock, return_value=mock_response), \
             patch("aegis.consolidation._store_consolidated"):
            count = await _consolidate_batch(tmp_db, sample_episodes)

        assert count == 5
        # Check originals were marked
        cur = tmp_db.execute("SELECT consolidated FROM episodes")
        assert all(row[0] == 1 for row in cur.fetchall())

    @pytest.mark.asyncio
    async def test_consolidate_batch_empty_returns_zero(self, tmp_db):
        from aegis.consolidation import _consolidate_batch
        count = await _consolidate_batch(tmp_db, [])
        assert count == 0

    @pytest.mark.asyncio
    async def test_consolidate_batch_nim_failure_returns_zero(self, tmp_db, sample_episodes):
        from aegis.consolidation import _consolidate_batch

        with patch("aegis.consolidation._call_nim", new_callable=AsyncMock, return_value=None):
            count = await _consolidate_batch(tmp_db, sample_episodes)

        assert count == 0
        # Originals should NOT be marked consolidated
        cur = tmp_db.execute("SELECT consolidated FROM episodes")
        assert all(row[0] == 0 for row in cur.fetchall())


# ---------------------------------------------------------------------------
# Tests: consolidation module — event emission
# ---------------------------------------------------------------------------

class TestEmitEvent:
    @pytest.mark.asyncio
    async def test_emit_event_success(self):
        from aegis.consolidation import _emit_event

        with patch("aegis.observability.eventlog.log_event", new_callable=AsyncMock) as mock_log:
            await _emit_event("task_done", "info", {"event": "test"})
            mock_log.assert_called_once()

    @pytest.mark.asyncio
    async def test_emit_event_failure_isolation(self):
        from aegis.consolidation import _emit_event

        with patch("aegis.observability.eventlog.log_event",
                   new_callable=AsyncMock, side_effect=Exception("boom")):
            # Should not raise
            await _emit_event("task_done", "info", {"event": "test"})


# ---------------------------------------------------------------------------
# Tests: consolidation module — state persistence
# ---------------------------------------------------------------------------

class TestStatePersistence:
    def test_load_state_missing_file(self, tmp_path):
        from aegis.consolidation import _load_state
        with patch("aegis.consolidation._STATE_PATH", tmp_path / "missing.json"):
            state = _load_state()
            assert state == {}

    def test_save_and_load_state(self, tmp_path):
        from aegis.consolidation import _save_state, _load_state
        state_path = tmp_path / "state.json"
        with patch("aegis.consolidation._STATE_PATH", state_path):
            _save_state({"last_run": 12345.0, "last_rollover": "2026-01-01"})
            loaded = _load_state()
            assert loaded["last_run"] == 12345.0
            assert loaded["last_rollover"] == "2026-01-01"
