#!/usr/bin/env python3
"""ci_gate_sync.py — Upload CI gate results to Supabase after each PR run.

Reads SUPABASE_URL + SUPABASE_SERVICE_KEY from environment (GitHub Secrets).
Upserts gate results to gate_status table. Posts to task_activity on merge.

Usage:
    python scripts/ci_gate_sync.py gate \\
        --gate-name lint \\
        --status success \\
        --pr-number 39 \\
        --repo NavpreetST/helios \\
        --run-url https://github.com/.../actions/runs/123

    python scripts/ci_gate_sync.py merge \\
        --pr-number 39 \\
        --repo NavpreetST/helios \\
        --detail "Merged feat/nim-context-pack"

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


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")
REQUEST_TIMEOUT: int = 15


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only — no httpx in CI)
# ---------------------------------------------------------------------------


def _post(path: str, payload: dict, *, upsert: bool = False) -> int:
    """POST to Supabase REST API. Returns HTTP status code."""
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
        # Log but don't fail CI — gate sync is best-effort
        body = e.read().decode("utf-8", errors="replace")[:200]
        print(f"[gate-sync] HTTP {e.code}: {body}", file=sys.stderr)
        return e.code
    except Exception as e:
        print(f"[gate-sync] error: {e}", file=sys.stderr)
        return 0


# ---------------------------------------------------------------------------
# Gate status upsert
# ---------------------------------------------------------------------------

_VALID_STATUSES = frozenset({"success", "failure", "pending", "skipped"})


def upsert_gate_status(
    *,
    repo: str,
    pr_number: int,
    gate_name: str,
    status: str,
    conclusion: str = "",
    started_at: str = "",
    completed_at: str = "",
    run_url: str = "",
) -> int:
    """Upsert a gate_status row. Uses POST with resolution=merge-duplicates."""
    if status not in _VALID_STATUSES:
        print(f"[gate-sync] invalid status: {status}", file=sys.stderr)
        return 400

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
        print(f"[gate-sync] gate_status upserted: {repo}#{pr_number}/{gate_name} → {status}")
    else:
        print(f"[gate-sync] gate_status failed ({code}): {repo}#{pr_number}/{gate_name}")
    return code


# ---------------------------------------------------------------------------
# Task activity (on merge)
# ---------------------------------------------------------------------------


def post_task_activity(
    *,
    repo: str,
    pr_number: int,
    action: str,
    detail: str = "",
) -> int:
    """POST a task_activity row (action: merged, opened, closed)."""
    now = datetime.now(timezone.utc).isoformat()

    row = {
        "repo": repo,
        "pr_number": pr_number,
        "action": action,
        "detail": detail,
        "created_at": now,
    }

    code = _post("task_activity", row, upsert=False)
    if 200 <= code < 300:
        print(f"[gate-sync] task_activity posted: {action} {repo}#{pr_number}")
    else:
        print(f"[gate-sync] task_activity failed ({code}): {action} {repo}#{pr_number}")
    return code


# ---------------------------------------------------------------------------
# Bulk gate sync (all gates for a PR)
# ---------------------------------------------------------------------------


def sync_all_gates(
    *,
    repo: str,
    pr_number: int,
    lint: str = "pending",
    tests: str = "pending",
    drift_guard: str = "pending",
    run_url: str = "",
) -> None:
    """Upsert all gate statuses for a PR in one call."""
    for gate_name, status in [
        ("lint", lint),
        ("tests", tests),
        ("drift_guard", drift_guard),
    ]:
        if status and status != "pending":
            upsert_gate_status(
                repo=repo,
                pr_number=pr_number,
                gate_name=gate_name,
                status=status,
                run_url=run_url,
            )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print("[gate-sync] skipped (no SUPABASE_URL / SUPABASE_SERVICE_KEY)", file=sys.stderr)
        return 0

    parser = argparse.ArgumentParser(description="Sync CI gate results to Supabase")
    sub = parser.add_subparsers(dest="command", required=True)

    # --- gate subcommand ---
    gate_p = sub.add_parser("gate", help="Upsert a gate_status row")
    gate_p.add_argument("--gate-name", required=True, help="Gate name (lint, tests, drift_guard)")
    gate_p.add_argument("--status", required=True, choices=sorted(_VALID_STATUSES))
    gate_p.add_argument("--pr-number", type=int, required=True)
    gate_p.add_argument("--repo", required=True, help="owner/repo")
    gate_p.add_argument("--run-url", default="", help="GitHub Actions run URL")
    gate_p.add_argument("--conclusion", default="", help="Gate conclusion detail")
    gate_p.add_argument("--started-at", default="", help="ISO timestamp")
    gate_p.add_argument("--completed-at", default="", help="ISO timestamp")

    # --- merge subcommand ---
    merge_p = sub.add_parser("merge", help="Post a task_activity row")
    merge_p.add_argument("--pr-number", type=int, required=True)
    merge_p.add_argument("--repo", required=True, help="owner/repo")
    merge_p.add_argument("--detail", default="", help="Merge detail text")

    # --- bulk subcommand ---
    bulk_p = sub.add_parser("bulk", help="Upsert all gates for a PR")
    bulk_p.add_argument("--pr-number", type=int, required=True)
    bulk_p.add_argument("--repo", required=True, help="owner/repo")
    bulk_p.add_argument("--lint", default="pending", choices=sorted(_VALID_STATUSES))
    bulk_p.add_argument("--tests", default="pending", choices=sorted(_VALID_STATUSES))
    bulk_p.add_argument("--drift-guard", default="pending", choices=sorted(_VALID_STATUSES))
    bulk_p.add_argument("--run-url", default="", help="GitHub Actions run URL")

    args = parser.parse_args()

    if args.command == "gate":
        upsert_gate_status(
            repo=args.repo,
            pr_number=args.pr_number,
            gate_name=args.gate_name,
            status=args.status,
            conclusion=args.conclusion,
            started_at=args.started_at,
            completed_at=args.completed_at,
            run_url=args.run_url,
        )
    elif args.command == "merge":
        post_task_activity(
            repo=args.repo,
            pr_number=args.pr_number,
            action="merged",
            detail=args.detail,
        )
    elif args.command == "bulk":
        sync_all_gates(
            repo=args.repo,
            pr_number=args.pr_number,
            lint=args.lint,
            tests=args.tests,
            drift_guard=args.drift_guard,
            run_url=args.run_url,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
