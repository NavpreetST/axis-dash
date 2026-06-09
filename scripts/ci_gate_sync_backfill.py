#!/usr/bin/env python3
"""ci_gate_sync_backfill.py — Backfill gate_status for all merged PRs.

Queries GitHub API for check runs on each PR, maps them to gate names,
and upserts to Supabase gate_status table.

Usage:
    python scripts/ci_gate_sync_backfill.py \
        --repo NavpreetST/helios \
        --pr-range 25-45

Requires:
    SUPABASE_URL, SUPABASE_SERVICE_KEY env vars.
    GITHUB_TOKEN env var (optional, raises rate limit from 60→5000/hr).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")
GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
REQUEST_TIMEOUT: int = 15

# Gate name mapping: check run name → gate_name
# Covers all known naming conventions from CI workflow
_GATE_NAME_MAP: dict[str, str] = {
    "lint": "lint",
    "ruff": "lint",
    "Gate 1 · Lint": "lint",
    "Gate 1 - Lint": "lint",
    "tests": "tests",
    "pytest": "tests",
    "Gate 2 · Tests": "tests",
    "Gate 2 - Tests": "tests",
    "drift_guard": "drift_guard",
    "Drift Guard": "drift_guard",
    "Gate 4 · Drift Guard": "drift_guard",
    "Gate 4 - Drift Guard": "drift_guard",
    "Drift / state guard": "drift_guard",
    "Drift / arch guard": "drift_guard",
    "coderabbit": "coderabbit",
    "CodeRabbit": "coderabbit",
    "Gate 3 · CodeRabbit": "coderabbit",
    "Gate 3 - CodeRabbit": "coderabbit",
}

# Gate names we care about (skip coderabbit — advisory only)
_TRACKED_GATES = frozenset({"lint", "tests", "drift_guard"})


# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------
def _gh_get(path: str) -> dict | list | None:
    """GET from GitHub REST API. Returns parsed JSON or None."""
    url = f"https://api.github.com{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        print(f"[backfill] GitHub API {e.code}: {body}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[backfill] GitHub API error: {e}", file=sys.stderr)
        return None


def get_pr_check_runs(repo: str, pr_number: int) -> list[dict]:
    """Get all check runs for a PR's head commit."""
    # Get PR details to find head SHA
    pr = _gh_get(f"/repos/{repo}/pulls/{pr_number}")
    if not pr or "head" not in pr:
        return []

    head_sha = pr["head"]["sha"]

    # Get check runs for the head commit
    result = _gh_get(f"/repos/{repo}/commits/{head_sha}/check-runs")
    if not result or "check_runs" not in result:
        return []

    return result["check_runs"]


# ---------------------------------------------------------------------------
# Supabase upsert
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
        print(f"[backfill] Supabase HTTP {e.code}: {body}", file=sys.stderr)
        return e.code
    except Exception as e:
        print(f"[backfill] Supabase error: {e}", file=sys.stderr)
        return 0


def upsert_gate_status(
    *,
    repo: str,
    pr_number: int,
    gate_name: str,
    status: str,
    conclusion: str = "",
    run_url: str = "",
    started_at: str = "",
    completed_at: str = "",
) -> int:
    """Upsert a gate_status row."""
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "repo": repo,
        "pr_number": pr_number,
        "gate_name": gate_name,
        "status": status,
        "conclusion": conclusion or status,
        "started_at": started_at or now,
        "completed_at": completed_at or now,
        "run_url": run_url,
        "updated_at": now,
    }
    code = _post("gate_status", row, upsert=True)
    if 200 <= code < 300:
        print(f"  ✅ {gate_name} → {status}")
    else:
        print(f"  ❌ {gate_name} → {status} (HTTP {code})")
    return code


