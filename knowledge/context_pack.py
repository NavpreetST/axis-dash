#!/usr/bin/env python3
"""context_pack.py — Generate a context pack from the Helios knowledge database.

Searches the knowledge DB (facts, concepts, research_questions) for a given
task query, then synthesizes a structured context pack via NVIDIA NIM nano-8b.

Usage:
    python context_pack.py "task description"
    python context_pack.py "task description" --no-nim
    python context_pack.py "task description" --top 10
    python context_pack.py "task description" --db /path/to/db
    python context_pack.py "task description" --out -   # stdout

Output: knowledge/packs/<slug>.md
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
KNOWLEDGE_DIR = Path(__file__).resolve().parent
DB_PATH = KNOWLEDGE_DIR / "helios_knowledge.db"

# ---------------------------------------------------------------------------
# Embedding model (lazy-loaded)
# ---------------------------------------------------------------------------
_HAS_EMB = False
_MODEL = None


def _load_embed_model():
    global _HAS_EMB, _MODEL
    if _HAS_EMB:
        return
    try:
        import sys as _sys

        if "wandb" in _sys.modules and hasattr(_sys.modules["wandb"], "__spec__"):
            _sys.modules["wandb"].__spec__ = None
        from sentence_transformers import SentenceTransformer

        _MODEL = SentenceTransformer("all-MiniLM-L6-v2")
        _HAS_EMB = True
    except Exception:
        _HAS_EMB = False


def _embed(text: str):
    _load_embed_model()
    if _MODEL is None:
        return None
    return _MODEL.encode(text, normalize_embeddings=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower().strip())
    return s[:50].rstrip("-")


def _clean(text: str) -> str:
    if not text:
        return ""
    return (
        text.replace("\u2192", "->")
        .replace("\u2014", "--")
        .encode("ascii", errors="replace")
        .decode("ascii")
    )


# ---------------------------------------------------------------------------
# DB search (semantic + text fallback)
# ---------------------------------------------------------------------------
def _search_semantic(conn, query: str, table: str, limit: int = 5):
    cols_map = {
        "facts": ("name", "category", "content", "source_page", "status", "embedding"),
        "concepts": (
            "name", "type", "summary", "status", "dependencies",
            "source_pages", "embedding",
        ),
        "research_questions": (
            "question", "avenue", "priority", "status", "source_page", "embedding",
        ),
    }
    cols = cols_map[table]
    q_emb = _embed(query)
    if q_emb is None:
        return []

    import numpy as np

    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM {table} WHERE {cols[-1]} IS NOT NULL"
    ).fetchall()

    scored = []
    for r in rows:
        emb_bytes = r[-1]
        if emb_bytes:
            try:
                db_emb = np.frombuffer(emb_bytes, dtype=np.float32)
                s = float(np.dot(q_emb, db_emb))
                scored.append((s, r))
            except Exception:
                pass
    scored.sort(key=lambda x: x[0], reverse=True)
    return [(r, s) for s, r in scored[:limit]]


def _search_text(conn, query: str, table: str, limit: int = 5):
    cols_map = {
        "facts": ("name", "category", "content", "source_page", "status"),
        "concepts": ("name", "type", "summary", "status", "dependencies", "source_pages"),
        "research_questions": ("question", "avenue", "priority", "status", "source_page"),
    }
    cols = cols_map[table]
    results = []
    for term in query.split():
        if len(term) < 2:
            continue
        rows = conn.execute(
            f"SELECT {', '.join(cols)} FROM {table} "
            f"WHERE {cols[0]} LIKE ? OR {cols[2]} LIKE ? LIMIT ?",
            (f"%{term}%", f"%{term}%", limit),
        ).fetchall()
        for row in rows:
            if row not in results:
                results.append(row)
    return [(row, None) for row in results[:limit]]


def _search(conn, query: str, table: str, limit: int = 5):
    if _HAS_EMB:
        results = _search_semantic(conn, query, table, limit)
        if results:
            return results
    return _search_text(conn, query, table, limit)


# ---------------------------------------------------------------------------
# Raw formatting (fallback when NIM unavailable)
# ---------------------------------------------------------------------------
def _format_raw(query: str, facts, concepts, research) -> str:
    lines = [
        f"# Context Pack: {query[:80]}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Query: {query}",
        "",
        "---",
        "",
        "## Facts",
        "",
    ]

    for row, score in facts:
        name, cat, content, source, status = row[0], row[1], row[2], row[3], row[4]
        s_str = f"({score:.2f}) " if score else ""
        lines.append(f"- {s_str}**{_clean(name)}** [{_clean(status)}] [{_clean(cat)}]")
        lines.append(f"  {_clean(str(content)[:300])}")
        lines.append(f"  *src: {_clean(str(source))}*")
        lines.append("")

    lines.append("## Concepts")
    lines.append("")
    for row, score in concepts:
        name, typ, summary, status, deps, source = (
            row[0], row[1], row[2], row[3], row[4], row[5]
        )
        s_str = f"({score:.2f}) " if score else ""
        deps_str = f" (deps: {deps})" if deps else ""
        lines.append(f"- {s_str}**{_clean(name)}** [{_clean(status)}]{deps_str}")
        lines.append(f"  {_clean(str(summary)[:300])}")
        lines.append(f"  *src: {_clean(str(source))}*")
        lines.append("")

    lines.append("## Research Questions")
    lines.append("")
    for row, score in research:
        question = row[0]
        avenue = row[1] if len(row) > 1 else ""
        priority = row[2] if len(row) > 2 else ""
        status = row[3] if len(row) > 3 else ""
        source = row[4] if len(row) > 4 else ""
        s_str = f"({score:.2f}) " if score else ""
        lines.append(
            f"- {s_str}[{priority}] [{avenue}] {_clean(str(question)[:300])}"
        )
        lines.append(f"  *src: {_clean(str(source))}*")
        lines.append("")

    # Suggested reading
    lines.append("## Suggested Pages to Read")
    lines.append("")
    seen = set()
    for results in [facts, concepts, research]:
        for row, _ in results:
            src = row[3] if len(row) > 3 else row[4] if len(row) > 4 else ""
            if src and src not in seen:
                seen.add(src)
                lines.append(f"- `{_clean(str(src))}`")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# NIM nano-8b synthesis
# ---------------------------------------------------------------------------
_NIM_MODEL = "nvidia/llama-3.1-nemotron-nano-8b-v1"
_NIM_ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"
_NIM_TIMEOUT = 15  # seconds


def _build_nim_context(query: str, facts, concepts, research) -> str:
    """Build a structured text blob from DB results for the NIM prompt."""
    parts = [f"TASK: {query}", ""]

    parts.append("FACTS (ranked by relevance):")
    for i, (row, score) in enumerate(facts, 1):
        name, cat, content, source, status = row[0], row[1], row[2], row[3], row[4]
        s_str = f" score={score:.2f}" if score else ""
        parts.append(
            f"  {i}. [{status}] [{cat}] {name}{s_str}: "
            f"{str(content)[:200]}"
        )
    parts.append("")

    parts.append("CONCEPTS:")
    for i, (row, score) in enumerate(concepts, 1):
        name, typ, summary, status, deps, source = (
            row[0], row[1], row[2], row[3], row[4], row[5]
        )
        s_str = f" score={score:.2f}" if score else ""
        deps_str = f" deps={deps}" if deps else ""
        parts.append(
            f"  {i}. [{status}] [{typ}] {name}{s_str}{deps_str}: "
            f"{str(summary)[:200]}"
        )
    parts.append("")

    parts.append("RESEARCH QUESTIONS:")
    for i, (row, score) in enumerate(research, 1):
        question = row[0]
        avenue = row[1] if len(row) > 1 else ""
        priority = row[2] if len(row) > 2 else ""
        status = row[3] if len(row) > 3 else ""
        parts.append(
            f"  {i}. [{priority}] [{status}] [{avenue}] {str(question)[:200]}"
        )
    parts.append("")

    return "\n".join(parts)


_SYNTHESIS_PROMPT = """\
You are a Helios context-pack synthesizer. Given a task and raw DB results,
produce a structured context pack in markdown.

