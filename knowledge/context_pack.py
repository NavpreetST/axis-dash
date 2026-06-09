#!/usr/bin/env python3
"""
context_pack.py — Generate a context pack from the Helios knowledge database.
Usage: python context_pack.py "task description"
Output: Helix/packs/<slug>.md
"""
import logging
import sqlite3, sys, os, re
from pathlib import Path
from datetime import datetime

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
log = logging.getLogger("context_pack")

HELIX = Path(__file__).resolve().parent
DB_PATH = HELIX / "helios_knowledge.db"
NVIDIA_API_KEY: str | None = os.getenv("NVIDIA_API_KEY") or None
NIM_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

HAS_EMB = False
model = None
try:
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("all-MiniLM-L6-v2")
    HAS_EMB = True
except Exception:
    pass


def slug(text):
    return re.sub(r'[^a-z0-9]+', '-', text.lower().strip())[:50]


def embed(text):
    if not HAS_EMB or not model:
        return None
    return model.encode(text, normalize_embeddings=True)


def search_semantic(conn, query, table, limit=5):
    cols_map = {
        "facts": ("name", "category", "content", "source_page", "status", "embedding"),
        "concepts": ("name", "type", "summary", "status", "dependencies", "source_pages", "embedding"),
        "research_questions": ("question", "avenue", "priority", "status", "source_page", "embedding"),
    }
    cols = cols_map[table]
    q_emb = embed(query)
    if q_emb is None:
        return []

    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM {table} WHERE {cols[-1]} IS NOT NULL"
    ).fetchall()

    import numpy as np
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


def search_text(conn, query, table, limit=5):
    cols_map = {
        "facts": ("name", "category", "content", "source_page", "status"),
        "concepts": ("name", "type", "summary", "status", "dependencies", "source_pages"),
        "research_questions": ("question", "avenue", "priority", "status", "source_page"),
    }
    cols = cols_map[table]
    results = []
    for term in query.split():
        r = conn.execute(
            f"SELECT {', '.join(cols)} FROM {table} "
            f"WHERE {cols[0]} LIKE ? OR {cols[2]} LIKE ? LIMIT ?",
            (f"%{term}%", f"%{term}%", limit)
        ).fetchall()
        for row in r:
            if row not in results:
                results.append(row)
    return [(row, None) for row in results[:limit]]


def search(conn, query, table, limit=5):
    if HAS_EMB:
        results = search_semantic(conn, query, table, limit)
        if results:
            return results
    return search_text(conn, query, table, limit)


def clean(text):
    if not text:
        return ""
    return text.replace('\u2192', '->').replace('\u2014', '--').encode('ascii', errors='replace').decode('ascii')


def _nim_synthesis(query: str, facts: list, concepts: list, research: list) -> str | None:
    """Feed DB results to NIM nano-8b for narrative synthesis.

    Returns markdown string, or None on failure (caller falls back to raw format).
    """
    if not NVIDIA_API_KEY or not HAS_HTTPX:
        return None

    raw = []
    raw.append("## Raw Facts")
    for (row, score) in facts:
        s_str = f"(sim={score:.2f}) " if score else ""
        raw.append(f"- {s_str}{row[0]}: {str(row[2])[:300]}")
    raw.append("")
    raw.append("## Raw Concepts")
    for (row, score) in concepts:
        s_str = f"(sim={score:.2f}) " if score else ""
        deps = row[4] if row[4] else "(none)"
        raw.append(f"- {s_str}{row[0]} (deps: {deps}): {str(row[2])[:300]}")
    raw.append("")
    raw.append("## Raw Research Questions")
    for (row, score) in research:
        s_str = f"(sim={score:.2f}) " if score else ""
        raw.append(f"- {s_str}{row[0]}")
    raw.append("")

    system_prompt = (
        "You are a Helios knowledge synthesiser. Given raw knowledge-base results "
        "for a user's task query, produce a structured context pack in markdown. "
        "Include exactly these sections:\n\n"
        "1. **Task Summary** — short 1-2 paragraph overview connecting the query to "
        "the relevant knowledge.\n"
        "2. **Priority-Ranked Facts** — list facts in order of relevance, with brief "
        "justification for each.\n"
        "3. **Concept Dependencies** — which concepts depend on which, with "
        "prerequisite ordering noted.\n"
        "4. **Reading Order** — recommended sequence of source pages to read.\n"
        "5. **Checklist** — actionable steps or questions to resolve based on this "
        "knowledge.\n\n"
        "Be concise. Use bullet points. Do NOT repeat the raw rows verbatim — "
        "synthesise."
    )
    payload = {
        "model": "nvidia/llama-3.1-nemotron-nano-8b-v1",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Query: {query}\n\nRaw knowledge:\n{''.join(raw)}"},
        ],
        "max_tokens": 1024,
        "temperature": 0.7,
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.post(
                NIM_URL,
                headers={
                    "Authorization": f"Bearer {NVIDIA_API_KEY}",
                    "content-type": "application/json",
                },
                json=payload,
            )
        if r.status_code != 200:
            log.warning("NIM synthesis returned %d: %.200r", r.status_code, r.text)
            return None
        data = r.json()
        return data["choices"][0]["message"]["content"]
    except Exception as exc:
        log.warning("NIM synthesis failed: %s", exc)
        return None


