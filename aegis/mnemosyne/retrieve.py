import logging
import time
import sqlite3
from pathlib import Path
import numpy as np
from aegis.nexus.bus import BUS
from .db import CONN

log = logging.getLogger("mnemosyne.retrieve")
TOP_K = 8
SCAN_LIMIT = 500
SELF_HIT_GUARD_S = 2

KB_PATH = Path("/opt/aegis/knowledge/helios_knowledge.db")


def _blob_to_emb(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def _seed_rows() -> list[dict]:
    cur = CONN.execute(
        "SELECT id, text, ts FROM episodes WHERE action='seed' ORDER BY id"
    )
    return [
        {"id": str(_id), "text": text, "ts": ts, "score": 1.0}
        for _id, text, ts in cur.fetchall()
    ]


def _clean_fts5_query(text: str) -> str:
    """Strip punctuation and stop-words for FTS5 MATCH."""
    import re
    stop_words = {
        'a','an','the','is','are','was','were','be','been','being',
        'have','has','had','do','does','did','will','would','shall',
        'should','may','might','must','can','could','i','me','my',
        'we','our','you','your','he','she','it','they','them',
        'what','which','who','whom','this','that','these','those',
        'am','in','on','at','to','for','of','from','by','with',
        'about','as','into','through','during','before','after',
        'above','below','between','under','and','but','or','not',
        'no','nor','so','if','then','than','too','very','just',
        'how','where','when','why','tell','more','about','explain',
    }
    cleaned = re.sub(r'[^\w\s]', '', text.lower())
    words = [w for w in cleaned.split() if w not in stop_words and len(w) > 1]
    return ' AND '.join(words[:8])


def _search_knowledge(query_text: str) -> list[dict]:
    """FTS5 search on facts, concepts, research_questions."""
    if not KB_PATH.exists():
        log.warning("knowledge DB not found at %s", KB_PATH)
        return []

    kb = sqlite3.connect(str(KB_PATH))
    results = []
    fts_query = _clean_fts5_query(query_text)
    if not fts_query:
        kb.close()
        return []

    tables = {
        "facts": ("name", "content", "source_page", "status", 5),
        "concepts": ("name", "summary", "source_pages", "status", 3),
        "research_questions": ("question", "question", "source_page", "status", 2),
    }

    for table, (name_col, content_col, source_col, status_col, limit) in tables.items():
        try:
            rows = kb.execute(
                f"SELECT {name_col}, {content_col}, {source_col}, {status_col} "
                f"FROM {table} WHERE {content_col} LIKE ? LIMIT ?",
                (f"%{fts_query.split()[0] if fts_query.split() else query_text[:20]}%", limit)
            ).fetchall()
        except:
            continue

        for r in rows:
            name = str(r[0] or '')
            content = str(r[1] or '')
            src = str(r[2] or '')
            status = str(r[3] or '')
            text = f"[{status.upper()}] {name}: {content[:300]}"
            if src:
                text += f" (src: {src})"
            results.append({
                "id": f"kb-{table}-{hash(text) & 0x7FFFFFFF}",
                "text": text,
                "ts": time.time(),
                "score": 1.0,
            })

    kb.close()
    log.debug("knowledge search: %d hits from query '%s'", len(results), query_text[:40])
    return results


def retrieve(query_emb: list[float], query_text: str = "", k: int = TOP_K) -> list[dict]:
    q = np.asarray(query_emb, dtype=np.float32)
    cutoff = time.time() - SELF_HIT_GUARD_S
    cur = CONN.execute(
        "SELECT id, text, embedding, ts FROM episodes "
        "WHERE ts < ? AND (action IS NULL OR action != 'seed') "
        "ORDER BY id DESC LIMIT ?",
        (cutoff, SCAN_LIMIT),
    )
    scored = []
    for _id, text, blob, ts in cur.fetchall():
        emb = _blob_to_emb(blob)
        if emb.shape != q.shape:
            continue
        sim = float(np.dot(q, emb))
        scored.append((sim, _id, text, ts))
    scored.sort(reverse=True)
    cosine_hits = [
        {"id": str(_id), "text": text, "ts": ts, "score": sim}
        for sim, _id, text, ts in scored[:k]
    ]
    seed = _seed_rows()
    knowledge = _search_knowledge(query_text) if query_text else []

    seen = {h["id"] for h in seed}
    out = list(seed)
    for h in knowledge:
        if h["id"] not in seen:
            out.append(h)
            seen.add(h["id"])
    for h in cosine_hits:
        if h["id"] not in seen:
            out.append(h)
            seen.add(h["id"])
    return out


async def run() -> None:
    log.info("mnemosyne retriever running (with knowledge DB FTS5)")
    q = BUS.subscribe("sensor.text")
    while True:
        msg = await q.get()
        query_text = msg.payload.get("text", "")
        hits = retrieve(msg.payload["embedding"], query_text=query_text)
        await BUS.publish("memory.retrieved", {
            "ids":    [h["id"]    for h in hits],
            "texts":  [h["text"]  for h in hits],
            "scores": [h["score"] for h in hits],
        })
        n_kb = sum(1 for h in hits if h["id"].startswith("kb-"))
        n_seed = sum(1 for h in hits if h.get("score", 0) == 1.0)
        log.debug("retrieved %d hits (%d kb + %d seed + %d cosine)",
                  len(hits), n_kb, n_seed, len(hits) - n_kb - n_seed)
