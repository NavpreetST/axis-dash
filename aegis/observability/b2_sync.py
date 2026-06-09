"""B2 cold backup — compressed, timestamped upload of JSONL event files.

Uploads the append-only JSONL log to Backblaze B2 (S3-compatible API) as
gzip-compressed, timestamped objects.  The LOCAL JSONL stays source of
truth; B2 is archival/cold only — never gates or blocks the write path.

Reads creds from ~/.config/aegis/secrets.env (NEVER from repo .env).
Gracefully skips if B2_APPLICATION_KEY_ID or B2_APPLICATION_KEY are not set.

Uses httpx (already a helios dependency) for the B2 native API.

Upload strategy:
  - On each tick (60s), scan STATE_DIR/events/ for JSONL files
  - Upload any file that hasn't been uploaded yet (tracked via local manifest)
  - Files are gzip-compressed before upload; object name: events/YYYY-MM-DD.jsonl.gz
  - Manifest tracks {filename: sha256} to skip unchanged files
  - Retry with exponential backoff (1s → 2s → 4s → … capped at 30s) on failure
"""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import logging
import os
from pathlib import Path
from urllib.parse import quote

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (from env / secrets.env)
# ---------------------------------------------------------------------------
B2_KEY_ID: str = os.getenv("B2_APPLICATION_KEY_ID", "")
B2_APP_KEY: str = os.getenv("B2_APPLICATION_KEY", "")
B2_BUCKET: str = os.getenv("B2_BUCKET", "helios-eventlog")
B2_PREFIX: str = "events/"

STATE_DIR = Path(os.getenv("AEGIS_STATE_DIR", "/var/lib/aegis"))
EVENTS_DIR = STATE_DIR / "events"
MANIFEST_PATH = EVENTS_DIR / ".b2_manifest.json"

UPLOAD_INTERVAL_SECONDS: float = 60.0

# Retry / back-off
MAX_RETRIES: int = 5
INITIAL_BACKOFF: float = 1.0
BACKOFF_CAP: float = 30.0

_enabled: bool = bool(B2_KEY_ID and B2_APP_KEY)


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Hash helpers (threaded for large files)
# ---------------------------------------------------------------------------


def _sha256_sync(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _gzip_bytes(data: bytes) -> bytes:
    return gzip.compress(data, compresslevel=6)


async def _sha256(path: Path) -> str:
    return await asyncio.to_thread(_sha256_sync, path)


# ---------------------------------------------------------------------------
# B2 API helpers
# ---------------------------------------------------------------------------


async def _b2_authorize() -> dict:
    """Authorize with B2 and return auth data (token + api URL)."""
    import httpx

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            "https://api.backblazeb2.com/b2api/v2/b2_authorize_account",
            auth=(B2_KEY_ID, B2_APP_KEY),
        )
        resp.raise_for_status()
        return resp.json()


async def _b2_get_upload_url(auth: dict, bucket_id: str) -> dict:
    """Get a dedicated upload URL from B2."""
    import httpx

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{auth['apiUrl']}/b2api/v2/b2_get_upload_url",
            headers={"Authorization": auth["authorizationToken"]},
            json={"bucketId": bucket_id},
        )
        resp.raise_for_status()
        return resp.json()


async def _b2_get_bucket_id(auth: dict) -> str:
    """Resolve bucket name to bucket ID via b2_list_buckets."""
    import httpx

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{auth['apiUrl']}/b2api/v2/b2_list_buckets",
            headers={"Authorization": auth["authorizationToken"]},
            json={"accountId": auth["accountId"], "bucketName": B2_BUCKET},
        )
        resp.raise_for_status()
        buckets = resp.json().get("buckets", [])
        for b in buckets:
            if b.get("bucketName") == B2_BUCKET:
                return b["bucketId"]
        raise RuntimeError(f"b2: bucket {B2_BUCKET!r} not found")


