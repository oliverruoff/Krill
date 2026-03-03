"""Authentication and session helpers."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import TypedDict
from uuid import uuid4

from fastapi import Request

from .config import (
    clear_auth_ip_lock,
    count_auth_users,
    create_auth_session,
    create_auth_user,
    get_auth_ip_lock,
    get_auth_session_by_id,
    get_auth_user_by_username,
    register_auth_failed_attempt,
    revoke_auth_session,
    touch_auth_session,
)


SESSION_COOKIE_NAME = "krill_session"
_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")
_PASSWORD_MIN_LENGTH = 8
_PASSWORD_MAX_LENGTH = 200


class AuthSession(TypedDict):
    user_id: str
    username: str
    session_id: str


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _session_ttl_seconds() -> int:
    raw = str(os.getenv("KRILL_AUTH_SESSION_TTL_SECONDS", "86400")).strip()
    try:
        value = int(raw)
    except ValueError:
        return 86400
    return max(900, min(2592000, value))


def _hash_iterations() -> int:
    raw = str(os.getenv("KRILL_AUTH_HASH_ITERATIONS", "200000")).strip()
    try:
        value = int(raw)
    except ValueError:
        return 200000
    return max(100000, min(600000, value))


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc_iso(value: str) -> datetime | None:
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_username(username: str) -> str:
    return str(username).strip().lower()


def validate_username(username: str) -> str:
    normalized = normalize_username(username)
    if not _USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError("Username must be 3-64 chars and use letters, numbers, dot, underscore, or dash.")
    return normalized


def validate_password(password: str) -> str:
    value = str(password)
    if len(value) < _PASSWORD_MIN_LENGTH:
        raise ValueError("Password must be at least 8 characters long.")
    if len(value) > _PASSWORD_MAX_LENGTH:
        raise ValueError("Password is too long.")
    return value


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    iterations = _hash_iterations()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        salt.hex(),
        digest.hex(),
    )


def verify_password(password: str, stored_hash: str) -> bool:
    parts = str(stored_hash).split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return False
    try:
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        expected = bytes.fromhex(parts[3])
    except (ValueError, TypeError):
        return False
    computed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=len(expected))
    return hmac.compare_digest(computed, expected)


def _session_secret() -> str:
    return str(os.getenv("KRILL_AUTH_SESSION_SECRET", "")).strip()


def _session_hash(token: str) -> str:
    base = f"{_session_secret()}:{token}".encode("utf-8")
    return hashlib.sha256(base).hexdigest()


def build_session_cookie_value(session_id: str, token: str) -> str:
    return f"{session_id}.{token}"


def parse_session_cookie(cookie_value: str) -> tuple[str, str] | None:
    raw = str(cookie_value).strip()
    if not raw or "." not in raw:
        return None
    session_id, token = raw.split(".", 1)
    if not session_id or not token:
        return None
    return session_id.strip(), token.strip()


def session_cookie_max_age() -> int:
    return _session_ttl_seconds()


def session_cookie_secure(request: Request) -> bool:
    override = os.getenv("KRILL_AUTH_SECURE_COOKIE")
    if override is not None:
        return _bool_env("KRILL_AUTH_SECURE_COOKIE", False)
    scheme = str(request.url.scheme).strip().lower()
    if scheme == "https":
        return True

    host = str(request.url.hostname or "").strip().lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return False

    return True


def is_trust_proxy_enabled() -> bool:
    return _bool_env("KRILL_TRUST_PROXY", False)


def get_client_ip(request: Request) -> str:
    if is_trust_proxy_enabled():
        forwarded = str(request.headers.get("x-forwarded-for", "")).strip()
        if forwarded:
            first = forwarded.split(",", 1)[0].strip()
            if first:
                return first
    if request.client is not None and request.client.host:
        return str(request.client.host)
    return "unknown"


async def is_bootstrap_required() -> bool:
    return (await count_auth_users()) == 0


async def bootstrap_single_admin(username: str, password: str) -> dict[str, str]:
    if not await is_bootstrap_required():
        raise RuntimeError("Authentication is already configured.")
    normalized_username = validate_username(username)
    normalized_password = validate_password(password)
    password_digest = hash_password(normalized_password)
    return await create_auth_user(normalized_username, password_digest)


async def create_login_session(user_id: str, username: str, ip: str) -> tuple[str, str]:
    session_id = str(uuid4())
    session_token = secrets.token_urlsafe(48)
    expires_at = (_now_utc() + timedelta(seconds=_session_ttl_seconds())).isoformat()
    await create_auth_session(
        session_id=session_id,
        user_id=user_id,
        session_hash=_session_hash(session_token),
        expires_at=expires_at,
        ip=ip,
    )
    return build_session_cookie_value(session_id, session_token), username


async def is_ip_banned(ip: str) -> bool:
    lock_state = await get_auth_ip_lock(ip)
    if lock_state is None:
        return False
    banned_until = _parse_utc_iso(str(lock_state.get("banned_until", "")))
    if banned_until is None:
        return False
    return banned_until > _now_utc()


async def authenticate_login(username: str, password: str, ip: str) -> tuple[str, str]:
    if await is_ip_banned(ip):
        raise PermissionError("Too many failed login attempts. Try again later.")

    normalized_username = validate_username(username)
    normalized_password = validate_password(password)
    user = await get_auth_user_by_username(normalized_username)

    if user is None or not verify_password(normalized_password, str(user.get("password_hash", ""))):
        result = await register_auth_failed_attempt(ip)
        if bool(result.get("is_banned")):
            raise PermissionError("Too many failed login attempts. Try again later.")
        raise ValueError("Invalid username or password.")

    await clear_auth_ip_lock(ip)
    return await create_login_session(str(user["id"]), str(user["username"]), ip)


async def resolve_session(cookie_value: str) -> AuthSession | None:
    parsed = parse_session_cookie(cookie_value)
    if parsed is None:
        return None
    session_id, token = parsed
    session = await get_auth_session_by_id(session_id)
    if session is None:
        return None

    revoked_at = _parse_utc_iso(str(session.get("revoked_at", "")))
    if revoked_at is not None:
        return None

    expires_at = _parse_utc_iso(str(session.get("expires_at", "")))
    if expires_at is None or expires_at <= _now_utc():
        await revoke_auth_session(session_id)
        return None

    if not hmac.compare_digest(str(session.get("session_hash", "")), _session_hash(token)):
        return None

    await touch_auth_session(session_id)
    return AuthSession(
        user_id=str(session.get("user_id", "")),
        username=str(session.get("username", "")),
        session_id=session_id,
    )


async def resolve_session_from_request(request: Request) -> AuthSession | None:
    cookie_value = request.cookies.get(SESSION_COOKIE_NAME, "")
    return await resolve_session(str(cookie_value))


async def logout_session(cookie_value: str) -> None:
    parsed = parse_session_cookie(cookie_value)
    if parsed is None:
        return
    session_id, _ = parsed
    await revoke_auth_session(session_id)
