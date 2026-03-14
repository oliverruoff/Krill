"""Google Gemini OAuth (unofficial) provider routes."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ..config import ProviderConfig, load_settings, save_settings
from ..providers.gemini_oauth import (
    GEMINI_OAUTH_PROVIDER_ID,
    GeminiOAuthCredentials,
    parse_gemini_oauth_bundle,
    probe_supported_models,
    serialize_gemini_oauth_bundle,
)
from ..timed_jobs import clear_timed_job_auth_alert_provider_id


router = APIRouter()


class ModelOption(BaseModel):
    id: str
    label: str
    token_limit: int


class GeminiOAuthStatusResponse(BaseModel):
    connected: bool
    provider_id: str
    email: str
    expires_at_unix: int = 0
    expires_in_seconds: int = 0
    detail: str = ""
    credential_bundle: str = ""


class GeminiOAuthCompleteRequest(BaseModel):
    oauth_payload_or_path: str = Field(min_length=1, max_length=200000)


class GeminiOAuthModelsResponse(BaseModel):
    connected: bool
    models: list[ModelOption] = Field(default_factory=list)
    unsupported_models: list[dict[str, str]] = Field(default_factory=list)
    detail: str = ""


@router.get("/api/providers/google-gemini/oauth/status", response_model=GeminiOAuthStatusResponse)
async def get_gemini_oauth_status() -> GeminiOAuthStatusResponse:
    settings = await load_settings()
    config = settings.provider_configs.get(GEMINI_OAUTH_PROVIDER_ID)
    if config is None or not config.api_key.strip():
        return GeminiOAuthStatusResponse(
            connected=False,
            provider_id=GEMINI_OAUTH_PROVIDER_ID,
            email="",
            expires_at_unix=0,
            expires_in_seconds=0,
            detail="Not connected.",
            credential_bundle="",
        )
    try:
        credentials = parse_gemini_oauth_bundle(config.api_key)
    except Exception as exc:
        return GeminiOAuthStatusResponse(
            connected=False,
            provider_id=GEMINI_OAUTH_PROVIDER_ID,
            email="",
            expires_at_unix=0,
            expires_in_seconds=0,
            detail=f"Stored Gemini OAuth credentials are invalid: {exc}",
            credential_bundle=config.api_key,
        )
    now = int(time.time())
    expires_in = max(0, credentials.expires_at_unix - now)
    return GeminiOAuthStatusResponse(
        connected=bool(credentials.access_token),
        provider_id=GEMINI_OAUTH_PROVIDER_ID,
        email=credentials.email,
        expires_at_unix=credentials.expires_at_unix,
        expires_in_seconds=expires_in,
        detail="Connected" if expires_in > 0 else "Connected (token may need refresh).",
        credential_bundle=config.api_key,
    )


@router.get("/api/providers/google-gemini/oauth/models", response_model=GeminiOAuthModelsResponse)
async def get_gemini_oauth_models() -> GeminiOAuthModelsResponse:
    settings = await load_settings()
    config = settings.provider_configs.get(GEMINI_OAUTH_PROVIDER_ID)
    if config is None or not config.api_key.strip():
        return GeminiOAuthModelsResponse(connected=False, detail="Gemini OAuth is not connected.")
    try:
        credentials = parse_gemini_oauth_bundle(config.api_key)
        result = await asyncio.to_thread(probe_supported_models, credentials)
    except Exception as exc:
        return GeminiOAuthModelsResponse(connected=True, detail=f"Model probe failed: {exc}")

    refreshed = result.get("credentials")
    if isinstance(refreshed, GeminiOAuthCredentials):
        await _persist_gemini_oauth_credentials(refreshed)

    models: list[ModelOption] = []
    for item in result.get("supported_models", []):
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id", "")).strip()
        if not model_id:
            continue
        label = str(item.get("label", model_id)).strip() or model_id
        token_limit = item.get("token_limit")
        models.append(ModelOption(id=model_id, label=label, token_limit=token_limit if isinstance(token_limit, int) else 1048576))

    unsupported: list[dict[str, str]] = []
    for item in result.get("unsupported_models", []):
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id", "")).strip()
        reason = str(item.get("reason", "")).strip()
        if model_id:
            unsupported.append({"id": model_id, "reason": reason})

    detail = f"Detected {len(models)} supported model(s) for this account." if models else "No supported Gemini OAuth models detected."
    return GeminiOAuthModelsResponse(connected=True, models=models, unsupported_models=unsupported, detail=detail)


@router.get("/api/providers/google-gemini/oauth/start", response_class=HTMLResponse)
async def start_gemini_oauth() -> HTMLResponse:
    return HTMLResponse(content=_gemini_oauth_start_html())


@router.post("/api/providers/google-gemini/oauth/import-local", response_model=GeminiOAuthStatusResponse)
async def import_local_gemini_oauth() -> GeminiOAuthStatusResponse:
    credentials = _load_local_gemini_oauth_credentials()
    if credentials is None:
        raise HTTPException(status_code=422, detail="Could not find local Gemini CLI OAuth credentials. Paste JSON manually.")
    await _persist_gemini_oauth_credentials(credentials)
    now = int(time.time())
    return GeminiOAuthStatusResponse(
        connected=True,
        provider_id=GEMINI_OAUTH_PROVIDER_ID,
        email=credentials.email,
        expires_at_unix=credentials.expires_at_unix,
        expires_in_seconds=max(0, credentials.expires_at_unix - now),
        detail="Imported local Gemini OAuth credentials.",
        credential_bundle=serialize_gemini_oauth_bundle(credentials),
    )


@router.post("/api/providers/google-gemini/oauth/complete", response_model=GeminiOAuthStatusResponse)
async def complete_gemini_oauth(payload: GeminiOAuthCompleteRequest) -> GeminiOAuthStatusResponse:
    credentials = _parse_manual_input(payload.oauth_payload_or_path)
    await _persist_gemini_oauth_credentials(credentials)
    now = int(time.time())
    return GeminiOAuthStatusResponse(
        connected=True,
        provider_id=GEMINI_OAUTH_PROVIDER_ID,
        email=credentials.email,
        expires_at_unix=credentials.expires_at_unix,
        expires_in_seconds=max(0, credentials.expires_at_unix - now),
        detail="Connected",
        credential_bundle=serialize_gemini_oauth_bundle(credentials),
    )


@router.post("/api/providers/google-gemini/oauth/disconnect", response_model=GeminiOAuthStatusResponse)
async def disconnect_gemini_oauth() -> GeminiOAuthStatusResponse:
    settings = await load_settings()
    existing = settings.provider_configs.get(GEMINI_OAUTH_PROVIDER_ID)
    if existing is not None:
        settings.provider_configs[GEMINI_OAUTH_PROVIDER_ID] = existing.model_copy(update={"api_key": ""})
        if settings.active_provider_id == GEMINI_OAUTH_PROVIDER_ID:
            settings.setup_completed = False
        await save_settings(settings)
    return GeminiOAuthStatusResponse(
        connected=False,
        provider_id=GEMINI_OAUTH_PROVIDER_ID,
        email="",
        expires_at_unix=0,
        expires_in_seconds=0,
        detail="Disconnected",
        credential_bundle="",
    )


def _parse_manual_input(raw: str) -> GeminiOAuthCredentials:
    value = str(raw).strip()
    path = Path(value).expanduser()
    if path.exists() and path.is_file():
        return parse_gemini_oauth_bundle(path.read_text(encoding="utf-8"))
    return parse_gemini_oauth_bundle(value)


def _load_local_gemini_oauth_credentials() -> GeminiOAuthCredentials | None:
    candidates = [
        Path.home() / ".gemini" / "oauth_creds.json",
        Path.home() / ".gemini" / "settings.json",
    ]
    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
            return parse_gemini_oauth_bundle(text)
        except Exception:
            continue
    return None


async def _persist_gemini_oauth_credentials(credentials: GeminiOAuthCredentials) -> None:
    settings = await load_settings()
    existing = settings.provider_configs.get(GEMINI_OAUTH_PROVIDER_ID)
    model = existing.model.strip() if existing is not None and existing.model.strip() else "gemini-2.5-flash"
    if existing is None:
        settings.provider_configs[GEMINI_OAUTH_PROVIDER_ID] = ProviderConfig(api_key=serialize_gemini_oauth_bundle(credentials), model=model)
    else:
        settings.provider_configs[GEMINI_OAUTH_PROVIDER_ID] = existing.model_copy(
            update={"api_key": serialize_gemini_oauth_bundle(credentials), "model": model}
        )
    await save_settings(settings)
    await clear_timed_job_auth_alert_provider_id(GEMINI_OAUTH_PROVIDER_ID)


def _gemini_oauth_start_html() -> str:
    return (
        "<!doctype html>"
        "<html><head><meta charset='utf-8'><title>Gemini OAuth</title><style>"
        "body{font-family:ui-sans-serif,Segoe UI,Arial,sans-serif;margin:0;padding:24px;background:#f7f8fa;color:#1d2330;}"
        ".card{max-width:720px;margin:0 auto;padding:20px;border:1px solid #d7dbe3;border-radius:12px;background:#ffffff;}"
        "h1{margin:0 0 12px;font-size:20px;color:#1b4baf;}"
        "p{margin:0 0 12px;line-height:1.5;}"
        "code{background:#f1f3f8;padding:2px 6px;border-radius:6px;}"
        "</style></head><body><div class='card'>"
        "<h1>Gemini OAuth (Unofficial)</h1>"
        "<p>Krill will try to import local Gemini CLI OAuth credentials from <code>~/.gemini/oauth_creds.json</code> or <code>~/.gemini/settings.json</code>.</p>"
        "<p>If auto-import fails, paste OAuth JSON (or file path) into Setup manual completion field.</p>"
        "<p><strong>Caution:</strong> This is an unofficial integration. Use at your own risk.</p>"
        "<p id='status'>Trying local import...</p>"
        "</div><script>"
        "(async()=>{"
        "try{const r=await fetch('/api/providers/google-gemini/oauth/import-local',{method:'POST'});"
        "if(r.ok){document.getElementById('status').textContent='Local import succeeded. Closing...';"
        "try{if(window.opener){window.opener.postMessage({type:'krill-gemini-oauth-finished',ok:true},window.location.origin);}}catch(_e){}"
        "window.setTimeout(function(){window.close();},900);return;}"
        "const p=await r.json().catch(()=>({}));"
        "document.getElementById('status').textContent=(p&&p.detail)||'Local import failed. Use manual completion in Setup.';"
        "}catch(_e){document.getElementById('status').textContent='Local import failed. Use manual completion in Setup.';}"
        "})();"
        "</script></body></html>"
    )
