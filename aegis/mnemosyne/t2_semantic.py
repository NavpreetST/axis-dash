"""Mnemosyne T2 — semantic fact store (subject/predicate/object triples).

Schema:
  subj, pred, obj       — the triple
  confidence            — 0.0–1.0 scalar
  decay_t               — Unix timestamp; NULL = no decay
  source                — origin (e.g. "user_turn:42", "seed", "inference")
  embedding             — MiniLM embedding of "subj pred obj"
  ts                    — creation timestamp

Retrieval: by subject (exact), by triple pattern (LIKE), by embedding.
"""
from __future__ import annotations

import array
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .db import CONN

log = logging.getLogger("mnemosyne.t2")

SCHEMA = """
CREATE TABLE IF NOT EXISTS semantic_facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    subj        TEXT    NOT NULL,
    pred        TEXT    NOT NULL,
    obj         TEXT    NOT NULL,
    confidence  REAL    NOT NULL DEFAULT 1.0,
    decay_t     REAL,
    source      TEXT,
    embedding   BLOB,
    ts          REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_semantic_subj ON semantic_facts(subj);
CREATE INDEX IF NOT EXISTS idx_semantic_pred ON semantic_facts(pred);
CREATE INDEX IF NOT EXISTS idx_semantic_decay ON semantic_facts(decay_t);
"""
CONN.executescript(SCHEMA)


@dataclass
class Fact:
    subj: str
    pred: str
    obj: str
    confidence: float = 1.0
    decay_t: Optional[float] = None
    source: Optional[str] = None
    embedding: Optional[list[float]] = None
    ts: float = field(default_factory=time.time)


def _triple_text(f: Fact) -> str:
    return f"{f.subj} {f.pred} {f.obj}"


def _get_embedding(text: str) -> list[float]:
    try:
        from aegis.hive.text_encoder import get_model
        model = get_model()
        return model.encode(text, normalize_embeddings=True).tolist()
    except Exception:
        return [0.0] * 384


def _emb_blob(emb: list[float]) -> bytes:
    return array.array("f", emb).tobytes()


def insert(fact: Fact) -> int:
    if fact.embedding is None:
        fact.embedding = _get_embedding(_triple_text(fact))
    cur = CONN.execute(
        "INSERT INTO semantic_facts (subj, pred, obj, confidence, decay_t, source, embedding, ts) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (fact.subj.lower(), fact.pred.lower(), fact.obj,
         max(0.0, min(1.0, fact.confidence)),
         fact.decay_t, fact.source,
         _emb_blob(fact.embedding), fact.ts),
    )
    CONN.commit()
    log.debug("t2: inserted fact (%s, %s, %s) id=%d", fact.subj, fact.pred, fact.obj, cur.lastrowid)
    return cur.lastrowid


def insert_batch(facts: list[Fact]) -> list[int]:
    ids = []
    for f in facts:
        ids.append(insert(f))
    return ids


def delete_expired() -> int:
    now = time.time()
    cur = CONN.execute(
        "DELETE FROM semantic_facts WHERE decay_t IS NOT NULL AND decay_t < ?",
        (now,),
    )
    CONN.commit()
    if cur.rowcount:
        log.info("t2: deleted %d expired facts", cur.rowcount)
    return cur.rowcount


def query_by_subject(subj: str, min_confidence: float = 0.3) -> list[dict]:
    delete_expired()
    cur = CONN.execute(
        "SELECT id, subj, pred, obj, confidence, decay_t, source, ts "
        "FROM semantic_facts WHERE subj = ? AND confidence >= ? "
        "ORDER BY confidence DESC, ts DESC",
        (subj.lower(), min_confidence),
    )
    return [
        {"id": row[0], "subj": row[1], "pred": row[2], "obj": row[3],
         "confidence": row[4], "decay_t": row[5], "source": row[6], "ts": row[7]}
        for row in cur.fetchall()
    ]


def query_by_triple(subj: str, pred: str, obj: str, min_confidence: float = 0.3) -> list[dict]:
    delete_expired()
    cur = CONN.execute(
        "SELECT id, subj, pred, obj, confidence, decay_t, source, ts "
        "FROM semantic_facts "
        "WHERE subj LIKE ? AND pred LIKE ? AND obj LIKE ? AND confidence >= ? "
        "ORDER BY confidence DESC, ts DESC",
        (f"%{subj.lower()}%", f"%{pred.lower()}%", f"%{obj}%", min_confidence),
    )
    return [
        {"id": row[0], "subj": row[1], "pred": row[2], "obj": row[3],
         "confidence": row[4], "decay_t": row[5], "source": row[6], "ts": row[7]}
        for row in cur.fetchall()
    ]


def query_by_embedding(query_emb: list[float], k: int = 5, min_confidence: float = 0.3) -> list[dict]:
    delete_expired()
    q = np.asarray(query_emb, dtype=np.float32)
    cur = CONN.execute(
        "SELECT id, subj, pred, obj, confidence, decay_t, source, embedding, ts "
        "FROM semantic_facts WHERE embedding IS NOT NULL AND confidence >= ? "
        "ORDER BY ts DESC LIMIT 500",
        (min_confidence,),
    )
    scored = []
    for row in cur.fetchall():
        blob = row[7]
        if not blob:
            continue
        emb = np.frombuffer(blob, dtype=np.float32)
        if emb.shape != q.shape:
            continue
        sim = float(np.dot(q, emb))
        scored.append((sim, row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[8]))
    scored.sort(reverse=True)
    return [
        {"id": r[1], "subj": r[2], "pred": r[3], "obj": r[4],
         "confidence": r[5], "decay_t": r[6], "source": r[7], "ts": r[8],
         "score": r[0]}
        for r in scored[:k]
    ]


# ── Fact extraction helpers ──────────────────────────────────────────────

_PATTERNS = [
    (r"(?:my|the|this)\s+(\w+)\s+is\s+(\w+(?:\s+\w+){0,4})", "be"),
    (r"(?:i\s+(?:have|own|use|got)\s+(?:a|an|the)?\s*)(\w[\w\s]*)", "own"),
    (r"(?:i'?m?\s+(?:using|running|on)\s+(?:a|an|the)?\s*)(\w[\w\s/]*)", "runs"),
]


def extract_facts(text: str, source: str | None = None, confidence: float = 0.7) -> list[Fact]:
    text_lower = text.lower()
    facts: list[Fact] = []
    for pattern, pred in _PATTERNS:
        for m in re.finditer(pattern, text_lower):
            subj = m.group(1).strip()
            obj = m.group(2).strip() if pred != "own" and pred != "runs" else m.group(1).strip()
            if not subj or not obj:
                continue
            facts.append(Fact(
                subj=subj,
                pred=pred,
                obj=obj,
                confidence=confidence,
                source=source or f"extracted:{text[:40]}",
            ))
    return facts
