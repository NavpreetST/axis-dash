"""CR Watcher -- polls open PRs for CodeRabbit and triggers forge heal."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid

import httpx

from aegis.observability import eventlog

log = logging.getLogger(__name__)

_REPOS = ["NavpreetST/helios", "NavpreetST/axis-dash"]
_POLL_INTERVAL_S = float(os.getenv("AEGIS_CR_WATCHER_INTERVAL", "60"))
_CODERABBIT_LOGIN = "coderabbitai[bot]"
_GITHUB_API = "https://api.github.com"
_MAX_HEAL_ITERATIONS = int(os.getenv("FORGE_CR_MAX_ITERATIONS", "3"))
_HEAL_ENABLED = os.getenv("AEGIS_CR_WATCHER_ENABLED", "true").lower() in ("true", "1", "yes")
_HEAL_BASE = os.getenv("AEGIS_FORGE_HEAL_URL", "http://localhost:8080/forge/heal")
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


async def _trigger_heal(task_id: str) -> dict:
    try:
        token = os.environ.get("HELIOS_TOKEN", "")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(f"{_HEAL_BASE}/{task_id}", headers=headers)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning("cr_watcher: heal trigger failed -- %s", e)
        return {"healed": False, "error": str(e), "iterations": 0}


async def _create_supabase_task(repo: str, pr_number: int, branch: str, spec: str) -> str | None:
    su_url = os.environ.get("SUPABASE_URL", "")
    su_key = os.environ.get("SERVICE_ROLE", "") or os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not su_url or not su_key:
        log.warning("cr_watcher: cannot create task -- SUPABASE_URL or SERVICE_ROLE not set")
        return None
    task_id = str(uuid.uuid4())
    payload = {
        "title": spec[:200],
        "description": spec,
        "phase": "forge",
        "status": "open",
        "repo": repo,
        "pr_number": pr_number,
        "branch": branch,
    }
    anon_key = os.environ.get("SUPABASE_ANON_KEY", "")
    headers = {"apikey": anon_key or su_key, "Authorization": f"Bearer {su_key}", "Content-Type": "application/json", "Prefer": "return=representation"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(f"{su_url}/rest/v1/tasks?select=id", json=payload, headers=headers)
        if r.status_code in (200, 201, 204):
            rows = r.json()
            if isinstance(rows, list) and rows:
                task_id = str(rows[0].get("id", task_id))
            log.info("cr_watcher: created task %s for PR #%s in %s", task_id, pr_number, repo)
            return task_id
        else:
            log.warning("cr_watcher: failed to create task -- %s %s", r.status_code, r.text[:200])
            return None
    except Exception as e:
        log.warning("cr_watcher: supabase task creation error -- %s", e)
        return None


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

    result = {}
    if _HEAL_ENABLED:
        spec_lines = [f"- {f['path']}: {f['body']}" for f in findings]
        sep = "\\n"
        spec = "CR findings for PR #%d in %s%s" % (pr_number, repo, sep) + sep.join(spec_lines)
        task_id = await _create_supabase_task(repo, pr_number, branch, spec)
        if task_id:
            result = await _trigger_heal(task_id)

    success = result.get("healed", False)
    iterations = result.get("iterations", 0)
    log.info("CR watcher: PR #%s in %s -- %d findings -- healed in %d iterations",
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
                     "reason": f"exceeded {_MAX_HEAL_ITERATIONS} iterations -- needs human review"},
            severity="warn", sensitivity="internal",
        )

    if success:
        _healed_prs.add(key)


async def run() -> None:
    log.info("cr_watcher: polling %d repos every %ds", len(_REPOS), _POLL_INTERVAL_S)
    while True:
        for repo in _REPOS:
            try:
                for pr in await _gh_get(f"{_GITHUB_API}/repos/{repo}/pulls?state=open&per_page=20"):
                    await _process_pr(repo, pr)
            except Exception as e:
                log.warning("cr_watcher: error processing %s -- %s", repo, e)
        await asyncio.sleep(_POLL_INTERVAL_S)