async def _b2_upload(
    upload_url: str,
    upload_token: str,
    compressed: bytes,
    remote_name: str,
) -> bool:
    """Upload gzipped bytes to B2.  Returns True on success."""
    import httpx

    content_sha1 = hashlib.sha1(compressed).hexdigest()
    headers = {
        "Authorization": upload_token,
        "X-Bz-File-Name": quote(
            remote_name,
            safe="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-/~!$'*;=:@",
        ),
        "Content-Type": "application/gzip",
        "Content-Length": str(len(compressed)),
        "X-Bz-Content-Sha1": content_sha1,
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(upload_url, headers=headers, content=compressed)
            if resp.status_code == 200:
                log.info("b2: uploaded %s (%d bytes compressed)", remote_name, len(compressed))
                return True
            log.warning("b2: upload failed (%d): %s", resp.status_code, resp.text[:200])
            return False
    except Exception as e:
        log.warning("b2: upload error for %s — %s", remote_name, e)
        return False


async def _upload_one_file(
    fpath: Path,
    auth: dict,
    bucket_id: str,
    manifest: dict[str, str],
) -> bool:
    """Compress + upload a single JSONL file to B2 with retry.

    Returns True if the file was uploaded (or already up-to-date).
    """
    fname = fpath.name
    current_hash = await _sha256(fpath)

    # Skip if already uploaded with same hash
    if manifest.get(fname) == current_hash:
        return True

    # Read + compress in thread to avoid blocking event loop
    raw = await asyncio.to_thread(fpath.read_bytes)
    compressed = await asyncio.to_thread(_gzip_bytes, raw)
    remote_name = f"{B2_PREFIX}{fname}.gz"

    backoff = INITIAL_BACKOFF
    last_exc: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            upload_data = await _b2_get_upload_url(auth, bucket_id)
            ok = await _b2_upload(
                upload_data["uploadUrl"],
                upload_data["authorizationToken"],
                compressed,
                remote_name,
            )
            if ok:
                manifest[fname] = current_hash
                _save_manifest(manifest)
                return True
            # Upload returned False (non-retryable server response)
            log.warning("b2: non-retryable upload failure for %s", fname)
            return False
        except Exception as exc:
            last_exc = exc
            log.warning(
                "b2: upload error (attempt %d/%d) — %s, retrying in %.1fs",
                attempt, MAX_RETRIES, exc, backoff,
            )

        if attempt < MAX_RETRIES:
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_CAP)

    log.error("b2: upload failed after %d attempts for %s", MAX_RETRIES, fname)
    if last_exc:
        raise last_exc from None
    return False


# ---------------------------------------------------------------------------
# Core coroutine
# ---------------------------------------------------------------------------


async def run() -> None:
    """Periodically upload JSONL files to B2 as gzip-compressed objects.

    When ``B2_APPLICATION_KEY_ID`` / ``B2_APPLICATION_KEY`` are unset the
    coroutine returns immediately (feature-flag OFF).
    """
    if not _enabled:
        log.info("b2 backup: skipped (no B2_APPLICATION_KEY_ID / B2_APPLICATION_KEY)")
        return

    log.info("b2 backup running → bucket=%s prefix=%s", B2_BUCKET, B2_PREFIX)

    while True:
        await asyncio.sleep(UPLOAD_INTERVAL_SECONDS)

        try:
            manifest = _load_manifest()
            jsonl_files = sorted(EVENTS_DIR.glob("*.jsonl"))

            if not jsonl_files:
                continue

            auth = await _b2_authorize()
            bucket_id = await _b2_get_bucket_id(auth)

            for fpath in jsonl_files:
                try:
                    await _upload_one_file(fpath, auth, bucket_id, manifest)
                except Exception as e:
                    log.warning("b2: failed to upload %s — %s", fpath.name, e)

        except Exception as e:
            log.warning("b2 backup cycle error — %s", e)
