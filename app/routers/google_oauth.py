"""Google OAuth API routes and state helpers."""

from __future__ import annotations

import asyncio
import ipaddress
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ..config import McpConfig, load_settings, save_settings
from ..mcps.google_services import (
    ACCESS_MODE_PARAM,
    ACCESS_MODE_READ_ONLY,
    ACCESS_TOKEN_PARAM,
    CLIENT_ID_PARAM,
    CLIENT_SECRET_PARAM,
    CONNECTED_EMAIL_PARAM,
    GOOGLE_MCP_ID,
    REFRESH_TOKEN_PARAM,
    SCOPES_PARAM,
    TOKEN_EXPIRY_PARAM,
    build_google_oauth_authorize_url,
    exchange_google_oauth_code,
    fetch_google_account_email,
    google_oauth_scopes_for_mode,
    normalize_google_access_mode,
    resolve_google_client_credentials,
    revoke_google_token,
)


router = APIRouter()

_GOOGLE_OAUTH_STATE_TTL_SECONDS = 600
_google_oauth_states: dict[str, dict[str, object]] = {}
_google_oauth_lock = asyncio.Lock()
_PUBLIC_BASE_URL_ENV = "KRILL_PUBLIC_BASE_URL"


class GoogleOAuthStatusResponse(BaseModel):
    connected: bool
    access_mode: str
    email: str
    has_refresh_token: bool
    scopes: list[str] = Field(default_factory=list)


@router.get("/api/mcps/google/oauth/status", response_model=GoogleOAuthStatusResponse)
async def get_google_oauth_status() -> GoogleOAuthStatusResponse:
    settings = await load_settings()
    config = settings.mcp_configs.get(GOOGLE_MCP_ID) or McpConfig()
    params = dict(config.params)
    access_mode = normalize_google_access_mode(params.get(ACCESS_MODE_PARAM, ""))
    email_value = str(params.get(CONNECTED_EMAIL_PARAM, "")).strip()
    refresh_token = str(params.get(REFRESH_TOKEN_PARAM, "")).strip()
    scope_value = str(params.get(SCOPES_PARAM, "")).strip()
    scopes = [scope for scope in scope_value.split(" ") if scope.strip()] if scope_value else []
    connected = bool(refresh_token or str(params.get(ACCESS_TOKEN_PARAM, "")).strip())
    return GoogleOAuthStatusResponse(
        connected=connected,
        access_mode=access_mode,
        email=email_value,
        has_refresh_token=bool(refresh_token),
        scopes=scopes,
    )


@router.get("/api/mcps/google/oauth/start", response_class=HTMLResponse)
async def start_google_oauth(request: Request) -> HTMLResponse:
    settings = await load_settings()
    config = settings.mcp_configs.get(GOOGLE_MCP_ID) or McpConfig()
    params = dict(config.params)

    try:
        client_id, client_secret = resolve_google_client_credentials(params)
    except RuntimeError as exc:
        return HTMLResponse(content=_google_popup_html(False, str(exc)), status_code=422)

    if params.get(CLIENT_ID_PARAM) != client_id or params.get(CLIENT_SECRET_PARAM) != client_secret:
        updated_params = dict(params)
        updated_params[CLIENT_ID_PARAM] = client_id
        updated_params[CLIENT_SECRET_PARAM] = client_secret
        settings.mcp_configs[GOOGLE_MCP_ID] = McpConfig(enabled=config.enabled, params=updated_params)
        await save_settings(settings)
        params = updated_params

    access_mode = normalize_google_access_mode(params.get(ACCESS_MODE_PARAM, ""))
    state_token = secrets.token_urlsafe(32)
    await _register_google_oauth_state(state_token, {"access_mode": access_mode})
    redirect_uri = _build_google_oauth_redirect_uri(request)
    if _is_blocked_private_ip_google_redirect_uri(redirect_uri):
        return HTMLResponse(
            content=_google_popup_html(
                False,
                (
                    "Google OAuth blocks private-IP redirect URIs for this flow. "
                    f"Current callback: {redirect_uri}. "
                    "Use a public HTTPS domain/reverse-proxy URL or set "
                    f"{_PUBLIC_BASE_URL_ENV}=http://localhost:8055 when accessing Krill locally."
                ),
            ),
            status_code=422,
        )
    auth_url = build_google_oauth_authorize_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state_token,
        access_mode=access_mode,
    )
    return HTMLResponse(content=_google_oauth_start_html(auth_url))


