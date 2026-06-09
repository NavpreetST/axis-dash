#!/usr/bin/env python3
"""ci_coverage_sync.py — Push test coverage % to Supabase after CI run.

Reads coverage.json (from pytest --cov-report=json), extracts total %,
and upserts to Supabase coverage table.

Usage:
    python scripts/ci_coverage_sync.py \\
        --repo NavpreetST/helios \\
        --pr-number 42 \\
        --commit-sha abc1234

Requires SUPABASE_URL and SUPABASE_SERVICE_KEY env vars.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")
REQUEST_TIMEOUT: int = 15
COVERAGE_JSON: Path = Path("coverage.json")


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only)
# ---------------------------------------------------------------------------
def _post(path: str, payload: dict, *, upsert: bool = False) -> int:
    """POST to Supabase REST API."""
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    data = json.dumps(payload).encode("utf-8")

    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates" if upsert else "return=minimal",
    }

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        print(f"[coverage-sync] HTTP {e.code}: {body}", file=sys.stderr)
        return e.code
    except Exception as e:
        print(f"[coverage-sync] error: {e}", file=sys.stderr)
        return 0


# ---------------------------------------------------------------------------
# Coverage parsing
# ---------------------------------------------------------------------------
def parse_coverage(path: Path) -> dict | None:
    """Parse coverage.json and return summary dict."""
    if not path.exists():
        print(f"[coverage-sync] {path} not found", file=sys.stderr)
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"[coverage-sync] failed to parse {path}: {e}", file=sys.stderr)
        return None

    totals = data.get("totals", {})
    return {
        "total_pct": round(totals.get("percent_covered", 0), 2),
        "covered_lines": totals.get("covered_lines", 0),
        "missing_lines": totals.get("missing_lines", 0),
        "num_statements": totals.get("num_statements", 0),
    }


# ---------------------------------------------------------------------------
# Supabase upsert
# ---------------------------------------------------------------------------
def upsert_coverage(
    *,
    repo: str,
    pr_number: int,
    commit_sha: str,
    total_pct: float,
    covered_lines: int,
    missing_lines: int,
    num_statements: int,
) -> int:
    """Upsert a coverage row. Uses PR number as unique key."""
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "repo": repo,
        "pr_number": pr_number,
        "commit_sha": commit_sha,
        "total_pct": total_pct,
        "covered_lines": covered_lines,
        "missing_lines": missing_lines,
        "num_statements": num_statements,
        "created_at": now,
    }

    code = _post("coverage", row, upsert=True)
    if 200 <= code < 300:
        print(f"[coverage-sync] upserted: {repo}#{pr_number} = {total_pct}%")
    else:
        print(f"[coverage-sync] failed ({code}): {repo}#{pr_number}")
    return code


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print("[coverage-sync] skipped (no SUPABASE_URL / SUPABASE_SERVICE_KEY)", file=sys.stderr)
        return 0

    parser = argparse.ArgumentParser(description="Push coverage to Supabase")
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--commit-sha", default="", help="Git commit SHA")
    parser.add_argument("--coverage-json", default="coverage.json", help="Path to coverage.json")
    args = parser.parse_args()

    coverage_path = Path(args.coverage_json)
    summary = parse_coverage(coverage_path)
    if not summary:
        return 1

    print(f"[coverage-sync] {summary['total_pct']}% ({summary['covered_lines']}/{summary['num_statements']} lines)")

    return upsert_coverage(
        repo=args.repo,
        pr_number=args.pr_number,
        commit_sha=args.commit_sha,
        total_pct=summary["total_pct"],
        covered_lines=summary["covered_lines"],
        missing_lines=summary["missing_lines"],
        num_statements=summary["num_statements"],
    )


if __name__ == "__main__":
    raise SystemExit(main())
