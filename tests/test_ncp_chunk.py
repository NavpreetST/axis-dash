"""Tests for NCP chunk division guard (F3)."""
import pytest

WM_DIM = 48


def _chunk_size(emb_len: int) -> int:
    """Replicates the F3 fix: max(1, len(emb) // WM_DIM)."""
    return max(1, emb_len // WM_DIM)


def test_chunk_normal_384():
    """Standard MiniLM embedding (384 dims)."""
    c = _chunk_size(384)
    assert c == 8  # 384 // 48


def test_chunk_shorter_than_wm_dim():
    """Embedding shorter than WM_DIM — must not zero-divide."""
    c = _chunk_size(32)
    assert c == 1


def test_chunk_exactly_wm_dim():
    c = _chunk_size(48)
    assert c == 1


def test_chunk_partial_slot():
    c = _chunk_size(95)
    assert c == 1  # 95 // 48 = 1


def test_chunk_empty_embedding():
    c = _chunk_size(0)
    assert c == 1  # 0 // 48 = 0 -> max(1, 0) = 1
