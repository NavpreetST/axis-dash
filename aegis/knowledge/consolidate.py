"""NIM deep knowledge consolidation — batch synthesis of helios_knowledge.db.

Groups unconsolidated entries by category, feeds each group to Nemotron-120B
for deep synthesis, and writes five markdown reports:

    consolidated/theory.md
    consolidated/roadmap.md
    consolidated/research.md
    consolidated/todos.md
    consolidated/drift-report.md

Usage:
    python -m aegis.knowledge.consolidate
    python -m aegis.knowledge.consolidate --dry-run
    python -m aegis.knowledge.consolidate --category theory,roadmap

Environment:
    NVIDIA_API_KEY          — NIM auth (required)
    AEGIS_STATE_DIR         — runtime state dir (default: /var/lib/aegis)
    AEGIS_KNOWLEDGE_DB      — path to knowledge DB (default: STATE_DIR/helios_knowledge.db)
    AEGIS_KNOWLEDGE_OUTPUT  — output dir for reports (default: STATE_DIR/consolidated)
    AEGIS_NIM_MODEL         — NIM model override (default: nvidia/nemotron-3-super-120b-a12b)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from aegis.nim_budget import NIM_BUDGET

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
NIM_ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"
NIM_MODEL = os.getenv("AEGIS_NIM_MODEL", "nvidia/nemotron-3-super-120b-a12b")
MAX_RETRIES = 5
INITIAL_BACKOFF = 1.0
BACKOFF_CAP = 30.0
NIM_TIMEOUT = 120.0  # generous for deep synthesis

STATE_DIR = Path(os.getenv("AEGIS_STATE_DIR", "/var/lib/aegis"))
DB_PATH = Path(os.getenv("AEGIS_KNOWLEDGE_DB", str(STATE_DIR / "helios_knowledge.db")))
OUTPUT_DIR = Path(os.getenv("AEGIS_KNOWLEDGE_OUTPUT", str(STATE_DIR / "consolidated")))

CATEGORIES: list[str] = ["theory", "roadmap", "research", "todos", "drift"]

OUTPUT_FILES: dict[str, str] = {
    "theory": "theory.md",
    "roadmap": "roadmap.md",
    "research": "research.md",
    "todos": "todos.md",
    "drift": "drift-report.md",
}

# ── Synthesis prompts ────────────────────────────────────────────────────────

SYNTHESIS_PROMPTS: dict[str, str] = {
    "theory": """\
You are a deep-research synthesis engine. Synthesize the following knowledge \
entries into a cohesive theory document. Identify patterns, principles, and \
cross-cutting insights. Produce well-structured markdown with headings, \
evidence chains, and open questions.

Category: theory
Entries:
{entries}
""",
    "roadmap": """\
You are a strategic planning engine. Synthesize the following knowledge \
entries into a prioritized roadmap. Include timelines, dependencies, risk \
assessments, and milestone definitions. Produce well-structured markdown.

Category: roadmap
Entries:
{entries}
""",
    "research": """\
You are a research synthesis engine. Synthesize the following knowledge \
entries into a research document. Cover methodology, findings, data sources, \
confidence levels, and reproducibility notes. Produce well-structured markdown \
with references.

Category: research
Entries:
{entries}
""",
    "todos": """\
You are a task tracking engine. Synthesize the following knowledge entries \
into an actionable todo document. Group by priority, assign ownership where \
implied, include acceptance criteria and dependencies. Produce markdown.

Category: todos
Entries:
{entries}
""",
    "drift": """\
You are a drift analysis engine. Compare the following new synthesis against \
the previous baseline (if any). Identify deltas, regressions, new patterns, \
and broken assumptions. Rate drift severity as NONE / LOW / MEDIUM / HIGH. \
Produce a markdown drift report.

Previous baseline:
{previous}

