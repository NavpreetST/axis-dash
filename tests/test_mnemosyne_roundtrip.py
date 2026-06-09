import sqlite3

import pytest

from aegis.mnemosyne.db import SCHEMA


def test_schema_applies_clean():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    assert "episodes" in tables


# --- F2: write gate logic ---

WRITE_THRESHOLD = 0.3


def _simulate_score(reward: float, novelty: float, threat: float) -> float:
    return novelty + abs(reward) + threat


def _should_write(score: float, last_emb: list | None) -> bool:
    """Replication of the corrected write gate logic (F2 fix: or)."""
    if score < WRITE_THRESHOLD or last_emb is None:
        return False
    return True


def test_write_gate_high_score_with_embedding_writes():
    assert _should_write(score=1.0, last_emb=[0.1, 0.2]) is True


def test_write_gate_low_score_no_embedding_skips():
    assert _should_write(score=0.0, last_emb=None) is False


def test_write_gate_low_score_with_embedding_skips():
    assert _should_write(score=0.1, last_emb=[0.1, 0.2]) is False


def test_write_gate_high_score_no_embedding_skips():
    assert _should_write(score=0.5, last_emb=None) is False
