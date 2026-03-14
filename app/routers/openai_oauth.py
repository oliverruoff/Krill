"""OpenAI Codex OAuth API routes and state helpers."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import time
from urllib.parse import parse_qs, urlsplit, urlunsplit

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ..config import ProviderConfig, load_settings, save_settings
from ..timed_jobs import clear_timed_job_auth_alert_provider_id
from ..providers.openai_codex_oauth import (
    OPENAI_CODEX_OAUTH_PROVIDER_ID,
    OpenAICodexOAuthCredentials,
    build_openai_codex_authorize_url,
    exchange_openai_codex_code,
    parse_oauth_bundle,
    probe_supported_models,
    serialize_oauth_bundle,
)


router = APIRouter()

_OPENAI_OAUTH_STATE_TTL_SECONDS = 900
_openai_oauth_states: dict[str, dict[str, object]] = {}
_openai_oauth_lock = asyncio.Lock()
_PUBLIC_BASE_URL_ENV = "KRILL_PUBLIC_BASE_URL"


class ModelOption(BaseModel):
    id: str
    label: str
    token_limit: int


class OpenAIOAuthStatusResponse(BaseModel):
    connected: bool
    provider_id: str
    account_id: str
    expires_at_unix: int = 0
    expires_in_seconds: int = 0
    detail: str = ""
    credential_bundle: str = ""


class OpenAIOAuthCompleteRequest(BaseModel):
    redirect_url_or_code: str = Field(min_length=1, max_length=8000)


class OpenAIOAuthModelsResponse(BaseModel):
    connected: bool
    models: list[ModelOption] = Field(default_factory=list)
    unsupported_models: list[dict[str, str]] = Field(default_factory=list)
    detail: str = ""


@router.get("/api/providers/openai-codex/oauth/status", response_model=OpenAIOAuthStatusResponse)
async def get_openai_oauth_status() -> OpenAIOAuthStatusResponse:
    settings = await load_settings()
    provider_config = settings.provider_configs.get(OPENAI_CODEX_OAUTH_PROVIDER_ID)
    if provider_config is None or not provider_config.api_key.strip():
        return OpenAIOAuthStatusResponse(
            connected=False,
            provider_id=OPENAI_CODEX_OAUTH_PROVIDER_ID,
            account_id="",
            expires_at_unix=0,
            expires_in_seconds=0,
            detail="Not connected.",
            credential_bundle="",
        )

    try:
        credentials = parse_oauth_bundle(provider_config.api_key)
    except Exception as exc:
        return OpenAIOAuthStatusResponse(
            connected=False,
            provider_id=OPENAI_CODEX_OAUTH_PROVIDER_ID,
            account_id="",
            expires_at_unix=0,
            expires_in_seconds=0,
            detail=f"Stored OAuth credentials are invalid: {exc}",
            credential_bundle=provider_config.api_key,
        )

    now_unix = int(time.time())
    expires_in = max(0, credentials.expires_at_unix - now_unix)
    return OpenAIOAuthStatusResponse(
        connected=bool(credentials.refresh_token and credentials.access_token),
        provider_id=OPENAI_CODEX_OAUTH_PROVIDER_ID,
        account_id=credentials.account_id,
        expires_at_unix=credentials.expires_at_unix,
        expires_in_seconds=expires_in,
        detail="Connected" if expires_in > 0 else "Connected (token refresh will happen automatically).",
        credential_bundle=provider_config.api_key,
    )


@router.get("/api/providers/openai-codex/oauth/models", response_model=OpenAIOAuthModelsResponse)
async def get_openai_oauth_supported_models() -> OpenAIOAuthModelsResponse:
    settings = await load_settings()
    provider_config = settings.provider_configs.get(OPENAI_CODEX_OAUTH_PROVIDER_ID)
    if provider_config is None or not provider_config.api_key.strip():
        return OpenAIOAuthModelsResponse(
            connected=False,
            models=[],
            unsupported_models=[],
            detail="OpenAI OAuth is not connected.",
        )

    try:
        credentials = parse_oauth_bundle(provider_config.api_key)
    except Exception as exc:
        return OpenAIOAuthModelsResponse(
            connected=False,
            models=[],
            unsupported_models=[],
            detail=f"Stored OAuth credentials are invalid: {exc}",
        )

    try:
        result = await asyncio.to_thread(probe_supported_models, credentials)
    except Exception as exc:
        return OpenAIOAuthModelsResponse(
            connected=True,
            models=[],
            unsupported_models=[],
            detail=f"Model probe failed: {exc}",
        )

    refreshed_credentials = result.get("credentials")
    if isinstance(refreshed_credentials, OpenAICodexOAuthCredentials):
        await _persist_openai_oauth_credentials(refreshed_credentials)

    supported_raw = result.get("supported_models", [])
    unsupported_raw = result.get("unsupported_models", [])

    models: list[ModelOption] = []
    if isinstance(supported_raw, list):
        for item in supported_raw:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id", "")).strip()
            label = str(item.get("label", model_id)).strip() or model_id
            token_limit = item.get("token_limit")
            if not isinstance(token_limit, int):
                token_limit = 400000
            if model_id:
                models.append(ModelOption(id=model_id, label=label, token_limit=token_limit))

    unsupported_models: list[dict[str, str]] = []
    if isinstance(unsupported_raw, list):
        for item in unsupported_raw:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id", "")).strip()
            reason = str(item.get("reason", "")).strip()
            if model_id:
                unsupported_models.append({"id": model_id, "reason": reason})

    detail = ""
    if models:
        detail = f"Detected {len(models)} supported model(s) for this account."
    else:
        detail = "No supported models detected for this account."

    return OpenAIOAuthModelsResponse(
        connected=True,
        models=models,
        unsupported_models=unsupported_models,
        detail=detail,
    )


@router.get("/api/providers/openai-codex/oauth/start", response_class=HTMLResponse)
async def start_openai_oauth(request: Request) -> HTMLResponse:
    mode = str(request.query_params.get("mode", "manual")).strip().lower()
    use_manual = mode in {"manual", "paste", "localhost"}
    redirect_uri = "http://localhost:1455/auth/callback" if use_manual else _build_openai_oauth_redirect_uri(request)
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(72)
    code_challenge = _pkce_s256_challenge(verifier)

    await _register_openai_oauth_state(
        state,
        {
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
            "created_mode": "manual" if use_manual else "auto",
        },
    )

    auth_url = build_openai_codex_authorize_url(
        state=state,
        code_challenge=code_challenge,
        redirect_uri=redirect_uri,
    )
    return HTMLResponse(content=_openai_oauth_start_html(auth_url, use_manual))


@router.get("/api/providers/openai-codex/oauth/callback", response_class=HTMLResponse, name="openai_oauth_callback")
async def openai_oauth_callback(
    code: str = Query(default=""),
    state: str = Query(default=""),
    error_text: str = Query(default="", alias="error"),
) -> HTMLResponse:
    if error_text.strip():
        return HTMLResponse(content=_openai_popup_html(False, f"OpenAI OAuth error: {error_text.strip()}"), status_code=400)

    if not code.strip() or not state.strip():
        return HTMLResponse(content=_openai_popup_html(False, "OpenAI OAuth callback is missing code or state."), status_code=400)

    state_payload = await _consume_openai_oauth_state(state.strip())
    if state_payload is None:
        return HTMLResponse(content=_openai_popup_html(False, "OpenAI OAuth state is invalid or expired."), status_code=400)

    code_verifier = str(state_payload.get("code_verifier", "")).strip()
    redirect_uri = str(state_payload.get("redirect_uri", "")).strip()
    if not code_verifier or not redirect_uri:
        return HTMLResponse(content=_openai_popup_html(False, "OpenAI OAuth flow is missing verifier or redirect metadata."), status_code=422)

    try:
        credentials = await asyncio.to_thread(
            exchange_openai_codex_code,
            code=code.strip(),
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
        )
        await _persist_openai_oauth_credentials(credentials)
    except Exception as exc:
        return HTMLResponse(content=_openai_popup_html(False, f"OpenAI OAuth callback failed: {exc}"), status_code=422)

    return HTMLResponse(content=_openai_popup_html(True, "OpenAI account connected. You can close this window."))


@router.post("/api/providers/openai-codex/oauth/complete", response_model=OpenAIOAuthStatusResponse)
async def complete_openai_oauth(payload: OpenAIOAuthCompleteRequest) -> OpenAIOAuthStatusResponse:
    parsed = _parse_openai_manual_redirect_input(payload.redirect_url_or_code)
    state = parsed.get("state", "")
    code = parsed.get("code", "")
    if not state or not code:
        raise HTTPException(status_code=422, detail="Could not parse OAuth code/state from pasted input.")

    state_payload = await _consume_openai_oauth_state(state)
    if state_payload is None:
        raise HTTPException(status_code=422, detail="OpenAI OAuth state is invalid or expired. Start OAuth again.")

    code_verifier = str(state_payload.get("code_verifier", "")).strip()
    redirect_uri = str(state_payload.get("redirect_uri", "")).strip()
    if not code_verifier or not redirect_uri:
        raise HTTPException(status_code=422, detail="OpenAI OAuth state is missing verifier metadata.")

    try:
        credentials = await asyncio.to_thread(
            exchange_openai_codex_code,
            code=code,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
        )
        await _persist_openai_oauth_credentials(credentials)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"OpenAI OAuth completion failed: {exc}") from exc

    now_unix = int(time.time())
    return OpenAIOAuthStatusResponse(
        connected=True,
        provider_id=OPENAI_CODEX_OAUTH_PROVIDER_ID,
        account_id=credentials.account_id,
        expires_at_unix=credentials.expires_at_unix,
        expires_in_seconds=max(0, credentials.expires_at_unix - now_unix),
        detail="Connected",
        credential_bundle=serialize_oauth_bundle(credentials),
    )


@router.post("/api/providers/openai-codex/oauth/disconnect", response_model=OpenAIOAuthStatusResponse)
async def disconnect_openai_oauth() -> OpenAIOAuthStatusResponse:
    settings = await load_settings()
    provider_config = settings.provider_configs.get(OPENAI_CODEX_OAUTH_PROVIDER_ID)
    if provider_config is None:
        return OpenAIOAuthStatusResponse(
            connected=False,
            provider_id=OPENAI_CODEX_OAUTH_PROVIDER_ID,
            account_id="",
            expires_at_unix=0,
            expires_in_seconds=0,
            detail="Not connected.",
            credential_bundle="",
        )

    settings.provider_configs[OPENAI_CODEX_OAUTH_PROVIDER_ID] = provider_config.model_copy(update={"api_key": ""})
    if settings.active_provider_id == OPENAI_CODEX_OAUTH_PROVIDER_ID:
        settings.setup_completed = False
    await save_settings(settings)

    return OpenAIOAuthStatusResponse(
        connected=False,
        provider_id=OPENAI_CODEX_OAUTH_PROVIDER_ID,
        account_id="",
        expires_at_unix=0,
        expires_in_seconds=0,
        detail="Disconnected",
        credential_bundle="",
    )


def _pkce_s256_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _build_openai_oauth_redirect_uri(request: Request) -> str:
    override = os.getenv(_PUBLIC_BASE_URL_ENV, "").strip()
    if not override:
        return str(request.url_for("openai_oauth_callback"))

    normalized = override if override.startswith("http://") or override.startswith("https://") else f"https://{override}"
    parsed = urlsplit(normalized)
    if not parsed.scheme or not parsed.netloc:
        return str(request.url_for("openai_oauth_callback"))

    base_path = parsed.path.rstrip("/")
    callback_path = f"{base_path}/api/providers/openai-codex/oauth/callback"
    return urlunsplit((parsed.scheme, parsed.netloc, callback_path, "", ""))


async def _register_openai_oauth_state(state_token: str, payload: dict[str, object]) -> None:
    now = int(time.time())
    async with _openai_oauth_lock:
        _prune_openai_oauth_states(now)
        _openai_oauth_states[state_token] = {
            "created_at": now,
            "payload": dict(payload),
        }


async def _consume_openai_oauth_state(state_token: str) -> dict[str, object] | None:
    now = int(time.time())
    async with _openai_oauth_lock:
        _prune_openai_oauth_states(now)
        entry = _openai_oauth_states.pop(state_token, None)
        if not isinstance(entry, dict):
            return None
        payload = entry.get("payload")
        return payload if isinstance(payload, dict) else {}


def _prune_openai_oauth_states(now_unix: int) -> None:
    expired: list[str] = []
    for state_token, entry in _openai_oauth_states.items():
        created_at = entry.get("created_at") if isinstance(entry, dict) else None
        if not isinstance(created_at, int):
            expired.append(state_token)
            continue
        if created_at + _OPENAI_OAUTH_STATE_TTL_SECONDS < now_unix:
            expired.append(state_token)
    for state_token in expired:
        _openai_oauth_states.pop(state_token, None)


async def _persist_openai_oauth_credentials(credentials: OpenAICodexOAuthCredentials) -> None:
    settings = await load_settings()
    existing = settings.provider_configs.get(OPENAI_CODEX_OAUTH_PROVIDER_ID)
    existing_model = existing.model.strip() if existing is not None and existing.model.strip() else "gpt-5.3-codex"
    if existing is None:
        settings.provider_configs[OPENAI_CODEX_OAUTH_PROVIDER_ID] = ProviderConfig(
            api_key=serialize_oauth_bundle(credentials),
            model=existing_model,
        )
    else:
        settings.provider_configs[OPENAI_CODEX_OAUTH_PROVIDER_ID] = existing.model_copy(
            update={"api_key": serialize_oauth_bundle(credentials), "model": existing_model}
        )
    await save_settings(settings)
    await clear_timed_job_auth_alert_provider_id(OPENAI_CODEX_OAUTH_PROVIDER_ID)


def _parse_openai_manual_redirect_input(raw_input: str) -> dict[str, str]:
    value = str(raw_input).strip()
    if not value:
        return {"code": "", "state": ""}

    try:
        parsed_url = urlsplit(value)
        if parsed_url.scheme and parsed_url.netloc:
            query = parse_qs(parsed_url.query)
            code = str(query.get("code", [""])[0]).strip()
            state = str(query.get("state", [""])[0]).strip()
            return {"code": code, "state": state}
    except Exception:
        pass

    if "code=" in value:
        query = parse_qs(value)
        code = str(query.get("code", [""])[0]).strip()
        state = str(query.get("state", [""])[0]).strip()
        return {"code": code, "state": state}

    if "#" in value:
        code_part, state_part = value.split("#", 1)
        return {"code": code_part.strip(), "state": state_part.strip()}

    return {"code": value, "state": ""}


def _openai_popup_html(ok: bool, message: str) -> str:
    safe_message = str(message).replace("<", "&lt;").replace(">", "&gt;")
    title = "OpenAI Connected" if ok else "OpenAI OAuth Error"
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
        "<script>try{if(window.opener){window.opener.postMessage({type:'krill-openai-oauth-finished',ok:"
        + ("true" if ok else "false")
        + "},window.location.origin);}}catch(_e){}window.setTimeout(function(){window.close();},1200);</script>"
        "</body></html>"
    )


def _openai_oauth_start_html(auth_url: str, manual_mode: bool) -> str:
    raw_url = str(auth_url)
    safe_url = raw_url.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    script_url = json.dumps(raw_url)
    guidance = (
        "If login does not return to Krill automatically, copy the full final redirect URL from your browser and paste it in Setup using Complete Manual OAuth."
        if manual_mode
        else "If you are not redirected automatically, click the link below."
    )
    return (
        "<!doctype html>"
        "<html><head><meta charset='utf-8'><title>OpenAI Login</title><style>"
        "body{font-family:ui-sans-serif,Segoe UI,Arial,sans-serif;margin:0;padding:24px;background:#f7f8fa;color:#1d2330;}"
        ".card{max-width:640px;margin:0 auto;padding:20px;border:1px solid #d7dbe3;border-radius:12px;background:#ffffff;}"
        "h1{margin:0 0 12px;font-size:20px;color:#1b4baf;}"
        "p{margin:0 0 16px;line-height:1.5;}"
        "a{color:#1b4baf;text-decoration:none;}"
        "code{background:#f1f3f8;padding:2px 6px;border-radius:6px;}"
        "</style></head><body><div class='card'><h1>Opening OpenAI login...</h1><p>"
        + guidance
        + "</p><p><a id='oauth-link' href='"
        + safe_url
        + "'>Continue to OpenAI OAuth</a></p><p><small>"
        + ("Manual mode redirect URI: <code>http://localhost:1455/auth/callback</code>" if manual_mode else "")
        + "</small></p></div><script>window.location.replace("
        + script_url
        + ");</script></body></html>"
    )