@router.get("/api/mcps/google/oauth/callback", response_class=HTMLResponse, name="google_oauth_callback")
async def google_oauth_callback(
    request: Request,
    code: str = Query(default=""),
    state: str = Query(default=""),
    error_text: str = Query(default="", alias="error"),
) -> HTMLResponse:
    if error_text.strip():
        return HTMLResponse(content=_google_popup_html(False, f"Google OAuth error: {error_text.strip()}"), status_code=400)

    if not code.strip() or not state.strip():
        return HTMLResponse(content=_google_popup_html(False, "Google OAuth callback is missing code or state."), status_code=400)

    state_payload = await _consume_google_oauth_state(state.strip())
    if state_payload is None:
        return HTMLResponse(content=_google_popup_html(False, "Google OAuth state is invalid or expired."), status_code=400)
    requested_access_mode = normalize_google_access_mode(state_payload.get(ACCESS_MODE_PARAM, ""))

    settings = await load_settings()
    config = settings.mcp_configs.get(GOOGLE_MCP_ID) or McpConfig()
    params = dict(config.params)
    try:
        client_id, client_secret = resolve_google_client_credentials(params)
    except RuntimeError as exc:
        return HTMLResponse(content=_google_popup_html(False, str(exc)), status_code=422)

    redirect_uri = _build_google_oauth_redirect_uri(request)

    try:
        token_payload = await asyncio.to_thread(
            exchange_google_oauth_code,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            code=code.strip(),
        )
        access_token = str(token_payload.get("access_token", "")).strip()
        if not access_token:
            raise RuntimeError("OAuth exchange did not return an access token.")

        refresh_token = str(token_payload.get("refresh_token", "")).strip() or str(params.get(REFRESH_TOKEN_PARAM, "")).strip()
        expires_in_raw = token_payload.get("expires_in")
        expires_in = int(expires_in_raw) if isinstance(expires_in_raw, int) else 3600
        safe_expiry = max(60, min(86400, expires_in))
        expiry_iso = (datetime.now(timezone.utc) + timedelta(seconds=max(30, safe_expiry - 30))).isoformat()
        scope_value = str(token_payload.get("scope", "")).strip()
        if not scope_value:
            scope_value = " ".join(google_oauth_scopes_for_mode(requested_access_mode))

        connected_email = ""
        try:
            connected_email = await asyncio.to_thread(fetch_google_account_email, access_token=access_token)
        except Exception:
            connected_email = str(params.get(CONNECTED_EMAIL_PARAM, "")).strip()

        updated_params = dict(params)
        updated_params[CLIENT_ID_PARAM] = client_id
        updated_params[CLIENT_SECRET_PARAM] = client_secret
        updated_params[ACCESS_MODE_PARAM] = requested_access_mode
        updated_params[ACCESS_TOKEN_PARAM] = access_token
        if refresh_token:
            updated_params[REFRESH_TOKEN_PARAM] = refresh_token
        updated_params[TOKEN_EXPIRY_PARAM] = expiry_iso
        updated_params[SCOPES_PARAM] = scope_value
        updated_params[CONNECTED_EMAIL_PARAM] = connected_email
        settings.mcp_configs[GOOGLE_MCP_ID] = McpConfig(enabled=config.enabled, params=updated_params)
        await save_settings(settings)
    except Exception as exc:
        return HTMLResponse(content=_google_popup_html(False, f"Google OAuth callback failed: {exc}"), status_code=422)

    return HTMLResponse(content=_google_popup_html(True, "Google account connected. You can close this window."))


@router.post("/api/mcps/google/oauth/disconnect", response_model=GoogleOAuthStatusResponse)
async def disconnect_google_oauth() -> GoogleOAuthStatusResponse:
    settings = await load_settings()
    config = settings.mcp_configs.get(GOOGLE_MCP_ID) or McpConfig()
    params = dict(config.params)
    access_token = str(params.get(ACCESS_TOKEN_PARAM, "")).strip()
    refresh_token = str(params.get(REFRESH_TOKEN_PARAM, "")).strip()

    if access_token:
        try:
            await asyncio.to_thread(revoke_google_token, token=access_token)
        except Exception:
            pass
    if refresh_token:
        try:
            await asyncio.to_thread(revoke_google_token, token=refresh_token)
        except Exception:
            pass

    for key in (ACCESS_TOKEN_PARAM, REFRESH_TOKEN_PARAM, TOKEN_EXPIRY_PARAM, SCOPES_PARAM, CONNECTED_EMAIL_PARAM):
        params.pop(key, None)
    params[ACCESS_MODE_PARAM] = normalize_google_access_mode(params.get(ACCESS_MODE_PARAM, ACCESS_MODE_READ_ONLY))

    settings.mcp_configs[GOOGLE_MCP_ID] = McpConfig(enabled=config.enabled, params=params)
    await save_settings(settings)

    return GoogleOAuthStatusResponse(
        connected=False,
        access_mode=params[ACCESS_MODE_PARAM],
        email="",
        has_refresh_token=False,
        scopes=[],
    )


