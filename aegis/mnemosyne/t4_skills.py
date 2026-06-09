"""Mnemosyne T4 — procedural skill store.

Schema:
  skill_name       TEXT PK       — canonical name
  trigger_pattern  TEXT          — regex or keyword to match
  action_type      TEXT          — e.g. "python", "bash", "template", "nim"
  params_json      TEXT          — JSON schema for expected parameters
  success_count    INTEGER       — how many successful executions
  failure_count    INTEGER       — how many failed executions
  last_used        REAL          — Unix timestamp of last execution
  ts               REAL          — creation timestamp

Operations:
  learn(skill)                               — INSERT OR REPLACE
  match(trigger)                             — find skills matching trigger
  record_outcome(skill_name, success)         — update counters
  list_by_frequency(min_count=1)             — skills with enough usage
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from .db import CONN

log = logging.getLogger("mnemosyne.t4")

SCHEMA = """
CREATE TABLE IF NOT EXISTS skills (
    skill_name      TEXT    PRIMARY KEY,
    trigger_pattern TEXT    NOT NULL,
    action_type     TEXT    NOT NULL,
    params_json     TEXT,
    success_count   INTEGER NOT NULL DEFAULT 0,
    failure_count   INTEGER NOT NULL DEFAULT 0,
    last_used       REAL,
    ts              REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skills_action ON skills(action_type);
CREATE INDEX IF NOT EXISTS idx_skills_used ON skills(last_used);
"""
CONN.executescript(SCHEMA)


@dataclass
class Skill:
    skill_name: str
    trigger_pattern: str
    action_type: str = "template"
    params_json: Optional[str] = None
    success_count: int = 0
    failure_count: int = 0
    last_used: Optional[float] = None
    ts: float = field(default_factory=time.time)


def learn(skill: Skill) -> None:
    CONN.execute(
        "INSERT OR REPLACE INTO skills "
        "(skill_name, trigger_pattern, action_type, params_json, "
        " success_count, failure_count, last_used, ts) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (skill.skill_name, skill.trigger_pattern, skill.action_type,
         skill.params_json,
         skill.success_count, skill.failure_count,
         skill.last_used, skill.ts),
    )
    CONN.commit()
    log.info("t4: learned skill '%s' (trigger=%s, type=%s)",
             skill.skill_name, skill.trigger_pattern, skill.action_type)


def match(trigger: str, min_success: int = 0) -> list[dict]:
    """Find skills whose trigger_pattern matches the given text."""
    cur = CONN.execute(
        "SELECT skill_name, trigger_pattern, action_type, params_json, "
        "       success_count, failure_count, last_used, ts "
        "FROM skills WHERE success_count >= ? ORDER BY success_count DESC, last_used DESC",
        (min_success,),
    )
    results = []
    for row in cur.fetchall():
        try:
            if re.search(row[1], trigger, re.IGNORECASE):
                results.append({
                    "skill_name": row[0],
                    "trigger_pattern": row[1],
                    "action_type": row[2],
                    "params_json": row[3],
                    "success_count": row[4],
                    "failure_count": row[5],
                    "last_used": row[6],
                    "ts": row[7],
                })
        except re.error as e:
            log.warning("t4: invalid regex in skill '%s': %s", row[0], e)
            continue
    return results


def record_outcome(skill_name: str, success: bool) -> None:
    if success:
        CONN.execute(
            "UPDATE skills SET success_count = success_count + 1, last_used = ? "
            "WHERE skill_name = ?",
            (time.time(), skill_name),
        )
    else:
        CONN.execute(
            "UPDATE skills SET failure_count = failure_count + 1, last_used = ? "
            "WHERE skill_name = ?",
            (time.time(), skill_name),
        )
    CONN.commit()
    log.debug("t4: recorded %s for skill '%s'", "success" if success else "failure", skill_name)


def list_by_frequency(min_count: int = 1) -> list[dict]:
    cur = CONN.execute(
        "SELECT skill_name, action_type, success_count, failure_count, "
        "       last_used, trigger_pattern "
        "FROM skills WHERE success_count >= ? "
        "ORDER BY success_count DESC, last_used DESC",
        (min_count,),
    )
    return [
        {"skill_name": row[0], "action_type": row[1],
         "success_count": row[2], "failure_count": row[3],
         "last_used": row[4], "trigger_pattern": row[5]}
        for row in cur.fetchall()
    ]


def delete_unused(threshold_s: float = 2592000) -> int:
    """Delete skills unused for threshold_s seconds (default 30 days)."""
    cutoff = time.time() - threshold_s
    cur = CONN.execute(
        "DELETE FROM skills WHERE success_count = 0 AND failure_count = 0 "
        "AND (last_used IS NOT NULL AND last_used < ? "
        "      OR last_used IS NULL AND ts < ?)",
        (cutoff, cutoff),
    )
    CONN.commit()
    if cur.rowcount:
        log.info("t4: deleted %d unused skills", cur.rowcount)
    return cur.rowcount
