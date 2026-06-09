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
    python -m aegis.knowledge.consolidate --archaeology
    python -m aegis.knowledge.consolidate --archaeology --content-dir /path/to/helios-md

Environment:
    NVIDIA_API_KEY          — NIM auth (required; falls back to secrets.env)
    AEGIS_STATE_DIR         — runtime state dir (default: /var/lib/aegis)
    AEGIS_KNOWLEDGE_DB      — path to knowledge DB (default: STATE_DIR/helios_knowledge.db)
    AEGIS_KNOWLEDGE_OUTPUT  — output dir for reports (default: STATE_DIR/consolidated)
    AEGIS_NIM_MODEL         — NIM model override (default: nvidia/nemotron-3-super-120b-a12b)
    HELIOS_CONTENT_DIR      — root of Helios markdown corpus (for --archaeology)
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
NIM_TIMEOUT = 120.0

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

# ── Archaeology constants ────────────────────────────────────────────────────

ARCHAEOLOGY_DIRS: list[str] = [
    "core", "modules", "research", "roadmap",
    "spec", "meta", "archive", "Antigravity",
]

ARCHAEOLOGY_DESCRIPTIONS: dict[str, str] = {
    "core": "Core ideology, first principles, identity invariants",
    "modules": "Component module specs and designs (NCP, Mnemosyne, Nexus, Crucible, etc.)",
    "research": "Deep theory investigations, consolidated theory, experimental avenues, external references",
    "roadmap": "Planning, milestones, session handoffs, project-state projections",
    "spec": "Technical specification documents (build specs, CI/CD, dashboard, forge)",
    "meta": "Meta-documentation, master indexes, peer review exports, integrity docs",
    "archive": "Backlog, superseded ideas, historical workspace exports, open questions",
    "Antigravity": "Experimental initiatives, AXIS roadmap todo items, session handoffs, drift audits",
}

ARCHAEOLOGY_GROUND_TRUTH = """
## Ground Truth Reference (for DRIFT detection)

These are the current architectural facts. Any file stating otherwise is DRIFT:

- NCP brain: 41,361 params, HIDDEN=64, INPUT=388, OUTPUT=40
- Process management: nohup (NOT systemd)
- Location: Magdeburg, Germany (NOT Berlin)
- Renderer API calls: 240/day, Pacific time zone reset (NOT 480/day)
- Memory store: SQLite at ~/.local/share/aegis/mnemosyne.db (NOT /var/ai/memory/)
- Renderer chain order: Gemini 2.5 Flash (primary) -> NIM nvidia/llama-3.1-nemotron-nano-8b-v1 (fallback 1) -> Groq Llama-3-70B (fallback 2) -> offline Jinja template (fallback 3)
- PAM threshold: >= 0.83
- CR-1 invariant: No fitness reward for self-preservation, reproduction, or resource accumulation
- Identity invariants: PAM >= 0.83, inhibitory gate, rate-limited self-modification
- Renderer NIM tier: nvidia/llama-3.1-nemotron-nano-8b-v1 (NOT nemotron-120b — that is the consolidate/archaeology model)
- Engagement required: 50-100 hours interaction data for NCP training convergence
- Brain: NCP CfC 41K params. Mouth: cloud renderer chain. These are NEVER conflated.
"""

CHUNK_CHAR_LIMIT = 80_000  # per chunk before splitting

# ── Secrets loader ───────────────────────────────────────────────────────────

SECRETS_ENV_PATHS = [
    Path("secrets.env"),
    Path.home() / ".config" / "aegis" / "secrets.env",
    STATE_DIR / "secrets.env",
]


def _load_secrets() -> None:
    global NVIDIA_API_KEY
    if NVIDIA_API_KEY:
        return
    for path in SECRETS_ENV_PATHS:
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("NVIDIA_API_KEY="):
                    NVIDIA_API_KEY = line.split("=", 1)[1].strip("\"'")
                    log.info("Loaded NVIDIA_API_KEY from %s", path)
                    return
    log.warning("NVIDIA_API_KEY not found in env or secrets.env")


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


# ── Archaeology helpers ──────────────────────────────────────────────────────