def _build_google_oauth_redirect_uri(request: Request) -> str:
    override = os.getenv(_PUBLIC_BASE_URL_ENV, "").strip()
    if not override:
        return str(request.url_for("google_oauth_callback"))

    normalized = override if override.startswith("http://") or override.startswith("https://") else f"https://{override}"
    parsed = urlsplit(normalized)
    if not parsed.scheme or not parsed.netloc:
        return str(request.url_for("google_oauth_callback"))

    base_path = parsed.path.rstrip("/")
    callback_path = f"{base_path}/api/mcps/google/oauth/callback"
    return urlunsplit((parsed.scheme, parsed.netloc, callback_path, "", ""))


def _is_blocked_private_ip_google_redirect_uri(redirect_uri: str) -> bool:
    hostname = (urlsplit(redirect_uri).hostname or "").strip().lower()
    if not hostname:
        return False
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        return False

    try:
        ip_value = ipaddress.ip_address(hostname)
    except ValueError:
        return False

    return ip_value.is_private


async def _register_google_oauth_state(state_token: str, payload: dict[str, object]) -> None:
    now = int(time.time())
    async with _google_oauth_lock:
        _prune_google_oauth_states(now)
        _google_oauth_states[state_token] = {
            "created_at": now,
            "payload": dict(payload),
        }


async def _consume_google_oauth_state(state_token: str) -> dict[str, object] | None:
    now = int(time.time())
    async with _google_oauth_lock:
        _prune_google_oauth_states(now)
        entry = _google_oauth_states.pop(state_token, None)
        if not isinstance(entry, dict):
            return None
        payload = entry.get("payload")
        return payload if isinstance(payload, dict) else {}


def _prune_google_oauth_states(now_unix: int) -> None:
    expired: list[str] = []
    for state_token, entry in _google_oauth_states.items():
        created_at = entry.get("created_at") if isinstance(entry, dict) else None
        if not isinstance(created_at, int):
            expired.append(state_token)
            continue
        if created_at + _GOOGLE_OAUTH_STATE_TTL_SECONDS < now_unix:
            expired.append(state_token)
    for state_token in expired:
        _google_oauth_states.pop(state_token, None)


def _google_popup_html(ok: bool, message: str) -> str:
    safe_message = str(message).replace("<", "&lt;").replace(">", "&gt;")
    title = "Google Connected" if ok else "Google OAuth Error"
    color = "#2c7a4b" if ok else "#a1302d"
    return (
        "<!doctype html>"
        "<html><head><meta charset='utf-8'><title>"
        + title
        + "</title><style>"
        "body{font-family:ui-sans-serif,Segoe UI,Arial,sans-serif;margin:0;padding:24px;background:#f7f8fa;color:#1d2330;}"
        ".card{max-width:560px;margin:0 auto;padding:20px;border:1px solid #d7dbe3;border-radius:12px;background:#ffffff;}"
        "h1{margin:0 0 12px;font-size:20px;color:"
        + color
        + ";}"
        "p{margin:0 0 16px;line-height:1.5;}"
        "a{color:#1b4baf;text-decoration:none;}"
        "</style></head><body><div class='card'><h1>"
        + title
        + "</h1><p>"
        + safe_message
        + "</p><p><a href='/setup?edit=1'>Return to Setup</a></p></div>"
        "<script>try{if(window.opener){window.opener.postMessage({type:'krill-google-oauth-finished',ok:"
        + ("true" if ok else "false")
        + "},window.location.origin);}}catch(_e){}window.setTimeout(function(){window.close();},1200);</script>"
        "</body></html>"
    )


def _google_oauth_start_html(auth_url: str) -> str:
    safe_url = str(auth_url).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    script_url = str(auth_url).replace('"', "\\\"")
    return (
        "<!doctype html>"
        "<html><head><meta charset='utf-8'><title>Google Login</title><style>"
        "body{font-family:ui-sans-serif,Segoe UI,Arial,sans-serif;margin:0;padding:24px;background:#f7f8fa;color:#1d2330;}"
        ".card{max-width:640px;margin:0 auto;padding:20px;border:1px solid #d7dbe3;border-radius:12px;background:#ffffff;}"
        "h1{margin:0 0 12px;font-size:20px;color:#1b4baf;}"
        "p{margin:0 0 16px;line-height:1.5;}"
        "a{color:#1b4baf;text-decoration:none;}"
        "</style></head><body><div class='card'><h1>Opening Google login...</h1><p>If you are not redirected automatically, click below.</p><p><a href='"
        + safe_url
        + "'>Continue to Google OAuth</a></p></div><script>window.location.replace(\""
        + script_url
        + "\");</script></body></html>"
    )
