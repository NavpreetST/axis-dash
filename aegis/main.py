"""Aegis — boots Nexus + all modules + tick loop, serves a unix socket.

Per-connection request/reply: each client gets the next action.speak
within a 10 s window after each input line.

Forge commands (prefix FORGE:) are intercepted before the brain pipeline:
  FORGE:SUBMIT:<json>  — submit a coding task
  FORGE:POLL:<id>      — poll task status
  FORGE:FETCH:<id>     — fetch task result/diffs
  FORGE:LIST           — list all tasks
  FORGE:GATE:<id>      — run gate stage on completed task
  FORGE:CLEANUP:<id>   — remove task sandbox
"""

import asyncio
import json
import logging
import os
from pathlib import Path

_env = Path.home() / ".config" / "aegis" / "secrets.env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from aegis.brain import ncp
from aegis.forge.dispatcher import ForgeDispatcher
from aegis.forge.gate import GateStage
from aegis.forge.manager import ForgeManager
from aegis.hive import text_encoder
from aegis.mnemosyne import retrieve, write
from aegis.mnemosyne.db import CONN as _MNEMO_CONN
from aegis.mnemosyne.db import seed_if_empty as _seed_if_empty
from aegis.nexus import clock, neurobus
from aegis.nexus.bus import BUS
from aegis.observability import b2_sync, eventlog, supabase_sync, turns
from aegis import consolidation
from aegis.renderer import dispatcher
from aegis.renderer.gemini import validate_sku as _validate_sku