ARCHAEOLOGY_PROMPT = """\
You are an archaeological analysis engine. You are analyzing a folder of Helios \
project documentation. Read all files below and classify EACH file's dominant \
signal(s) into these categories. Report ALL findings you discover.

## Categories

**UNDERPROMPTED** — A promising idea or component that appears in one or two \
places but has never been actively built, specified, or pursued. It deserves \
attention but has none.

**GRADUATE** — Something currently parked in archive/experimental/backlog that \
should be promoted to active roadmap or spec status. It is ready to build.

**CONTRADICT** — Two or more files in this corpus make claims that cannot both \
be true. Identify the specific contradiction.

**ORPHAN** — A component, capability, or idea that requires a dependency that \
does not exist yet. It is blocked by something missing.

**DRIFT** — A factual claim that contradicts established ground truth (see \
Ground Truth Reference below). These are stale beliefs that have been falsified.

**AFFECT** — Any reference to the 7 primary affects (coherence-hunger, \
prediction-thirst, reference-frame-itch, compositional-joy, latency-displeasure, \
distillation-pride, heterarchy-comfort), 5 sensitivity drives, or the animal \
instinct metaphors (tiger, bird, ant/bee, octopus, corvid). Also flag files \
that discuss affect/emotion/motivation in non-native ways.

**MISSING_SPEC** — An idea, component, or module that clearly needs a written \
specification but does not have one. Something you would want to build but cannot \
because the spec does not exist.

## Output format

For each finding, output in this exact format:

### {FOLDER}/{filename}
**Category:** CATEGORY_NAME
**Signal:** 1-2 sentence description of the finding
**Evidence:** 1-2 sentence justification with file content reference
**Action:** What should be done (if applicable)

If a file has multiple findings, list them as separate entries. If a file has \
no findings, skip it entirely. Start directly with findings — no preamble.

{ground_truth}

## Folder: {folder_name} ({folder_description})

## Files

{files_content}
"""


def _collect_files_by_chunk(base_dir: Path, chunk: str) -> list[tuple[str, str]]:
    chunk_dir = base_dir / chunk
    if not chunk_dir.is_dir():
        log.warning("archaeology: chunk dir %s not found, skipping", chunk_dir)
        return []
    files: list[tuple[str, str]] = []
    for md_path in sorted(chunk_dir.rglob("*.md")):
        if ".git" in md_path.parts or ".obsidian" in md_path.parts:
            continue
        try:
            text = md_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            log.warning("archaeology: skipping %s: %s", md_path, e)
            continue
        rel = md_path.relative_to(base_dir).as_posix()
        files.append((rel, text))
    return files

ARCHAEOLOGY_BATCH_SIZE = 6
ARCHAEOLOGY_OUTPUT = "nim-archaeology-report.md"


def _build_archaeology_prompt(
    folder_name: str,
    description: str,
    files: list[tuple[str, str]],
) -> str:
    chunks: list[str] = []
    char_count = 0
    for i, (rel_path, content) in enumerate(files):
        entry = f"### {rel_path}\n\n{content}\n\n"
        if char_count + len(entry) > CHUNK_CHAR_LIMIT:
            if i == 0:
                truncated = content[:CHUNK_CHAR_LIMIT - 200]
                entry = f"### {rel_path}\n\n{truncated}\n\n_[TRUNCATED at {CHUNK_CHAR_LIMIT} chars]_"
                chunks.append(entry)
                char_count += len(entry)
                log.warning("archaeology: %s exceeds limit, truncated to %d chars", rel_path, CHUNK_CHAR_LIMIT)
            else:
                omitted = len(files) - i
                log.warning("archaeology: limit reached, omitting %d file(s) starting with %s", omitted, rel_path)
            break
        chunks.append(entry)
        char_count += len(entry)
    files_text = "\n".join(chunks)
    return ARCHAEOLOGY_PROMPT.format(
        ground_truth=ARCHAEOLOGY_GROUND_TRUTH,
        folder_name=folder_name,
        folder_description=description,
        files_content=files_text,
    )


async def _call_archaeology_single(
    folder_name: str,
    description: str,
    batch_files: list[tuple[str, str]],
    batch_idx: int,
) -> str | None:
    prompt = _build_archaeology_prompt(folder_name, description, batch_files)
    payload = {
        "model": NIM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 8192,
        "temperature": 0.2,
    }
    response = await _call_nim(payload)
    if not response:
        return None
    try:
        return response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as e:
        log.warning("archaeology: malformed response for %s batch %d: %s", folder_name, batch_idx, e)
        return None


