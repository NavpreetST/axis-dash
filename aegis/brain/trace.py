"""NCP tick trace logger — JSONL dump of every forward pass.

Each line: {timestamp, input_vec, output, intent, neurobus, text_input}
Used by eval_v0 probes (invariants, wirehead detector, vestigiality)
and reservoir baseline harness.

Best-effort: write errors logged at debug, never crash the tick loop.
"""
from __future__ import annotations

import json
import logging
import os
import time

from aegis.observability.paths import NCP_TRACE_PATH

log = logging.getLogger("brain.trace")

_MAX_LINES = int(os.getenv("AEGIS_NCP_TRACE_MAX_LINES", "100000"))

_file_handle = None
_lines_written = 0


def _open() -> None:
    global _file_handle, _lines_written
    if _file_handle is not None:
        return
    try:
        NCP_TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _file_handle = open(NCP_TRACE_PATH, "a")  # noqa: SIM115
        _lines_written = 0
    except OSError as e:
        log.debug("trace: failed to open %s — %s", NCP_TRACE_PATH, e)


def _rotate() -> None:
    global _file_handle, _lines_written
    try:
        _file_handle.close()
    except Exception:
        pass
    _file_handle = None
    _lines_written = 0


def write(
    *,
    input_vec: list[float],
    output: list[float],
    intent: dict,
    neurobus: dict,
    text_input: str,
    tick_dt: float,
) -> None:
    global _lines_written
    if _file_handle is None:
        _open()
    if _file_handle is None:
        return

    record = {
        "ts": time.time(),
        "input_vec": [round(v, 6) for v in input_vec],
        "output": [round(v, 6) for v in output],
        "intent": intent,
        "neurobus": {k: round(v, 4) for k, v in neurobus.items()},
        "text_input": text_input,
        "tick_dt": round(tick_dt, 4),
    }

    try:
        _file_handle.write(json.dumps(record, default=str) + "\n")
        _file_handle.flush()
        _lines_written += 1
        if _lines_written >= _MAX_LINES:
            _rotate()
    except OSError as e:
        log.debug("trace: write failed — %s", e)