def _raw_format(query: str, facts: list, concepts: list, research: list) -> str:
    """Markdown from raw DB results (fallback when NIM is unavailable)."""
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

    for (row, score) in facts:
        name, cat, content, source, status = row[0], row[1], row[2], row[3], row[4]
        s_str = f"({score:.2f}) " if score else ""
        lines.append(f"- {s_str}**{clean(name)}** [{clean(status)}] [{clean(cat)}]")
        lines.append(f"  {clean(str(content)[:300])}")
        lines.append(f"  *src: {clean(str(source))}*")
        lines.append("")

    lines.append("## Concepts")
    lines.append("")
    for (row, score) in concepts:
        name, typ, summary, status, deps, source = row[0], row[1], row[2], row[3], row[4], row[5]
        s_str = f"({score:.2f}) " if score else ""
        deps_str = f" (deps: {deps})" if deps else ""
        lines.append(f"- {s_str}**{clean(name)}** [{clean(status)}]{deps_str}")
        lines.append(f"  {clean(str(summary)[:300])}")
        lines.append(f"  *src: {clean(str(source))}*")
        lines.append("")

    lines.append("## Research Questions")
    lines.append("")
    for (row, score) in research:
        question = row[0]
        avenue = row[1] if len(row) > 1 else ""
        priority = row[2] if len(row) > 2 else ""
        status = row[3] if len(row) > 3 else ""
        source = row[4] if len(row) > 4 else ""
        s_str = f"({score:.2f}) " if score else ""
        lines.append(f"- {s_str}[{priority}] [{avenue}] {clean(str(question)[:300])}")
        lines.append(f"  *src: {clean(str(source))}*")
        lines.append("")

    lines.append("## Suggested Pages to Read")
    lines.append("")
    seen = set()
    for results in [facts, concepts, research]:
        for (row, _) in results:
            src = row[3] if len(row) > 3 else row[4] if len(row) > 4 else ""
            if src and src not in seen:
                seen.add(src)
                lines.append(f"- `{clean(str(src))}`")
    lines.append("")

    return "\n".join(lines)


def generate(query):
    conn = sqlite3.connect(str(DB_PATH))
    s = slug(query)
    pack_dir = HELIX / "packs"
    pack_dir.mkdir(exist_ok=True)

    facts = search(conn, query, "facts", 5)
    concepts = search(conn, query, "concepts", 5)
    research = search(conn, query, "research_questions", 5)
    conn.close()

    synthesis = _nim_synthesis(query, facts, concepts, research)
    output = synthesis if synthesis else _raw_format(query, facts, concepts, research)

    pack_path = pack_dir / f"{s}.md"
    pack_path.write_text(output, encoding="utf-8")
    return pack_path, output


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python context_pack.py 'task description'")
        sys.exit(1)

    query = " ".join(sys.argv[1:])
    pack_path, output = generate(query)
    line_count = output.count('\n') + 1
    print(f"Pack: {pack_path}")
    print(f"Lines: {line_count}")
    print()
    print(output[:1500])
