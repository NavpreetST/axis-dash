"""B2 cold backup — periodic upload of JSONL event files to Backblaze B2.

Reads creds from ~/.config/aegis/secrets.env (NEVER from repo .env).
Gracefully skips if B2_APPLICATION_KEY_ID or B2_APPLICATION_KEY are not set.

Uses httpx (already a helios dependency) for the B2 native API.
Object Lock is OFF — files are uploaded as-is, no retention policy.

Upload strategy:
  - On each tick (60s), scan STATE_DIR/events/ for JSONL files
  - Upload any file that hasn't been uploaded yet (tracked via a local manifest)
  - The manifest lives at STATE_DIR/events/.b2_manifest.json
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
from urllib.parse import quote

log = logging.getLogger(__name__)

B2_KEY_ID = os.getenv("B2_APPLICATION_KEY_ID", "")
B2_APP_KEY = os.getenv("B2_APPLICATION_KEY", "")
B2_BUCKET = os.getenv("B2_BUCKET", "helios-eventlog")
B2_PREFIX = "events/"

STATE_DIR = Path(os.getenv("AEGIS_STATE_DIR", "/var/lib/aegis"))
EVENTS_DIR = STATE_DIR / "events"
MANIFEST_PATH = EVENTS_DIR / ".b2_manifest.json"

UPLOAD_INTERVAL_SECONDS = 60.0

_enabled = bool(B2_KEY_ID and B2_APP_KEY)


def _load_manifest() -> dict[str, str]:
    """Load the upload manifest: {filename: sha256_hex}."""
    if MANIFEST_PATH.exists():
        try:
            return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_manifest(manifest: dict[str, str]) -> None:
    try:
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    except OSError as e:
        log.warning("b2: failed to save manifest — %s", e)


def _sha256_sync(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha1_sync(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


async def _sha256(path: Path) -> str:
    return await asyncio.to_thread(_sha256_sync, path)


async def _sha1(path: Path) -> str:
    return await asyncio.to_thread(_sha1_sync, path)


async def _get_b2_auth() -> dict:
    """Authorize with B2 and return auth data (token + api URL)."""
    import httpx

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            "https://api.backblazeb2.com/b2api/v2/b2_authorize_account",
            auth=(B2_KEY_ID, B2_APP_KEY),
        )
        resp.raise_for_status()
        return resp.json()


async def _get_upload_url(auth: dict, bucket_id: str) -> dict:
    """Get a dedicated upload URL from B2 (step 1 of two-step upload)."""
    import httpx

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{auth['apiUrl']}/b2api/v2/b2_get_upload_url",
            headers={"Authorization": auth["authorizationToken"]},
            json={"bucketId": bucket_id},
        )
        resp.raise_for_status()
        return resp.json()


async def _upload_file(
    upload_url: str,
    upload_token: str,
    file_path: Path,
    file_name: str,
) -> bool:
    """Upload a file to B2 using the native API (step 2 of two-step upload)."""
    import httpx

    file_content = file_path.read_bytes()
    content_sha1 = hashlib.sha1(file_content).hexdigest()

    headers = {
        "Authorization": upload_token,
        "X-Bz-File-Name": quote(
            file_name,
            safe="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-/~!$'*;=:@",
        ),
        "Content-Type": "application/octet-stream",
        "Content-Length": str(len(file_content)),
        "X-Bz-Content-Sha1": content_sha1,
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(upload_url, headers=headers, content=file_content)
            if resp.status_code == 200:
                log.info("b2: uploaded %s (%d bytes)", file_name, len(file_content))
                return True
            log.warning("b2: upload failed (%d): %s", resp.status_code, resp.text[:200])
            return False
    except Exception as e:
        log.warning("b2: upload error for %s — %s", file_name, e)
        return False


async def run() -> None:
    """Periodically upload JSONL files to B2.

    This is a STUB that can be activated by setting B2_APPLICATION_KEY_ID
    and B2_APPLICATION_KEY in ~/.config/aegis/secrets.env.  When creds
    are absent, the coroutine waits indefinitely (no-op).
    """
    if not _enabled:
        log.info("b2 backup: skipped (no B2_APPLICATION_KEY_ID / B2_APPLICATION_KEY)")
        await asyncio.Event().wait()  # sleep forever (truly)
        return

    log.info("b2 backup running → bucket=%s prefix=%s", B2_BUCKET, B2_PREFIX)

    while True:
        await asyncio.sleep(UPLOAD_INTERVAL_SECONDS)

        try:
            manifest = _load_manifest()

            # Find JSONL files to upload
            jsonl_files = sorted(EVENTS_DIR.glob("*.jsonl"))

            if not jsonl_files:
                continue

            # Get B2 auth once per cycle
            auth = await _get_b2_auth()

            # Get bucket ID
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{auth['apiUrl']}/b2api/v2/b2_get_bucket",
                    headers={"Authorization": auth["authorizationToken"]},
                    json={"bucketName": B2_BUCKET},
                )
                resp.raise_for_status()
                bucket_id = resp.json()["bucketId"]

            # Get a fresh upload URL for this cycle
            upload_data = await _get_upload_url(auth, bucket_id)
            upload_url = upload_data["uploadUrl"]
            upload_token = upload_data["authorizationToken"]

            for fpath in jsonl_files:
                fname = fpath.name
                current_hash = await _sha256(fpath)

                # Skip if already uploaded with same hash
                if manifest.get(fname) == current_hash:
                    continue

                remote_name = f"{B2_PREFIX}{fname}"
                success = await _upload_file(upload_url, upload_token, fpath, remote_name)
                if success:
                    manifest[fname] = current_hash
                    _save_manifest(manifest)

        except Exception as e:
            log.warning("b2 backup cycle error — %s", e)
