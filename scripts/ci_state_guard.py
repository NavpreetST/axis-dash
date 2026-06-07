#!/usr/bin/env python3
"""CI drift / arch guard — enforce the 14-field /state contract.

Parses aegis/web/server.py and extracts the keys returned by _build_state().
Fails if:
  - The field count differs from 14
  - Any field name has changed
  - Any field has been removed

Usage: python scripts/ci_state_guard.py
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

SERVER_PY = Path(__file__).resolve().parent.parent / "aegis" / "web" / "server.py"

# The frozen set of top-level keys that _build_state() MUST return.
EXPECTED_FIELDS: frozenset[str] = frozenset({
    "neurobus",
    "h",
    "is_speaking",
    "last_action_type",
    "tick_id",
    "mnemosyne_event",
    "provider",
    "rpd_used",
    "rpd_budget",
    "connected",
    "uptime_seconds",
    "tick_rate",
    "pam",
    "coherence",
})

EXPECTED_COUNT = len(EXPECTED_FIELDS)  # 14


def _extract_return_keys_from_source(source: str) -> list[str] | None:
    """Find the return dict literal inside _build_state() and extract its keys.

    Uses AST parsing to avoid fragile regex.  Returns None if the function
    or return statement can't be found.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "_build_state":
            continue
        # Walk the function body for a Return statement with a Dict value.
        for stmt in ast.walk(node):
            if not isinstance(stmt, ast.Return) or not isinstance(stmt.value, ast.Dict):
                continue
            keys: list[str] = []
            for key_node in stmt.value.keys:
                if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                    keys.append(key_node.value)
                else:
                    # Non-constant key (computed) — abort
                    return None
            return keys
    return None


def _fallback_regex_extract(source: str) -> list[str] | None:
    """Fallback: regex-extract string keys from the return dict in _build_state().

    Only used if AST parsing fails (e.g. the source has syntax the parser
    doesn't understand).
    """
    # Find _build_state function body, then the return dict
    pattern = re.compile(
        r'def _build_state\b.*?return\s*\{(.*?)\}',
        re.DOTALL,
    )
    m = pattern.search(source)
    if not m:
        return None
    body = m.group(1)
    # Extract string literal keys: "key": ...
    keys = re.findall(r'"(\w+)"\s*:', body)
    return keys if keys else None


def main() -> int:
    if not SERVER_PY.exists():
        print(f"ERROR: {SERVER_PY} not found", file=sys.stderr)
        return 1

    source = SERVER_PY.read_text(encoding="utf-8")
    keys = _extract_return_keys_from_source(source)
    if keys is None:
        keys = _fallback_regex_extract(source)
    if keys is None:
        print("ERROR: could not extract _build_state() return keys", file=sys.stderr)
        return 1

    actual = frozenset(keys)
    count = len(keys)

    print(f"Detected {count} /state fields: {sorted(keys)}")

    errors: list[str] = []

    if count != EXPECTED_COUNT:
        errors.append(
            f"Field count changed: expected {EXPECTED_COUNT}, got {count}"
        )

    removed = EXPECTED_FIELDS - actual
    if removed:
        errors.append(f"Fields REMOVED (breaking): {sorted(removed)}")

    added = actual - EXPECTED_FIELDS
    if added:
        errors.append(f"Fields ADDED (review required): {sorted(added)}")

    if errors:
        print("\n*** DRIFT GUARD FAILED ***", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print(
            "\nTo fix: if the /state contract change is intentional, update "
            "EXPECTED_FIELDS in this script and tests/test_state_contract.py, "
            "then get Navpreet's approval.",
            file=sys.stderr,
        )
        return 1

    print("OK — /state contract is intact (14 fields, no drift).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
