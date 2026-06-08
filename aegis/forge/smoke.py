#!/usr/bin/env python3
"""Forge smoke test — end-to-end: trivial task → diff → gate → result.

Usage:
    cd /opt/aegis && source .venv/bin/activate
    python -m aegis.forge.smoke

Requires the aegis daemon to be running (aegis.main) with forge enabled.
"""

import asyncio
import os
import sys

# Ensure secrets are loaded
_env = os.path.expanduser("~/.config/aegis/secrets.env")
if os.path.exists(_env):
    with open(_env) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

from pathlib import Path  # noqa: E402

from aegis.forge.dispatcher import ForgeDispatcher, TaskStatus  # noqa: E402
from aegis.forge.gate import GateStage  # noqa: E402
from aegis.forge.manager import ForgeManager  # noqa: E402


async def smoke_test() -> int:
    print("=== Forge Smoke Test ===")
    print()

    # 1. Start forge manager
    print("[1/5] Starting forge server...")
    manager = ForgeManager()
    try:
        await manager.start()
    except Exception as e:
        print(f"  FAIL: could not start forge server: {e}")
        print("  (is opencode installed? `which opencode`)")
        return 1
    print(f"  OK — server on port {manager._port}")

    try:
        # 2. Submit a trivial task
        print("[2/5] Submitting trivial task...")
        dispatcher = ForgeDispatcher(manager)
        task = await dispatcher.submit(
            "Create a file called hello.py with a function hello() "
            "that returns the string 'hello from forge'"
        )
        print(f"  OK — task {task.id}")

        # 3. Execute the task
        print("[3/5] Executing task (this may take a minute)...")
        task = await dispatcher.execute(task.id)
        print(f"  Status: {task.status.value}")
        print(f"  Diffs: {len(task.diffs)}")
        print(f"  Files created: {task.files_created}")
        print(f"  Files modified: {task.files_modified}")

        if task.status == TaskStatus.FAILED:
            print(f"  FAIL: {task.error}")
            return 1

        # 4. Run gate
        print("[4/5] Running gate stage...")
        gate = GateStage(task.workdir)
        gate_result = await gate.run_all()
        print(f"  Lint: {'PASS' if gate_result.lint_passed else 'FAIL'}")
        print(f"  Tests: {'PASS' if gate_result.test_passed else 'FAIL'}")
        print(f"  Build: {'PASS' if gate_result.build_passed else 'FAIL'}")
        print(f"  Overall: {'PASS' if gate_result.overall_passed else 'FAIL'}")
        print(f"  Gate time: {gate_result.gate_ms}ms")

        # 5. Verify sandbox contents
        print("[5/5] Checking sandbox...")
        workdir = Path(task.workdir)
        if workdir.exists():
            files = list(workdir.rglob("*"))
            print(f"  Workdir: {workdir}")
            print(f"  Files: {[f.name for f in files if f.is_file()]}")
        else:
            print(f"  Workdir missing: {workdir}")

        print()
        print("=== Smoke Test Complete ===")
        return 0

    finally:
        await manager.stop()


if __name__ == "__main__":
    rc = asyncio.run(smoke_test())
    sys.exit(rc)