logging.basicConfig(
    level=os.getenv("AEGIS_LOG", "INFO"),
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
log = logging.getLogger("aegis")

SOCK_PATH = Path(os.getenv("AEGIS_SOCK", "/tmp/aegis.sock"))
REPLY_TIMEOUT = float(os.getenv("AEGIS_REPLY_TIMEOUT", "15.0"))

# Forge globals — set during main() boot
_forge_manager: ForgeManager | None = None
_forge_dispatcher: ForgeDispatcher | None = None


async def _handle_forge_command(line: str) -> str:
    """Handle FORGE: prefixed commands. Returns response string."""
    global _forge_manager, _forge_dispatcher

    parts = line.split(":", 2)
    if len(parts) < 2:
        return "FORGE:ERR:malformed command"

    cmd = parts[1].upper()

    if cmd == "SUBMIT":
        if _forge_dispatcher is None:
            return "FORGE:ERR:forge not initialized"
        spec = (parts[2] if len(parts) > 2 else "").strip()
        if not spec or len(spec) < 10:
            return "FORGE:ERR:invalid spec (must be >= 10 chars)"
        try:
            task = await _forge_dispatcher.submit(spec)
            asyncio.create_task(_execute_and_log(task.id))
            return f"FORGE:OK:{task.id}"
        except Exception as e:
            return f"FORGE:ERR:{e}"

    elif cmd in ("POLL", "FETCH"):
        if _forge_dispatcher is None:
            return "FORGE:ERR:forge not initialized"
        task_id = parts[2] if len(parts) > 2 else ""
        from aegis.forge.dispatcher import get_task

        task = get_task(task_id)
        if task is None:
            return f"FORGE:ERR:unknown task {task_id}"
        prefix = "STATUS" if cmd == "POLL" else "RESULT"
        return f"FORGE:{prefix}:{json.dumps(task.to_dict())}"

    elif cmd == "LIST":
        from aegis.forge.dispatcher import list_tasks

        tasks = list_tasks()
        return f"FORGE:LIST:{json.dumps([t.to_dict() for t in tasks])}"

    elif cmd == "GATE":
        if _forge_dispatcher is None:
            return "FORGE:ERR:forge not initialized"
        task_id = parts[2] if len(parts) > 2 else ""
        from aegis.forge.dispatcher import TaskStatus, get_task

        task = get_task(task_id)
        if task is None:
            return f"FORGE:ERR:unknown task {task_id}"
        if task.status != TaskStatus.COMPLETED:
            return f"FORGE:ERR:task not completed (status={task.status.value})"
        gate = GateStage(task.workdir)
        result = await gate.run_all()
        approved = await gate.request_owner_approval(task_id, result) if result.overall_passed else False
        task = await _forge_dispatcher.complete_gate(task_id, result, approved)
        return f"FORGE:GATE:{json.dumps(result.to_dict())}"

    elif cmd == "CLEANUP":
        if _forge_dispatcher is None:
            return "FORGE:ERR:forge not initialized"
        task_id = parts[2] if len(parts) > 2 else ""
        await _forge_dispatcher.cleanup(task_id)
        return f"FORGE:OK:{task_id} cleaned"

    else:
        return f"FORGE:ERR:unknown command {cmd}"


async def _execute_and_log(task_id: str) -> None:
    """Execute a forge task and log the result."""
    global _forge_dispatcher
    if _forge_dispatcher is None:
        return
    try:
        task = await _forge_dispatcher.execute(task_id)
        await eventlog.log_event(
            source="forge",
            event_type="forge_task_completed",
            payload={
                "task_id": task_id,
                "status": task.status.value,
                "diffs": len(task.diffs),
                "files_created": len(task.files_created),
                "files_modified": len(task.files_modified),
            },
            severity="info",
            sensitivity="internal",
        )
    except Exception as e:
        await eventlog.log_event(
            source="forge",
            event_type="forge_task_failed",
            payload={"task_id": task_id, "error": str(e)},
            severity="error",
            sensitivity="internal",
        )


async def serve_unix_socket() -> None:
    SOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SOCK_PATH.exists():
        SOCK_PATH.unlink()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        reply_q = BUS.subscribe("action.speak")
        try:
            while not reader.at_eof():
                raw = await reader.readline()
                if not raw:
                    break
                line = raw.decode(errors="replace")

                # Intercept FORGE: commands before brain pipeline
                if line.startswith("FORGE:"):
                    try:
                        response = await _handle_forge_command(line.strip())
                    except Exception as e:
                        log.exception("unhandled error in forge handler")
                        response = f"FORGE:ERR:internal error: {e}"
                    writer.write((response + "\n").encode())
                    await writer.drain()
                    continue

                # Normal brain pipeline
                await text_encoder.ingest_text(line)
                try:
                    msg = await asyncio.wait_for(reply_q.get(), timeout=REPLY_TIMEOUT)
                    reply_text = msg.payload["text"]
                    writer.write((reply_text + "\n").encode())
                    await writer.drain()

                    await eventlog.log_event(
                        source="aegis",
                        event_type="chat_turn",
                        payload={
                            "prompt": line.strip(),
                            "reply": reply_text,
                        },
                        severity="info",
                        sensitivity="internal",
                    )
                except TimeoutError:
                    writer.write(b"(no reply within timeout)\n")
                    await writer.drain()
        except Exception as e:
            log.warning("client handler error: %s", e)
        finally:
            try:
                writer.close()
            except Exception:
                pass

    server = await asyncio.start_unix_server(handle, str(SOCK_PATH))
    os.chmod(SOCK_PATH, 0o660)
    log.info("unix socket at %s", SOCK_PATH)
    async with server:
        await server.serve_forever()


async def main() -> None:
    global _forge_manager, _forge_dispatcher

    log.info("aegis booting...")
    await text_encoder.prime()
    _seed_if_empty(_MNEMO_CONN)

    # Boot forge (opencode server) — non-fatal if it fails
    _forge_manager = ForgeManager()
    try:
        await _forge_manager.start()
        log.info("forge online")
        _forge_dispatcher = ForgeDispatcher(_forge_manager)
    except Exception as e:
        log.warning("forge failed to start (tasks unavailable): %s", e)
        _forge_manager = None
        _forge_dispatcher = None

    async def _forge_reap_loop() -> None:
        """Periodically reap old completed forge tasks."""
        while True:
            await asyncio.sleep(300)  # every 5 min
            if _forge_dispatcher:
                try:
                    n = _forge_dispatcher.reap_completed(max_age_seconds=3600)
                    if n:
                        log.info("forge: reaped %d old tasks", n)
                except Exception as e:
                    log.error("forge: reap error: %s", e)

    async def _supervised_consolidation() -> None:
        """Supervised wrapper for consolidation.run().

        Crash isolation: catches any exception from consolidation.run()
        and logs it, but NEVER lets it propagate into the daemon's
        asyncio.gather().  This ensures consolidation crashes never
        cancel sibling tasks or take down the 1 Hz Nexus.
        """
        while True:
            try:
                await consolidation.run()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("consolidation: supervised crash — %s", e, exc_info=True)
                await asyncio.sleep(60)  # backoff before retry

    tasks = [
        asyncio.create_task(clock.run(hz=1.0)),
        asyncio.create_task(neurobus.run()),
        asyncio.create_task(ncp.run()),
        asyncio.create_task(dispatcher.run()),
        asyncio.create_task(turns.run()),
        asyncio.create_task(eventlog.run()),
        asyncio.create_task(supabase_sync.run()),
        asyncio.create_task(b2_sync.run()),
        asyncio.create_task(write.run()),
        asyncio.create_task(retrieve.run()),
        asyncio.create_task(serve_unix_socket()),
        asyncio.create_task(_forge_reap_loop()),
        asyncio.create_task(_supervised_consolidation()),
    ]
    log.info("aegis online — connect via the aegis CLI")
    try:
        # Emit startup event — best-effort, never block boot
        try:
            await eventlog.log_event(
                source="aegis",
                event_type="task_done",
                payload={"task": "boot", "status": "online"},
                severity="info",
                sensitivity="internal",
            )
        except Exception:
            log.debug("main: failed to emit startup event", exc_info=True)
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        log.info("shutting down")
        # Emit shutdown event — best-effort, never hang teardown
        try:
            await asyncio.wait_for(
                eventlog.log_event(
                    source="aegis",
                    event_type="error",
                    payload={"where": "main_loop", "reason": "shutdown"},
                    severity="warn",
                    sensitivity="internal",
                ),
                timeout=2.0,
            )
        except Exception:
            log.debug("main: failed to emit shutdown event", exc_info=True)
        for t in tasks:
            t.cancel()
        if _forge_dispatcher:
            await _forge_dispatcher.shutdown()
        if _forge_manager:
            await _forge_manager.stop()
    except Exception as e:
        await eventlog.log_event(
            source="aegis",
            event_type="error",
            payload={"where": "main_loop", "err": str(e)},
            severity="error",
            sensitivity="internal",
        )
        if _forge_dispatcher:
            await _forge_dispatcher.shutdown()
        if _forge_manager:
            await _forge_manager.stop()
        raise


if __name__ == "__main__":
    _validate_sku()
    asyncio.run(main())
