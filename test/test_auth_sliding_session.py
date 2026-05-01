"""Verifies auth sessions use a sliding expiry window."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _session_id_from_cookie(cookie_value: str) -> str:
    session_id, _, _token = cookie_value.partition(".")
    if not session_id:
        raise RuntimeError("Session cookie did not include a session id.")
    return session_id


def _session_row(db_path: Path, session_id: str) -> dict[str, str]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT session_id, expires_at, last_seen_at, revoked_at FROM auth_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"Session {session_id} was not persisted.")
        return {key: str(row[key]) for key in row.keys()}
    finally:
        conn.close()


def _set_session_expires_at(db_path: Path, session_id: str, expires_at: datetime) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "UPDATE auth_sessions SET expires_at = ? WHERE session_id = ?",
            (expires_at.isoformat(), session_id),
        )
        conn.commit()
    finally:
        conn.close()


def _cleanup_db_artifacts(db_path: Path) -> None:
    for path in (db_path, db_path.with_name(f"{db_path.name}-wal"), db_path.with_name(f"{db_path.name}-shm")):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


async def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    temp_root = repo_root / "tmp_verify_data"
    temp_root.mkdir(parents=True, exist_ok=True)
    db_path = temp_root / f"krill_auth_sliding_session_{uuid.uuid4().hex}.db"
    os.environ["KRILL_BRAINDUMP_PATH"] = str(db_path)
    os.environ["KRILL_AUTH_SESSION_TTL_SECONDS"] = "1800"
    os.environ["KRILL_AUTH_SESSION_SECRET"] = "auth-sliding-session-test-secret"

    from app.auth import (  # pylint: disable=import-outside-toplevel
        authenticate_login,
        bootstrap_single_admin,
        resolve_session,
    )
    from app.config import ensure_settings_file  # pylint: disable=import-outside-toplevel

    await ensure_settings_file()
    await bootstrap_single_admin("admin-user", "correct-horse-password")

    before_login = datetime.now(timezone.utc)
    cookie_value, username = await authenticate_login("admin-user", "correct-horse-password", "127.0.0.1")
    if username != "admin-user":
        raise RuntimeError(f"Expected normalized admin username, got {username!r}.")

    session_id = _session_id_from_cookie(cookie_value)
    created_row = _session_row(db_path, session_id)
    created_expires_at = _parse_iso(created_row["expires_at"])
    created_delta = (created_expires_at - before_login).total_seconds()
    if not 1790 <= created_delta <= 1810:
        raise RuntimeError(f"Expected login TTL near 1800 seconds, got {created_delta:.1f}.")

    shortened_expires_at = datetime.now(timezone.utc) + timedelta(seconds=900)
    _set_session_expires_at(db_path, session_id, shortened_expires_at)

    before_resolve = datetime.now(timezone.utc)
    resolved = await resolve_session(cookie_value)
    if resolved is None or resolved["session_id"] != session_id:
        raise RuntimeError("Expected valid session to resolve before expiry.")

    renewed_row = _session_row(db_path, session_id)
    renewed_expires_at = _parse_iso(renewed_row["expires_at"])
    renewed_delta = (renewed_expires_at - before_resolve).total_seconds()
    if not 1790 <= renewed_delta <= 1810:
        raise RuntimeError(f"Expected renewed TTL near 1800 seconds, got {renewed_delta:.1f}.")
    if renewed_expires_at <= shortened_expires_at:
        raise RuntimeError("Expected session expiry to move forward after successful resolve.")

    expired_cookie_value, _ = await authenticate_login("admin-user", "correct-horse-password", "127.0.0.1")
    expired_session_id = _session_id_from_cookie(expired_cookie_value)
    _set_session_expires_at(db_path, expired_session_id, datetime.now(timezone.utc) - timedelta(seconds=1))

    expired_result = await resolve_session(expired_cookie_value)
    if expired_result is not None:
        raise RuntimeError("Expected expired session to be rejected.")

    expired_row = _session_row(db_path, expired_session_id)
    if not expired_row["revoked_at"]:
        raise RuntimeError("Expected expired session to be revoked.")

    _cleanup_db_artifacts(db_path)
    print("PASS: auth sessions are created with the configured TTL, renewed on resolve, and revoked after expiry.")


if __name__ == "__main__":
    asyncio.run(main())
