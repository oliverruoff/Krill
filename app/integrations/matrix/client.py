"""Minimal Matrix client helpers for bot sync and messaging."""

from __future__ import annotations

import json
from typing import Any
from urllib import error, parse, request


def _normalize_homeserver_url(homeserver_url: str) -> str:
    value = str(homeserver_url or "").strip().rstrip("/")
    if not value:
        raise ValueError("Matrix homeserver URL is required.")
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    return value


def _request_json(
    homeserver_url: str,
    path: str,
    access_token: str,
    *,
    method: str = "GET",
    body: dict[str, object] | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    base_url = _normalize_homeserver_url(homeserver_url)
    token = str(access_token or "").strip()
    if not token:
        raise ValueError("Matrix access token is required.")
    url = f"{base_url}{path}"
    payload_bytes = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if body is not None:
        payload_bytes = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=payload_bytes, method=method.upper(), headers=headers)
    with request.urlopen(req, timeout=timeout_seconds) as response:
        raw_body = response.read().decode("utf-8")
    if not raw_body.strip():
        return {}
    parsed = json.loads(raw_body)
    return parsed if isinstance(parsed, dict) else {}


def matrix_whoami(homeserver_url: str, access_token: str) -> dict[str, Any]:
    return _request_json(homeserver_url, "/_matrix/client/v3/account/whoami", access_token)


def matrix_sync(
    homeserver_url: str,
    access_token: str,
    *,
    since: str = "",
    timeout_ms: int = 25000,
) -> dict[str, Any]:
    query = {"timeout": str(max(0, int(timeout_ms)))}
    if since:
        query["since"] = since
    query_text = parse.urlencode(query)
    return _request_json(homeserver_url, f"/_matrix/client/v3/sync?{query_text}", access_token, timeout_seconds=max(30, timeout_ms // 1000 + 10))


def matrix_send_message(
    homeserver_url: str,
    access_token: str,
    room_id: str,
    text: str,
    *,
    txn_id: str,
) -> dict[str, Any]:
    safe_room_id = parse.quote(str(room_id or "").strip(), safe="")
    safe_txn_id = parse.quote(str(txn_id or "").strip(), safe="")
    return _request_json(
        homeserver_url,
        f"/_matrix/client/v3/rooms/{safe_room_id}/send/m.room.message/{safe_txn_id}",
        access_token,
        method="PUT",
        body={"msgtype": "m.text", "body": str(text or "")},
    )


def matrix_joined_members(homeserver_url: str, access_token: str, room_id: str) -> dict[str, Any]:
    safe_room_id = parse.quote(str(room_id or "").strip(), safe="")
    return _request_json(
        homeserver_url,
        f"/_matrix/client/v3/rooms/{safe_room_id}/joined_members",
        access_token,
    )


def matrix_room_name(homeserver_url: str, access_token: str, room_id: str) -> str:
    safe_room_id = parse.quote(str(room_id or "").strip(), safe="")
    try:
        payload = _request_json(
            homeserver_url,
            f"/_matrix/client/v3/rooms/{safe_room_id}/state/m.room.name",
            access_token,
        )
    except error.HTTPError:
        return ""
    return str(payload.get("name", "")).strip() if isinstance(payload, dict) else ""
