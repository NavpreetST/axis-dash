#!/usr/bin/env python3
"""test_ci_coverage_sync.py — Tests for ci_coverage_sync.py."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from ci_coverage_sync import parse_coverage, upsert_coverage


# ---------------------------------------------------------------------------
# parse_coverage
# ---------------------------------------------------------------------------
class TestParseCoverage:
    def test_returns_none_for_missing_file(self):
        assert parse_coverage(Path("nonexistent.json")) is None

    def test_parses_valid_coverage_json(self):
        data = {
            "totals": {
                "num_statements": 500,
                "covered_lines": 425,
                "missing_lines": 75,
                "percent_covered": 85.0,
            }
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f_path = f.name

        try:
            result = parse_coverage(Path(f_path))
            assert result is not None
            assert result["total_pct"] == 85.0
            assert result["covered_lines"] == 425
            assert result["missing_lines"] == 75
            assert result["num_statements"] == 500
        finally:
            Path(f_path).unlink()

    def test_handles_empty_totals(self):
        data = {"totals": {}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f_path = f.name

        try:
            result = parse_coverage(Path(f_path))
            assert result is not None
            assert result["total_pct"] == 0.0
        finally:
            Path(f_path).unlink()

    def test_returns_none_for_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not json {{{")
            f_path = f.name

        try:
            assert parse_coverage(Path(f_path)) is None
        finally:
            Path(f_path).unlink()

    def test_rounds_percentage(self):
        data = {"totals": {"percent_covered": 85.123456}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f_path = f.name

        try:
            result = parse_coverage(Path(f_path))
            assert result["total_pct"] == 85.12
        finally:
            Path(f_path).unlink()


# ---------------------------------------------------------------------------
# upsert_coverage
# ---------------------------------------------------------------------------
class TestUpsertCoverage:
    @patch("ci_coverage_sync._post")
    def test_upsert_success(self, mock_post):
        mock_post.return_value = 201
        code = upsert_coverage(
            repo="NavpreetST/helios",
            pr_number=42,
            commit_sha="abc1234",
            total_pct=85.0,
            covered_lines=425,
            missing_lines=75,
            num_statements=500,
        )
        assert code == 201
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "coverage"
        assert call_args[0][1]["total_pct"] == 85.0
        assert call_args[0][1]["pr_number"] == 42
        assert call_args[1]["upsert"] is True

    @patch("ci_coverage_sync._post")
    def test_upsert_failure(self, mock_post):
        mock_post.return_value = 500
        code = upsert_coverage(
            repo="NavpreetST/helios",
            pr_number=42,
            commit_sha="abc1234",
            total_pct=0,
            covered_lines=0,
            missing_lines=0,
            num_statements=0,
        )
        assert code == 500