New synthesis:
{current}
""",
}

# ── DB helpers ───────────────────────────────────────────────────────────────

DB_SCHEMA = """\
CREATE TABLE IF NOT EXISTS knowledge (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category    TEXT    NOT NULL,
    title       TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    source      TEXT,
    tags        TEXT,
    ts          REAL    NOT NULL,
    embedding   BLOB,
    consolidated INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_knowledge_category ON knowledge(category);
CREATE INDEX IF NOT EXISTS idx_knowledge_consolidated ON knowledge(consolidated);
CREATE INDEX IF NOT EXISTS idx_knowledge_ts ON knowledge(ts);
"""


def _init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(DB_SCHEMA)
    conn.commit()
    return conn


def _get_unconsolidated_by_category(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    rows = conn.execute(
        "SELECT id, category, title, content, source, ts FROM knowledge "
        "WHERE consolidated = 0 ORDER BY category, ts ASC"
    ).fetchall()
    groups: dict[str, list[dict]] = {}
    for r in rows:
        cat = r["category"] if isinstance(r, sqlite3.Row) else r[1]
        groups.setdefault(cat, []).append({
            "id": r[0],
            "category": r[1],
            "title": r[2],
            "content": r[3],
            "source": r[4],
            "ts": r[5],
        })
    return groups


def _mark_consolidated(conn: sqlite3.Connection, ids: list[int]) -> None:
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    conn.execute(
        f"UPDATE knowledge SET consolidated = 1 WHERE id IN ({placeholders})",
        ids,
    )
    conn.commit()


# ── NIM client ───────────────────────────────────────────────────────────────

async def _call_nim(payload: dict) -> dict | None:
    # Spin-wait on budget — does NOT count against MAX_RETRIES
    while True:
        wait = NIM_BUDGET.wait_s()
        if wait > 0:
            log.debug("consolidate: rate-limited, sleeping %.1fs", wait)
            await asyncio.sleep(wait)
        if NIM_BUDGET.allow():
            break
        log.debug("consolidate: budget exhausted, sleeping 1s")
        await asyncio.sleep(1.0)

    backoff = INITIAL_BACKOFF
    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=NIM_TIMEOUT) as client:
                r = await client.post(
                    NIM_ENDPOINT,
                    headers={
                        "Authorization": f"Bearer {NVIDIA_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                if r.status_code == 429:
                    log.warning("consolidate: NIM 429, backoff %.1fs", backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, BACKOFF_CAP)
                    continue
                r.raise_for_status()
                return r.json()
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as e:
            log.warning("consolidate: NIM network error (attempt %d): %s", attempt + 1, e)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_CAP)
        except httpx.HTTPStatusError as e:
            if e.response.status_code >= 500:
                log.warning("consolidate: NIM server error %d (attempt %d)", e.response.status_code, attempt + 1)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, BACKOFF_CAP)
            else:
                log.error("consolidate: NIM client error %d: %s", e.response.status_code, e)
                return None
        except Exception as e:
            log.warning("consolidate: NIM unexpected error (attempt %d): %s", attempt + 1, e)
            return None
    log.error("consolidate: NIM call failed after %d retries", MAX_RETRIES)
    return None


async def _synthesize_category(category: str, entries: list[dict]) -> str | None:
    entries_text = "\n\n".join(
        f"## {e['title']}\n\n{e['content']}\n\n*Source: {e['source'] or 'unknown'} | TS: {e['ts']}*"
        for e in entries
    )
    prompt = SYNTHESIS_PROMPTS[category].format(entries=entries_text)

    payload = {
        "model": NIM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4096,
        "temperature": 0.3,
    }

    response = await _call_nim(payload)
    if not response:
        return None

    try:
        return response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as e:
        log.warning("consolidate: malformed NIM response for %s: %s", category, e)
        return None


async def _generate_drift_report(output_dir: Path, new_synthesis: dict[str, str]) -> str | None:
    previous: dict[str, str] = {}
    for cat, filename in OUTPUT_FILES.items():
        if cat == "drift":
            continue
        path = output_dir / filename
        if path.exists():
            previous[cat] = path.read_text(encoding="utf-8")
        else:
            previous[cat] = "(no previous)"

    drift_prompt = SYNTHESIS_PROMPTS["drift"].format(
        previous=json.dumps(previous, indent=2),
        current=json.dumps(new_synthesis, indent=2),
    )

    payload = {
        "model": NIM_MODEL,
        "messages": [{"role": "user", "content": drift_prompt}],
        "max_tokens": 4096,
        "temperature": 0.3,
    }

    response = await _call_nim(payload)
    if not response:
        return None

    try:
        return response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as e:
        log.warning("consolidate: malformed NIM response for drift: %s", e)
        return None


# ── Atomic write ─────────────────────────────────────────────────────────────

def _write_output(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)
    log.info("consolidate: wrote %s (%d bytes)", path, len(content))


# ── Main flow ────────────────────────────────────────────────────────────────

@dataclass
class ConsolidationResult:
    category: str
    entries_count: int
    output_path: Path | None
    error: str | None = None


async def consolidate(
    db_path: Path = DB_PATH,
    output_dir: Path = OUTPUT_DIR,
    categories: list[str] | None = None,
    dry_run: bool = False,
) -> list[ConsolidationResult]:
    if not NVIDIA_API_KEY and not dry_run:
        log.error("consolidate: NVIDIA_API_KEY not set")
        return []

    if categories is None:
        categories = [c for c in CATEGORIES if c != "drift"]

    conn = _init_db(db_path)
    groups = _get_unconsolidated_by_category(conn)

    results: list[ConsolidationResult] = []
    new_synthesis: dict[str, str] = {}

    report_categories = [c for c in categories if c != "drift"]

    for cat in report_categories:
        entries = groups.get(cat, [])
        if not entries:
            log.info("consolidate: no unconsolidated entries for %s, skipping", cat)
            results.append(ConsolidationResult(category=cat, entries_count=0, output_path=None))
            continue

        if dry_run:
            log.info("consolidate: [DRY RUN] would synthesize %d entries for %s", len(entries), cat)
            results.append(ConsolidationResult(category=cat, entries_count=len(entries), output_path=None))
            continue

        log.info("consolidate: synthesizing %d entries for %s", len(entries), cat)
        content = await _synthesize_category(cat, entries)
        if not content:
            log.error("consolidate: synthesis failed for %s", cat)
            results.append(ConsolidationResult(category=cat, entries_count=len(entries), output_path=None, error="synthesis_failed"))
            continue

        output_path = output_dir / OUTPUT_FILES[cat]
        _write_output(output_path, content)
        _mark_consolidated(conn, [e["id"] for e in entries])
        new_synthesis[cat] = content
        results.append(ConsolidationResult(category=cat, entries_count=len(entries), output_path=output_path))

    # Drift report — runs if any category was actually synthesized
    if not dry_run and new_synthesis:
        drift_content = await _generate_drift_report(output_dir, new_synthesis)
        if drift_content:
            drift_path = output_dir / OUTPUT_FILES["drift"]
            _write_output(drift_path, drift_content)
            results.append(ConsolidationResult(category="drift", entries_count=0, output_path=drift_path))
        else:
            log.warning("consolidate: drift report generation skipped or failed")
            results.append(ConsolidationResult(category="drift", entries_count=0, output_path=None, error="drift_failed"))

    conn.close()
    return results


# ── CLI entrypoint ───────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="NIM deep knowledge consolidation for Helios",
    )
    parser.add_argument("--db", default=None, help="Path to helios_knowledge.db (default: $AEGIS_KNOWLEDGE_DB or STATE_DIR/helios_knowledge.db)")
    parser.add_argument("--output-dir", default=None, help="Output directory for reports (default: $AEGIS_KNOWLEDGE_OUTPUT or STATE_DIR/consolidated)")
    parser.add_argument("--category", default=None, help="Comma-separated categories to process (default: all except drift; drift auto-runs after synthesis)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without calling NIM or writing files")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    db = Path(args.db) if args.db else DB_PATH
    out_dir = Path(args.output_dir) if args.output_dir else OUTPUT_DIR

    cats = None
    if args.category:
        cats = [c.strip() for c in args.category.split(",") if c.strip()]

    results = asyncio.run(consolidate(db_path=db, output_dir=out_dir, categories=cats, dry_run=args.dry_run))

    if args.dry_run:
        for r in results:
            status = "OK" if not r.error else f"FAIL ({r.error})"
            log.info("[DRY RUN] %s: %d entries → %s", r.category, r.entries_count, status)
        return

    for r in results:
        if r.error:
            log.error("consolidate: %s — %s (entries=%d)", r.category, r.error, r.entries_count)
        elif r.output_path:
            log.info("consolidate: %s — %d entries → %s", r.category, r.entries_count, r.output_path)
        else:
            log.info("consolidate: %s — no entries to process", r.category)


if __name__ == "__main__":
    main()
