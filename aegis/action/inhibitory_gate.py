"""Inhibitory gate — regex blocklist + host whitelist before shell_cmd execution.

Blocks dangerous commands before they reach the executor:
  - rm -rf (recursive forced deletion, variant forms)
  - sudo (privilege escalation)
  - curl/wget to non-whitelist hosts
  - /dev device access

Usage:
    from aegis.action.inhibitory_gate import InhibitoryGate
    gate = InhibitoryGate()
    ok, reason = gate.check("rm -rf /")
    # -> (False, "blocked by pattern: rm recursive force")
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger("action.inhibitory_gate")

WHITELIST_HOSTS = {"api.github.com", "localhost", "127.0.0.1"}

_BLOCKED_PATTERNS: list[re.Pattern] = [
    re.compile(r"\brm\s+(?:-[rf]+\s*)+[/\w]", re.IGNORECASE),
    re.compile(r"\bsudo\b", re.IGNORECASE),
    re.compile(r"/dev/\w+"),
    re.compile(r">\s*/dev/"),
    re.compile(r"\bdangerously\b", re.IGNORECASE),
]


def _extract_url(command: str) -> str | None:
    for token in command.split():
        if token.startswith(("http://", "https://")):
            parsed = urlparse(token)
            return parsed.netloc
    return None


class InhibitoryGate:
    def check(self, command: str, **context: Any) -> tuple[bool, str]:
        for pat in _BLOCKED_PATTERNS:
            if pat.search(command):
                log.warning("inhibitory_gate: blocked '%s' by pattern '%s'", command[:80], pat.pattern)
                return False, f"blocked by pattern: {pat.pattern}"

        cmd_name = command.strip().split(maxsplit=1)[0] if command.strip() else ""
        if cmd_name in ("curl", "wget"):
            host = _extract_url(command)
            if host is None or host not in WHITELIST_HOSTS:
                log.warning("inhibitory_gate: blocked %s to non-whitelist host '%s'", cmd_name, host)
                return False, f"blocked: {cmd_name} to non-whitelist host {host}"

        return True, ""
