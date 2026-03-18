"""Ephemeral shared-file links for gateway and Telegram delivery."""

from __future__ import annotations

import asyncio
import mimetypes
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict


class SharedFileEntry(TypedDict):
    path: str
    filename: str
    media_type: str
    size_bytes: int
    created_at_unix: float
    expires_at_unix: float


_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{10,200}$")
_MIN_TTL_SECONDS = 60
_MAX_TTL_SECONDS = 24 * 60 * 60
_DEFAULT_TTL_SECONDS = 60 * 60

_shared_files_lock = asyncio.Lock()
_shared_files: dict[str, SharedFileEntry] = {}


def _clamp_ttl_seconds(value: int | float | None) -> int:
    if isinstance(value, bool):
        return _DEFAULT_TTL_SECONDS
    if isinstance(value, int | float):
        parsed = int(value)
    else:
        parsed = _DEFAULT_TTL_SECONDS
    return max(_MIN_TTL_SECONDS, min(_MAX_TTL_SECONDS, parsed))


def _guess_media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return str(guessed or "application/octet-stream")


def _sanitize_filename(value: str, fallback: str) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        candidate = fallback
    candidate = candidate.replace("\\", "_").replace("/", "_")
    candidate = re.sub(r"[\r\n\t]+", " ", candidate).strip()
    return candidate or fallback


def _now_unix() -> float:
    return time.time()


def _iso_from_unix(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


async def create_shared_file_link(path: Path, *, download_name: str = "", ttl_seconds: int | float | None = None) -> dict[str, object]:
    resolved = path.expanduser().resolve()
    if not resolved.exists() or not resolved.is_file():
        raise RuntimeError(f"File does not exist: {resolved}")

    token = secrets.token_urlsafe(24)
    ttl = _clamp_ttl_seconds(ttl_seconds)
    now_unix = _now_unix()
    expires_at_unix = now_unix + ttl
    stat = resolved.stat()
    filename = _sanitize_filename(download_name, resolved.name)
    entry: SharedFileEntry = {
        "path": str(resolved),
        "filename": filename,
        "media_type": _guess_media_type(resolved),
        "size_bytes": int(stat.st_size),
        "created_at_unix": now_unix,
        "expires_at_unix": expires_at_unix,
    }

    async with _shared_files_lock:
        await prune_expired_shared_files_locked(now_unix)
        _shared_files[token] = entry

    return {
        "token": token,
        "download_url": f"/api/files/shared/{token}",
        "filename": filename,
        "media_type": entry["media_type"],
        "size_bytes": entry["size_bytes"],
        "created_at": _iso_from_unix(now_unix),
        "expires_at": _iso_from_unix(expires_at_unix),
        "ttl_seconds": ttl,
    }


async def get_shared_file_entry(token: str) -> SharedFileEntry | None:
    normalized = str(token or "").strip()
    if not _TOKEN_PATTERN.fullmatch(normalized):
        return None
    now_unix = _now_unix()
    async with _shared_files_lock:
        await prune_expired_shared_files_locked(now_unix)
        entry = _shared_files.get(normalized)
        if entry is None:
            return None
        if entry["expires_at_unix"] <= now_unix:
            _shared_files.pop(normalized, None)
            return None
        return dict(entry)


async def prune_expired_shared_files_locked(now_unix: float | None = None) -> None:
    now_value = _now_unix() if now_unix is None else now_unix
    stale_tokens = [token for token, entry in _shared_files.items() if entry["expires_at_unix"] <= now_value]
    for token in stale_tokens:
        _shared_files.pop(token, None)


async def prune_expired_shared_files() -> None:
    async with _shared_files_lock:
        await prune_expired_shared_files_locked()
