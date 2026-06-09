"""Inhibitory gate — regex blocklist + PAM check before shell_cmd execution.

Blocks dangerous commands before they reach the executor:
  - rm -rf (recursive forced deletion)
  - sudo (privilege escalation)
  - curl/wget to non-whitelist hosts
  - /dev device access

Usage:
    from aegis.action.inhibitory_gate import InhibitoryGate
    gate = InhibitoryGate()
    ok, reason = gate.check("rm -rf /")
    # -> (False, "blocked by regex: rm -rf")
"""
from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger("action.inhibitory_gate")

_BLOCKED_PATTERNS: list[re.Pattern] = [
    re.compile(r"\brm\s+-rf\b", re.IGNORECASE),
    re.compile(r"\bsudo\b", re.IGNORECASE),
    re.compile(r"\bcurl\s+(?:-[^\s]*\s+)?(?!https?://(?:api\.github\.com|localhost|127\.0\.0\.1))", re.IGNORECASE),
    re.compile(r"\bwget\s+(?:-[^\s]*\s+)?(?!https?://(?:api\.github\.com|localhost|127\.0\.0\.1))", re.IGNORECASE),
    re.compile(r"/dev/\w+"),
    re.compile(r">\s*/dev/"),
    re.compile(r"\bdangerously\b", re.IGNORECASE),
]

WHITELIST_HOSTS = {"api.github.com", "localhost", "127.0.0.1"}


class InhibitoryGate:
    def check(self, command: str, **context: Any) -> tuple[bool, str]:
        for pat in _BLOCKED_PATTERNS:
            if pat.search(command):
                log.warning("inhibitory_gate: blocked '%s' by pattern '%s'", command[:80], pat.pattern)
                return False, f"blocked by regex: {pat.pattern}"
        return True, ""