{context}

OUTPUT FORMAT (use exactly these sections):

## Task Summary
One paragraph: what the task is about and why these results matter.

## Priority-Ranked Facts
Top facts ranked by relevance to the task. Format:
- **fact name** [status] — key detail (source: page)

## Concept Dependencies
Concepts and their dependency chains. Format:
- **concept** [type] — summary → depends on: dep1, dep2

## Reading Order
Ordered list of pages/files to read, most important first. Include why each matters.

## Checklist
Actionable checklist items derived from the facts and concepts.
Format: [ ] action item

Keep the output under 800 words. Be concrete and actionable."""


def _call_nim(prompt: str, api_key: str) -> str | None:
    """Call NIM nano-8b synchronously. Returns response text or None on failure."""
    payload = json.dumps({
        "model": _NIM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1200,
        "temperature": 0.3,
    }).encode("utf-8")

    req = urllib.request.Request(
        _NIM_ENDPOINT,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=_NIM_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, ValueError, TimeoutError):
        return None


def _format_nim(
    query: str, nim_output: str, facts, concepts, research
) -> str:
    """Combine NIM synthesis with raw metadata footer."""
    header = [
        f"# Context Pack: {query[:80]}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Query: {query}",
        f"Model: {_NIM_MODEL}",
        "",
        "---",
        "",
    ]

    # NIM-synthesized content
    body = nim_output.strip()
    if not body.startswith("##"):
        body = "## Synthesized Context\n\n" + body

    # Raw metadata footer (for reference)
    footer = [
        "",
        "---",
        "",
        "## Raw Metadata",
        "",
        f"### Facts ({len(facts)} rows)",
    ]
    for row, score in facts:
        name = row[0]
        s_str = f" ({score:.2f})" if score else ""
        footer.append(f"- {_clean(name)}{s_str}")
    footer.append("")

    footer.append(f"### Concepts ({len(concepts)} rows)")
    for row, score in concepts:
        name = row[0]
        s_str = f" ({score:.2f})" if score else ""
        footer.append(f"- {_clean(name)}{s_str}")
    footer.append("")

    footer.append(f"### Research Questions ({len(research)} rows)")
    for row, score in research:
        question = row[0]
        s_str = f" ({score:.2f})" if score else ""
        footer.append(f"- {_clean(str(question)[:80])}{s_str}")
    footer.append("")

    # Suggested reading
    footer.append("### Suggested Pages")
    seen = set()
    for results in [facts, concepts, research]:
        for row, _ in results:
            src = row[3] if len(row) > 3 else row[4] if len(row) > 4 else ""
            if src and src not in seen:
                seen.add(src)
                footer.append(f"- `{_clean(str(src))}`")
    footer.append("")

    return "\n".join(header) + body + "\n".join(footer)


# ---------------------------------------------------------------------------
# Main generate function
# ---------------------------------------------------------------------------
def generate(
    query: str,
    *,
    top_n: int = 5,
    use_nim: bool = True,
    db_path: str | Path | None = None,
) -> tuple[Path, str]:
    """Generate a context pack for the given query.

    Returns (pack_path, output_text).
    If NIM is unavailable, falls back to raw formatting.
    """
    db = Path(db_path) if db_path else DB_PATH
    conn = sqlite3.connect(str(db))
    s = _slug(query)
    pack_dir = KNOWLEDGE_DIR / "packs"
    pack_dir.mkdir(exist_ok=True)

    # DB search — top-15 across all tables (5 per table)
    facts = _search(conn, query, "facts", top_n)
    concepts = _search(conn, query, "concepts", top_n)
    research = _search(conn, query, "research_questions", top_n)
    conn.close()

    # Try NIM synthesis
    output = None
    if use_nim:
        api_key = os.getenv("NVIDIA_API_KEY")
        if api_key:
            context = _build_nim_context(query, facts, concepts, research)
            prompt = _SYNTHESIS_PROMPT.format(context=context)
            nim_result = _call_nim(prompt, api_key)
            if nim_result:
                output = _format_nim(query, nim_result, facts, concepts, research)

    # Fallback to raw formatting
    if output is None:
        output = _format_raw(query, facts, concepts, research)

    pack_path = pack_dir / f"{s}.md"
    pack_path.write_text(output, encoding="utf-8")
    return pack_path, output


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate a context pack from the Helios knowledge database"
    )
    parser.add_argument("query", help="Task description to search for")
    parser.add_argument(
        "--top", type=int, default=5, help="Results per table (default 5)"
    )
    parser.add_argument(
        "--no-nim", action="store_true", help="Skip NIM synthesis, use raw formatting"
    )
    parser.add_argument(
        "--db", type=str, default=None, help="Database path (default: helios_knowledge.db)"
    )
    parser.add_argument(
        "--out", type=str, default=None, help="Output path (default: packs/<slug>.md, '-' for stdout)"
    )
    args = parser.parse_args()

    query = " ".join(args.query) if isinstance(args.query, list) else args.query
    pack_path, output = generate(
        query,
        top_n=args.top,
        use_nim=not args.no_nim,
        db_path=args.db,
    )

    if args.out == "-":
        print(output)
    else:
        print(f"Pack: {pack_path}")
        print(f"Lines: {output.count(chr(10)) + 1}")
        print()
        print(output[:2000])