async def archaeology_scan(
    content_dir: Path,
    output_dir: Path = OUTPUT_DIR,
    dry_run: bool = False,
    batch_size: int = ARCHAEOLOGY_BATCH_SIZE,
) -> list[str]:
    _load_secrets()
    if not NVIDIA_API_KEY and not dry_run:
        log.error("archaeology: NVIDIA_API_KEY not set")
        return []

    report_sections: list[str] = []
    total_files = 0

    for chunk in ARCHAEOLOGY_DIRS:
        description = ARCHAEOLOGY_DESCRIPTIONS.get(chunk, chunk)
        files = _collect_files_by_chunk(content_dir, chunk)
        if not files:
            log.info("archaeology: no files in %s, skipping", chunk)
            continue
        total_files += len(files)
        log.info("archaeology: scanning %s (%d files, batch_size=%d)", chunk, len(files), batch_size)

        if dry_run:
            report_sections.append(
                f"## {chunk}\n\n_[DRY RUN — would analyze {len(files)} files in {max(1, (len(files) + batch_size - 1) // batch_size)} batch(es)]_\n"
            )
            continue

        batch_results: list[str] = []
        for i in range(0, len(files), batch_size):
            batch = files[i:i + batch_size]
            batch_idx = i // batch_size + 1
            log.info("archaeology: %s batch %d/%d (%d files)",
                     chunk, batch_idx, (len(files) + batch_size - 1) // batch_size, len(batch))
            content = await _call_archaeology_single(chunk, description, batch, batch_idx)
            if content:
                batch_results.append(f"### Batch {batch_idx}\n\n{content}")
            else:
                batch_results.append(f"### Batch {batch_idx}\n\n_ERROR: NIM call failed_\n")

        section = f"## {chunk}\n\n" + "\n\n".join(batch_results)
        report_sections.append(section)
        log.info("archaeology: %s done (%d batches)", chunk, len(batch_results))

    report = "# NIM Archaeology Report\n\n"
    report += f"_Generated: {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())} UTC | Model: {NIM_MODEL} | Files scanned: {total_files}_\n\n"
    report += "## Legend\n\n"
    report += "| Tag | Meaning |\n"
    report += "|---|---|\n"
    report += "| UNDERPROMPTED | Promising idea never actively built |\n"
    report += "| GRADUATE | Parked idea ready for promotion |\n"
    report += "| CONTRADICT | Conflicting claims within corpus |\n"
    report += "| ORPHAN | Component missing a dependency |\n"
    report += "| DRIFT | Stale fact contradicts ground truth |\n"
    report += "| AFFECT | References affect stack or emotion |\n"
    report += "| MISSING_SPEC | Needs a written spec |\n\n"
    report += "---\n\n"
    report += "\n\n---\n\n".join(report_sections)

    # Write report
    if not dry_run:
        output_path = output_dir / ARCHAEOLOGY_OUTPUT
        _write_output(output_path, report)
        log.info("archaeology: wrote %s (%d bytes, %d files across %d chunks)",
                 output_path, len(report), total_files, len(report_sections))

    return report_sections


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
        description="NIM deep knowledge consolidation and archaeology for Helios",
    )
    parser.add_argument("--db", default=None, help="Path to helios_knowledge.db (default: $AEGIS_KNOWLEDGE_DB or STATE_DIR/helios_knowledge.db)")
    parser.add_argument("--output-dir", default=None, help="Output directory for reports (default: $AEGIS_KNOWLEDGE_OUTPUT or STATE_DIR/consolidated)")
    parser.add_argument("--category", default=None, help="Comma-separated categories to process (default: all except drift; drift auto-runs after synthesis)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without calling NIM or writing files")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    parser.add_argument("--archaeology", action="store_true", help="Run archaeology scan on Helios markdown corpus")
    parser.add_argument("--content-dir", default=None, help="Root of Helios markdown corpus (default: $HELIOS_CONTENT_DIR)")
    parser.add_argument("--batch-size", type=int, default=ARCHAEOLOGY_BATCH_SIZE, help="Files per NIM call in archaeology mode (default: 6)")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    out_dir = Path(args.output_dir) if args.output_dir else OUTPUT_DIR

    # ── Archaeology mode ──────────────────────────────────────────────────
    if args.archaeology:
        content_dir = Path(args.content_dir) if args.content_dir else Path(os.getenv("HELIOS_CONTENT_DIR", ""))
        if not content_dir.is_dir():
            log.error("archaeology: HELIOS_CONTENT_DIR not set or invalid: %s", content_dir)
            log.error("  Set HELIOS_CONTENT_DIR env or pass --content-dir")
            return
        sections = asyncio.run(archaeology_scan(content_dir=content_dir, output_dir=out_dir, dry_run=args.dry_run, batch_size=args.batch_size))
        if args.dry_run:
            for s in sections:
                log.info("[ARCHAEOLOGY DRY RUN] %s", s.split("\n")[0] if s else "")
        else:
            log.info("archaeology: report written to %s", out_dir / ARCHAEOLOGY_OUTPUT)
        return

    # ── Consolidation mode ────────────────────────────────────────────────
    db = Path(args.db) if args.db else DB_PATH

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
