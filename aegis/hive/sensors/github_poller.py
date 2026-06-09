"""GitHub poller sensor — polls GitHub API for PRs, issues, commits.

Publishes pr_events to NeuroBus channel "sensor.github".  Rate-limited to
1 request per 60 seconds.  Uses gh CLI (requires auth via `gh auth login`).

Usage:
    from aegis.hive.sensors.github_poller import run
    await run()
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

from aegis.nexus.bus import BUS

log = logging.getLogger("hive.sensors.github_poller")

POLL_INTERVAL_S = 60
REPOS = ["NavpreetST/helios", "axis-dash"]
_prev_prs: dict[str, set[int]] = {}


async def _fetch_prs(repo: str) -> list[dict]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "gh", "pr", "list", "--repo", repo, "--state", "open",
            "--json", "number,title,author,createdAt,headRefName,baseRefName,url",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            log.warning("github_poller: gh pr list failed for %s: %s", repo, stderr.decode())
            return []
        return json.loads(stdout.decode())
    except Exception as e:
        log.warning("github_poller: error fetching PRs for %s: %s", repo, e)
        return []


async def run() -> None:
    log.info("github_poller sensor started (interval=%ds)", POLL_INTERVAL_S)
    for repo in REPOS:
        _prev_prs[repo] = set()
    while True:
        for repo in REPOS:
            prs = await _fetch_prs(repo)
            current_ids: set[int] = {p["number"] for p in prs}
            new_ids = current_ids - _prev_prs[repo]
            for pr in prs:
                if pr["number"] in new_ids:
                    await BUS.publish("sensor.github", {
                        "event": "pr_opened",
                        "repo": repo,
                        "pr": pr["number"],
                        "title": pr["title"],
                        "author": pr["author"]["login"],
                        "url": pr["url"],
                        "ts": datetime.now(UTC).isoformat(),
                    })
                    log.info("github_poller: new PR #%d in %s", pr["number"], repo)
            _prev_prs[repo] = current_ids
        await asyncio.sleep(POLL_INTERVAL_S)
