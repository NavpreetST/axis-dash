"""NIM rate-limiter seam — enforces RPM cap for NVIDIA NIM API calls.

This is a standalone rate-limiter, OFF the interactive Gemini/Groq path.
It tracks call timestamps in-memory and evicts entries older than the
window.  Designed for the overnight consolidation loop: 10-20 calls/min
target, 30-40 hard cap.

Usage:
    from aegis.nim_budget import NIM_BUDGET
    if NIM_BUDGET.allow():
        await _call_nim(...)
"""
from __future__ import annotations

import os
import time

NIM_RPM_CAP = int(os.getenv("AEGIS_NIM_RPM_CAP", "40"))
NIM_TARGET_RPM = int(os.getenv("AEGIS_NIM_TARGET_RPM", "15"))
NIM_INTERVAL_S = int(os.getenv("AEGIS_NIM_INTERVAL_S", "86400"))
NIM_BATCH_SIZE = int(os.getenv("AEGIS_NIM_BATCH_SIZE", "20"))
NIM_MODEL = os.getenv("AEGIS_NIM_MODEL", "meta/llama-3.3-70b-instruct")


class NimBudget:
    """Sliding-window RPM rate-limiter for NIM calls.

    Timestamps are stored in-memory only — a daemon restart resets the
    budget, which is fine for a background consolidation job.
    """

    def __init__(self, rpm_cap: int = NIM_RPM_CAP, window_s: float = 60.0) -> None:
        self.rpm_cap = rpm_cap
        self.window_s = window_s
        self._timestamps: list[float] = []

    def _evict_stale(self) -> None:
        """Remove timestamps older than the sliding window."""
        now = time.time()
        cutoff = now - self.window_s
        self._timestamps = [t for t in self._timestamps if t > cutoff]

    def allow(self) -> bool:
        """Return True if a call is within budget, and record the timestamp."""
        self._evict_stale()
        if len(self._timestamps) >= self.rpm_cap:
            return False
        self._timestamps.append(time.time())
        return True

    @property
    def remaining(self) -> int:
        """Remaining calls in the current window."""
        self._evict_stale()
        return max(0, self.rpm_cap - len(self._timestamps))

    def wait_s(self) -> float:
        """Seconds to wait until the next call is allowed (0.0 if immediate)."""
        self._evict_stale()
        if len(self._timestamps) < self.rpm_cap:
            return 0.0
        oldest = self._timestamps[0]
        return max(0.0, oldest + self.window_s - time.time())


# Module-level singleton — shared across all _call_nim invocations
NIM_BUDGET = NimBudget()
