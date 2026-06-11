"""CR Watcher — polls open PRs for CodeRabbit and triggers forge heal."""

from __future__ import annotations

import asyncio
import logging
import os
import re

import httpx

from aegis.observability import eventlog

log = logging.getLogger(__name__)

_REPOS = ["NavpreetST/helios", "NavpreetST/axis-dash"]
_POLL_INTERVAL_S = float(os.getenv("AEGIS_CR_WATCHER_INTERVAL", "60"))
_CODERABBIT_LOGIN = "coderabbitai[bot]"
_GITHUB_API = "https://api.github.com"
_MAX_HEAL_ITERATIONS = int(os.getenv("FORGE_CR_MAX_ITERATIONS", "3"))
_HEAL_ENABLED = os.getenv("AEGIS_CR_WATCHER_ENABLED", "true").lower() in ("true", "1", "yes")
_HEAL_URL = os.getenv("AEGIS_FORGE_HEAL_URL", "http://localhost:8080/forge/heal/0")
_healed_prs: set[str] = set()


async def _gh_get(url: str) -> list[dict]:
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.get(url, headers=headers)
    r.raise_for_status()
    return r.json()


async def _trigger_heal(repo: str, pr_number: int, branch: str) -> dict:
    try:
        params = {"repo": repo, "pr": str(pr_number), "branch": branch}
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(_HEAL_URL, params=params)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning("cr_watcher: heal trigger failed — %s", e)
        return {"healed": False, "error": str(e), "iterations": 0}


async def _process_pr(repo: str, pr: dict) -> None:
    pr_number = pr["number"]
    branch = pr["head"]["ref"]
    key = f"{repo}#{pr_number}"
    if key in _healed_prs:
        return

    reviews = await _gh_get(f"{_GITHUB_API}/repos/{repo}/pulls/{pr_number}/reviews?per_page=10")
    cr_reviews = [r for r in reviews if r.get("user", {}).get("login") == _CODERABBIT_LOGIN]
    if not cr_reviews or cr_reviews[-1].get("state", "") == "APPROVED":
        return
    review_state = cr_reviews[-1].get("state", "")
    if review_state not in ("CHANGES_REQUESTED", "COMMENTED"):
        return

    comments = await _gh_get(f"{_GITHUB_API}/repos/{repo}/pulls/{pr_number}/comments?per_page=50")
    findings = [
        {"path": c.get("path", ""), "body": c.get("body", "")[:200]}
        for c in comments if c.get("user", {}).get("login") == _CODERABBIT_LOGIN
    ]

    await eventlog.log_event(
        source="cr_watcher", event_type="cr_changes_requested",
        payload={"repo": repo, "pr_number": pr_number, "branch": branch,
                 "finding_count": len(findings), "findings": findings},
        severity="warn", sensitivity="internal",
    )

    if _HEAL_ENABLED:
        result = await _trigger_heal(repo, pr_number, branch)
    else:
        result = {}
    success = result.get("healed", False)
    iterations = result.get("iterations", 0)
    log.info("CR watcher: PR #%s in %s — %d findings — healed in %d iterations",
             pr_number, repo, len(findings), iterations)

    await eventlog.log_event(
        source="cr_watcher", event_type="cr_heal_attempt",
        payload={"pr_number": pr_number, "repo": repo, "success": success, "iterations": iterations},
        severity="info", sensitivity="internal",
    )

    if iterations >= _MAX_HEAL_ITERATIONS:
        body = cr_reviews[-1].get("body", "")
        finding_match = re.search(r"Actionable comments posted: (\d+)", body)
        finding_count = int(finding_match.group(1)) if finding_match else 0
        await eventlog.log_event(
            source="cr_watcher", event_type="cr_flag",
            payload={"pr_number": pr_number, "repo": repo,
                     "reason": f"exceeded {_MAX_HEAL_ITERATIONS} iterations — needs human review"},
            severity="warn", sensitivity="internal",
        )

    _healed_prs.add(key)


async def run() -> None:
    log.info("cr_watcher: polling %d repos every %ds", len(_REPOS), _POLL_INTERVAL_S)
    while True:
        for repo in _REPOS:
            try:
                for pr in await _gh_get(f"{_GITHUB_API}/repos/{repo}/pulls?state=open&per_page=20"):
                    await _process_pr(repo, pr)
            except Exception as e:
                log.warning("cr_watcher: error processing %s — %s", repo, e)
        await asyncio.sleep(_POLL_INTERVAL_S)