# ---------------------------------------------------------------------------
# Backfill logic
# ---------------------------------------------------------------------------
def _map_gate_name(check_run_name: str) -> str | None:
    """Map a check run name to a canonical gate name."""
    # Try exact match first
    if check_run_name in _GATE_NAME_MAP:
        return _GATE_NAME_MAP[check_run_name]

    # Try case-insensitive partial match (require >=5 chars to avoid false positives)
    lower = check_run_name.lower()
    for key, gate in _GATE_NAME_MAP.items():
        if len(key) >= 5 and key.lower() in lower:
            return gate
        if len(lower) >= 5 and lower in key.lower():
            return gate

    return None


def _conclusion_to_status(conclusion: str) -> str:
    """Map GitHub check run conclusion to our status enum."""
    if conclusion == "success":
        return "success"
    elif conclusion in ("failure", "cancelled", "timed_out"):
        return "failure"
    elif conclusion == "skipped":
        return "skipped"
    else:
        return "pending"


def backfill_pr(repo: str, pr_number: int) -> dict[str, str]:
    """Backfill gate_status for a single PR. Returns {gate_name: status}."""
    print(f"PR #{pr_number}...")

    check_runs = get_pr_check_runs(repo, pr_number)
    if not check_runs:
        print(f"  ⚠️  No check runs found")
        return {}

    results: dict[str, str] = {}

    for cr in check_runs:
        name = cr.get("name", "")
        conclusion = cr.get("conclusion", "") or ""
        status_gh = cr.get("status", "")  # "completed", "in_progress", "queued"
        html_url = cr.get("html_url", "")
        started_at = cr.get("started_at", "")
        completed_at = cr.get("completed_at", "")

        gate_name = _map_gate_name(name)
        if not gate_name or gate_name not in _TRACKED_GATES:
            continue

        # Determine status
        if status_gh != "completed":
            status = "pending"
        else:
            status = _conclusion_to_status(conclusion)

        results[gate_name] = status
        upsert_gate_status(
            repo=repo,
            pr_number=pr_number,
            gate_name=gate_name,
            status=status,
            conclusion=conclusion,
            run_url=html_url,
            started_at=started_at,
            completed_at=completed_at,
        )

    if not results:
        print(f"  ⚠️  No tracked gates found in {len(check_runs)} check runs")

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print("[backfill] skipped (no SUPABASE_URL / SUPABASE_SERVICE_KEY)", file=sys.stderr)
        return 0

    parser = argparse.ArgumentParser(description="Backfill gate_status for merged PRs")
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--pr-range", required=True, help="PR range, e.g. 25-45 or 30,31,32")
    args = parser.parse_args()

    # Parse PR range with validation
    prs: list[int] = []
    for part in args.pr_range.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                start_str, end_str = part.split("-", 1)
                start, end = int(start_str), int(end_str)
                if start < 1 or end < start:
                    print(f"[backfill] invalid range: {part}", file=sys.stderr)
                    return 1
                prs.extend(range(start, end + 1))
            else:
                num = int(part)
                if num < 1:
                    print(f"[backfill] invalid PR number: {part}", file=sys.stderr)
                    return 1
                prs.append(num)
        except ValueError:
            print(f"[backfill] invalid PR range input: {part}", file=sys.stderr)
            return 1

    if not prs:
        print("[backfill] no PR numbers to process", file=sys.stderr)
        return 1

    print(f"Backfilling gate_status for {len(prs)} PRs ({prs[0]}–{prs[-1]})...")
    print(f"Repo: {args.repo}")
    print()

    total_gates = 0
    total_upserts = 0

    for pr_num in prs:
        results = backfill_pr(args.repo, pr_num)
        total_gates += len(results)
        # Rate-limit: 60/hr unauthenticated, 5000/hr authenticated
        if GITHUB_TOKEN:
            time.sleep(0.5)
        else:
            print("  ⚠️  No GITHUB_TOKEN — sleeping 60s to stay within rate limit (60/hr)")
            print("  💡  Set GITHUB_TOKEN env var for 5000/hr limit")
            time.sleep(60)
        print()

    print(f"Done. {total_gates} gate statuses upserted across {len(prs)} PRs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
