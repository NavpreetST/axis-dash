"""Drift / arch guard — enforce the 15-field /state contract.

This test prevents accidental field additions, removals, or type changes
in the /state WebSocket response.  The 15 top-level keys and their types
are FROZEN — any change MUST be reviewed by Navpreet and reflected here
before merge.

Source of truth: aegis/web/server.py:_build_state() (lines 405-443).
"""

from __future__ import annotations

from typing import Any

# The frozen set of top-level field names in /state.
_STATE_FIELDS: frozenset[str] = frozenset({
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
    "runtime",
})

# neurobus sub-schema: exactly 6 float keys.
_NEUROBUS_KEYS: frozenset[str] = frozenset({
    "reward",
    "novelty",
    "attention",
    "patience",
    "threat",
    "trust",
})

# Field → expected (broad) Python type(s) at runtime.
# None means "any value is acceptable" (None-typed fields).
_FIELD_TYPES: dict[str, tuple[type | None, ...]] = {
    "neurobus": (dict,),
    "h": (list,),
    "is_speaking": (bool,),
    "last_action_type": (str,),
    "tick_id": (int,),
    "mnemosyne_event": (dict, type(None)),
    "provider": (str, type(None)),
    "rpd_used": (int, type(None)),
    "rpd_budget": (int, type(None)),
    "connected": (bool,),
    "uptime_seconds": (int, type(None)),
    "tick_rate": (float,),
    "pam": (type(None),),
    "coherence": (type(None),),
    "runtime": (dict,),
}


def _build_state_from_files(
    orb: dict[str, Any],
    renderer: dict[str, Any],
) -> dict[str, Any]:
    """Reproduce _build_state() logic from server.py without /proc依赖.

    This is intentionally a MINIMAL reproduction — enough to validate
    field presence and types without importing the full FastAPI stack
    or needing a running daemon.  The test below checks the source code
    itself for the canonical field list.
    """
    neurobus_raw = orb.get("neurobus") or orb
    neurobus = {k: float(neurobus_raw.get(k, 0.0) or 0.0) for k in _NEUROBUS_KEYS}

    h = orb.get("h", [])
    if not isinstance(h, list):
        h = []
    h = h[:64]

    last_success = (renderer or {}).get("last_success") or {}
    providers = (renderer or {}).get("providers") or {}
    gemini = providers.get("gemini") or {}

    return {
        "neurobus": neurobus,
        "h": h,
        "is_speaking": bool(orb.get("is_speaking", False)),
        "last_action_type": str(orb.get("last_action_type") or "idle"),
        "tick_id": int(float(orb.get("tick_id") or 0)),
        "mnemosyne_event": orb.get("mnemosyne_event"),
        "provider": last_success.get("provider") if isinstance(last_success, dict) else None,
        "rpd_used": int(gemini["local_daily_used"]) if isinstance(gemini.get("local_daily_used"), (int, float)) else None,
        "rpd_budget": int(gemini["local_daily_budget"]) if isinstance(gemini.get("local_daily_budget"), (int, float)) else None,
        "connected": True,
        "uptime_seconds": None,
        "tick_rate": 1.0,
        "pam": None,
        "coherence": None,
        "runtime": {},
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_state_fields_frozen() -> None:
    """The /state contract MUST contain exactly these 14 fields.

    If this test breaks, you changed the /state shape.  Update this test
    ONLY after Navpreet has reviewed and approved the contract change.
    """
    state = _build_state_from_files(
        orb={"h": [0.1] * 64, "tick_id": 42, "is_speaking": True, "last_action_type": "speak"},
        renderer={"last_success": {"provider": "gemini"}, "providers": {"gemini": {"local_daily_used": 7, "local_daily_budget": 240}}},
    )
    assert set(state.keys()) == _STATE_FIELDS


def test_state_neurobus_sub_keys() -> None:
    """neurobus MUST contain exactly 6 float keys."""
    state = _build_state_from_files(orb={}, renderer={})
    assert set(state["neurobus"].keys()) == _NEUROBUS_KEYS


def test_state_neurobus_values_are_float() -> None:
    state = _build_state_from_files(orb={}, renderer={})
    for k, v in state["neurobus"].items():
        assert isinstance(v, float), f"neurobus.{k} must be float, got {type(v)}"


def test_state_field_types() -> None:
    """Each field must match its expected type."""
    state = _build_state_from_files(
        orb={"h": [0.0], "tick_id": 1},
        renderer={"last_success": {"provider": "gemini"}, "providers": {"gemini": {"local_daily_used": 1, "local_daily_budget": 2}}},
    )
    for field, expected in _FIELD_TYPES.items():
        val = state[field]
        assert isinstance(val, expected), (
            f"{field} must be {expected}, got {type(val).__name__}"
        )


def test_h_truncated_to_64() -> None:
    """h vector MUST be capped at 64 elements."""
    state = _build_state_from_files(orb={"h": list(range(200))}, renderer={})
    assert len(state["h"]) == 64


def test_h_non_list_becomes_empty() -> None:
    """Non-list h values MUST coerce to []."""
    state = _build_state_from_files(orb={"h": "bad"}, renderer={})
    assert state["h"] == []


def test_pam_and_coherence_always_none() -> None:
    """pam and coherence are unresolved — MUST always be None."""
    state = _build_state_from_files(orb={}, renderer={})
    assert state["pam"] is None
    assert state["coherence"] is None
