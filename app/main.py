"""FastAPI entrypoint exposing setup, gateway, chat, and integration APIs."""

import asyncio
import ipaddress
import json
import logging
import os
import secrets
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile, File, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .chat_engine import generate_chat_response
from .config import (
    IntegrationConfig,
    MemoryEntry,
    McpConfig,
    Settings,
    TimedJob,
    create_braindump_snapshot,
    delete_timed_job,
    ensure_settings_file,
    import_braindump_db,
    list_short_term_memories,
    list_timed_jobs,
    load_settings,
    resolve_short_term_memories,
    save_settings,
    upsert_timed_job,
    view_braindump,
)
from .integrations import (
    get_integration,
    get_integration_options,
    get_runtime_integrations,
    is_supported_integration,
)
from .mcps.git_ops import (
    SSH_PRIVATE_PARAM,
    SSH_PUBLIC_PARAM,
    ensure_ssh_keypair,
    get_or_create_ssh_public_key,
    get_workspace_path,
    verify_github_ssh_access,
)
from .mcps.google_services import (
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
from .mcps import get_mcp, get_mcp_options, is_supported_mcp
from .memory_extraction import (
    get_memory_extraction_status,
    register_completed_turn,
    register_user_message_and_maybe_extract,
    start_memory_extraction_worker,
    stop_memory_extraction_worker,
)
from .providers import get_provider, get_provider_options, is_supported_provider
from .providers.resilience import generate_with_retries
from .version import APP_VERSION
from .timed_jobs import get_timed_job_channel_options, start_timed_jobs_worker, stop_timed_jobs_worker
from .timed_jobs import trigger_timed_job_now


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Krill")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
logger = logging.getLogger(__name__)


class ModelOption(BaseModel):
    id: str
    label: str
    token_limit: int


class ProviderOption(BaseModel):
    id: str
    label: str
    api_key_url: str
    models: list[ModelOption]


class VerifyProviderRequest(BaseModel):
    provider_id: str
    model: str
    api_key: str


class VerifyProviderResponse(BaseModel):
    ok: bool
    detail: str


class VerifyMcpRequest(BaseModel):
    mcp_id: str
    params: dict[str, str] = Field(default_factory=dict)


class VerifyMcpResponse(BaseModel):
    ok: bool
    detail: str


class VerifyIntegrationRequest(BaseModel):
    integration_id: str
    params: dict[str, str] = Field(default_factory=dict)


class VerifyIntegrationResponse(BaseModel):
    ok: bool
    detail: str


class IntegrationStatusResponse(BaseModel):
    statuses: dict[str, dict[str, object]]


class GitSshKeyResponse(BaseModel):
    public_key: str


class GitSshVerifyResponse(BaseModel):
    ok: bool
    detail: str


class GoogleOAuthStatusResponse(BaseModel):
    connected: bool
    access_mode: str
    email: str
    has_refresh_token: bool
    scopes: list[str] = Field(default_factory=list)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1, max_length=5000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=5000)
    history: list[ChatTurn] = Field(default_factory=list)
    memory_block: str = Field(default="", max_length=8000)
    provider_id: str = ""
    model: str = ""
    api_key: str = ""
    bot_name: str = Field(default="", max_length=30)
    system_prompt: str = Field(default="", max_length=1000)
    source_channel: str = "gateway"
    source_chat_id: str = ""


class CompactChatRequest(BaseModel):
    history: list[ChatTurn] = Field(default_factory=list)
    target_token_limit: int = Field(default=0, ge=0)
    memory_block: str = Field(default="", max_length=8000)


class CompactChatResponse(BaseModel):
    memory_block: str
    history: list[ChatTurn]
    used_tokens: int | None = None


class ChatStateResponse(BaseModel):
    chats: list[dict[str, object]]
    active_chat_id: str
    daily_token_usage: list[dict[str, object]]


class MemoryUserMessageRequest(BaseModel):
    source_channel: str = "gateway"
    source_chat_id: str = ""


class MemoryTurnCompleteRequest(BaseModel):
    source_channel: str = "gateway"
    source_chat_id: str = ""
    user_message: str = Field(min_length=1, max_length=10000)
    assistant_message: str = Field(default="", max_length=30000)


class ShortTermMemoryResolveItem(BaseModel):
    id: int
    action: Literal["accept", "decline"]
    memory_type: Literal["core", "normal"] = "normal"


class ShortTermMemoryResolveRequest(BaseModel):
    items: list[ShortTermMemoryResolveItem] = Field(default_factory=list)


class MemoryCompactionRequest(BaseModel):
    memory_type: Literal["core", "normal"]


class MemoryCompactionResponse(BaseModel):
    ok: bool = True
    memory_type: Literal["core", "normal"]
    used_tokens: int | None = None
    compacted_count: int = 0
    core_memories: list[dict[str, str]] = Field(default_factory=list)
    normal_memories: list[dict[str, str]] = Field(default_factory=list)


class TimedJobWriteRequest(BaseModel):
    title: str = Field(default="", max_length=120)
    prompt: str = Field(default="", max_length=5000)
    interval: Literal["daily", "weekly", "monthly", "once"] = "daily"
    start_date: str = ""
    time_of_day: str = "00:00"
    timezone: str = ""
    timezone_offset_minutes: int = Field(default=0, ge=-840, le=840)
    enabled: bool = False
    channels: list[str] = Field(default_factory=lambda: ["gateway"])


class TimedJobsResponse(BaseModel):
    jobs: list[TimedJob]
    channels: list[dict[str, object]]


_GOOGLE_OAUTH_STATE_TTL_SECONDS = 600
_google_oauth_states: dict[str, dict[str, object]] = {}
_google_oauth_lock = asyncio.Lock()
_PUBLIC_BASE_URL_ENV = "KRILL_PUBLIC_BASE_URL"


@app.on_event("startup")
async def startup_event() -> None:
    await ensure_settings_file()
    await _rehydrate_git_ssh_material()
    await start_memory_extraction_worker()
    await start_timed_jobs_worker()
    for integration in get_runtime_integrations():
        integration.start()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await stop_memory_extraction_worker()
    await stop_timed_jobs_worker()
    for integration in get_runtime_integrations():
        await integration.stop()


@app.get("/", response_class=FileResponse)
async def read_root() -> FileResponse:
    settings = await load_settings()
    page = "gateway.html" if _is_setup_complete(settings) else "setup.html"
    return FileResponse(STATIC_DIR / page)


@app.get("/setup", response_class=FileResponse)
async def read_setup() -> FileResponse:
    return FileResponse(STATIC_DIR / "setup.html")


@app.get("/favicon.ico", response_class=FileResponse)
async def read_favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "img" / "krill_icon.png")


@app.get("/gateway")
async def read_gateway():
    settings = await load_settings()

    if not _is_setup_complete(settings):
        return RedirectResponse(url="/setup", status_code=307)

    return FileResponse(STATIC_DIR / "gateway.html")


@app.get("/api/braindump/download")
async def download_braindump(background_tasks: BackgroundTasks):
    # We create a temporary snapshot to ensure consistency and avoid locking the main DB
    fd, tmp_path_str = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    tmp_path = Path(tmp_path_str)
    
    try:
        await create_braindump_snapshot(tmp_path)
        # Note: In a real production app we'd need a cleaner way to delete this temp file after send.
        # For Krill, we'll return it and let the OS/Task handle it if possible, 
        # but FileResponse doesn't delete automatically.
        background_tasks.add_task(tmp_path.unlink, missing_ok=True)
        return FileResponse(
            tmp_path, 
            media_type="application/x-sqlite3", 
            filename="braindump.db",
            background=background_tasks,
        )
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Download failed: {exc}")


@app.post("/api/braindump/import")
async def import_braindump(file: UploadFile = File(...)):
    fd, tmp_path_str = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    tmp_path = Path(tmp_path_str)
    
    try:
        content = await file.read()
        tmp_path.write_bytes(content)
        await import_braindump_db(tmp_path)
        await _rehydrate_git_ssh_material()
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}")
    finally:
        tmp_path.unlink(missing_ok=True)


@app.get("/api/braindump/view")
async def get_braindump_view() -> dict[str, object]:
    return await view_braindump(show_secrets=True)


@app.get("/api/settings", response_model=Settings)
async def get_settings() -> Settings:
    return await load_settings()


@app.get("/api/version")
async def get_version() -> dict[str, str]:
    return {"version": APP_VERSION}


@app.get("/api/chat/state", response_model=ChatStateResponse)
async def get_chat_state() -> ChatStateResponse:
    settings = await load_settings()
    return ChatStateResponse(
        chats=[chat.model_dump() for chat in settings.chats],
        active_chat_id=settings.active_chat_id,
        daily_token_usage=[entry.model_dump() for entry in settings.daily_token_usage],
    )


@app.get("/api/providers", response_model=list[ProviderOption])
async def get_providers() -> list[dict[str, object]]:
    return get_provider_options()


@app.post("/api/settings", response_model=Settings)
async def update_settings(settings: Settings) -> Settings:
    existing = await load_settings()
    settings = settings.model_copy(update={"user_message_count": existing.user_message_count})
    _merge_google_managed_oauth_params(existing, settings)
    _merge_git_managed_ssh_params(existing, settings)
    _validate_settings_payload(settings)
    return await save_settings(settings)


@app.post("/api/memory/user-message")
async def register_memory_user_message(payload: MemoryUserMessageRequest) -> dict[str, object]:
    triggered = await register_user_message_and_maybe_extract(
        source_channel=payload.source_channel,
        source_chat_id=payload.source_chat_id,
    )
    return {"ok": True, "triggered": triggered}


@app.post("/api/memory/turn-complete")
async def register_memory_turn_complete(payload: MemoryTurnCompleteRequest) -> dict[str, object]:
    await register_completed_turn(
        source_channel=payload.source_channel,
        source_chat_id=payload.source_chat_id,
        user_message=payload.user_message,
        assistant_message=payload.assistant_message,
    )
    return {"ok": True}


@app.get("/api/memory/short-term")
async def get_short_term_memory() -> dict[str, object]:
    items = await list_short_term_memories(status="pending")
    status = get_memory_extraction_status()
    return {
        "ok": True,
        "count": len(items),
        "items": [item.model_dump() for item in items],
        "extraction": status,
    }


@app.post("/api/memory/short-term/resolve")
async def resolve_short_term_memory(payload: ShortTermMemoryResolveRequest) -> dict[str, object]:
    changed = await resolve_short_term_memories([item.model_dump() for item in payload.items])
    return {"ok": True, "changed": changed}


@app.post("/api/memory/compact", response_model=MemoryCompactionResponse)
async def compact_memories(payload: MemoryCompactionRequest) -> MemoryCompactionResponse:
    settings = await load_settings()
    if not _is_setup_complete(settings):
        raise HTTPException(status_code=422, detail="Setup is not complete.")

    active_provider_id = settings.active_provider_id
    provider_config = settings.provider_configs.get(active_provider_id)
    if provider_config is None:
        raise HTTPException(status_code=422, detail="Active provider is not configured.")

    provider = get_provider(active_provider_id)
    if provider is None:
        raise HTTPException(status_code=422, detail="Active provider is unavailable.")

    source_memories = settings.core_memories if payload.memory_type == "core" else settings.normal_memories
    compactable = [entry for entry in source_memories if entry.content.strip()]
    if not compactable:
        raise HTTPException(status_code=422, detail="No memories available to compact for this type.")

    source_lines, required_timestamps, _ = _build_memory_compaction_source(compactable)
    prompt = _build_memory_compaction_prompt(payload.memory_type, source_lines, required_timestamps)

    try:
        compacted_text, used_tokens = await generate_with_retries(
            provider=provider,
            prompt=prompt,
            system_prompt=_memory_compaction_system_prompt(),
            model=provider_config.model,
            api_key=provider_config.api_key,
            history=[],
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Memory compaction failed: {exc}") from exc

    compacted_memory = str(compacted_text).strip()
    if not compacted_memory:
        raise HTTPException(status_code=422, detail="Memory compaction failed: Provider returned empty compacted memory.")

    compacted_entry = MemoryEntry(content=compacted_memory, created_at=datetime.now(timezone.utc).isoformat())
    if payload.memory_type == "core":
        settings.core_memories = [compacted_entry]
    else:
        settings.normal_memories = [compacted_entry]

    persisted = await save_settings(settings)
    return MemoryCompactionResponse(
        memory_type=payload.memory_type,
        used_tokens=used_tokens,
        compacted_count=len(compactable),
        core_memories=[entry.model_dump() for entry in persisted.core_memories],
        normal_memories=[entry.model_dump() for entry in persisted.normal_memories],
    )


@app.post("/api/providers/verify", response_model=VerifyProviderResponse)
async def verify_provider(payload: VerifyProviderRequest) -> VerifyProviderResponse:
    if not is_supported_provider(payload.provider_id):
        raise HTTPException(status_code=422, detail="Unsupported LLM provider.")

    if not payload.model.strip():
        raise HTTPException(status_code=422, detail="Model is required.")

    provider = get_provider(payload.provider_id)
    if provider is None:
        raise HTTPException(status_code=422, detail="Provider not found.")

    ok, detail = await provider.verify(payload.model, payload.api_key)
    if not ok:
        raise HTTPException(status_code=422, detail=detail)

    return VerifyProviderResponse(ok=True, detail=detail)


@app.get("/api/mcps")
async def get_mcps() -> list[dict[str, object]]:
    return get_mcp_options()


@app.post("/api/mcps/verify", response_model=VerifyMcpResponse)
async def verify_mcp(payload: VerifyMcpRequest) -> VerifyMcpResponse:
    if not is_supported_mcp(payload.mcp_id):
        raise HTTPException(status_code=422, detail="Unsupported MCP.")

    mcp = get_mcp(payload.mcp_id)
    if mcp is None:
        raise HTTPException(status_code=422, detail="MCP not found.")

    settings = await load_settings()
    persisted_config = settings.mcp_configs.get(payload.mcp_id) or McpConfig()
    merged_params = dict(persisted_config.params)
    merged_params.update(payload.params)

    ok, detail = await mcp.verify(merged_params)
    if not ok:
        raise HTTPException(status_code=422, detail=detail)

    return VerifyMcpResponse(ok=True, detail=detail)


@app.get("/api/mcps/google/oauth/status", response_model=GoogleOAuthStatusResponse)
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


@app.get("/api/mcps/google/oauth/start", response_class=HTMLResponse)
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


@app.get("/api/mcps/google/oauth/callback", response_class=HTMLResponse, name="google_oauth_callback")
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


@app.post("/api/mcps/google/oauth/disconnect", response_model=GoogleOAuthStatusResponse)
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


@app.get("/api/integrations")
async def get_integrations() -> list[dict[str, object]]:
    return get_integration_options()


@app.post("/api/integrations/verify", response_model=VerifyIntegrationResponse)
async def verify_integration(payload: VerifyIntegrationRequest) -> VerifyIntegrationResponse:
    if not is_supported_integration(payload.integration_id):
        raise HTTPException(status_code=422, detail="Unsupported integration.")

    integration = get_integration(payload.integration_id)
    if integration is None:
        raise HTTPException(status_code=422, detail="Integration not found.")

    ok, detail = await integration.verify(payload.params)
    if not ok:
        raise HTTPException(status_code=422, detail=detail)

    return VerifyIntegrationResponse(ok=True, detail=detail)


@app.get("/api/integrations/status", response_model=IntegrationStatusResponse)
async def get_integration_status() -> IntegrationStatusResponse:
    settings = await load_settings()
    telegram_config = settings.integration_configs.get("telegram") or IntegrationConfig()
    token_value = telegram_config.params.get("bot_token", "")
    token_configured = isinstance(token_value, str) and bool(token_value.strip())
    owner_user_id = settings.telegram_state.owner_user_id.strip()
    owner_chat_id = settings.telegram_state.owner_chat_id.strip()

    return IntegrationStatusResponse(
        statuses={
            "telegram": {
                "enabled": bool(telegram_config.enabled),
                "token_configured": token_configured,
                "owner_user_id": owner_user_id,
                "owner_chat_id": owner_chat_id,
                "owner_bound": bool(owner_user_id),
            }
        }
    )


@app.get("/api/timed-jobs", response_model=TimedJobsResponse)
async def get_timed_jobs() -> TimedJobsResponse:
    settings = await load_settings()
    jobs = await list_timed_jobs()
    channels = get_timed_job_channel_options(settings)
    return TimedJobsResponse(jobs=jobs, channels=channels)


@app.post("/api/timed-jobs", response_model=TimedJob)
async def create_timed_job(payload: TimedJobWriteRequest) -> TimedJob:
    if not payload.prompt.strip():
        raise HTTPException(status_code=422, detail="Timed job prompt is required.")
    if not payload.channels:
        raise HTTPException(status_code=422, detail="At least one output channel is required.")
    return await upsert_timed_job(payload.model_dump())


@app.put("/api/timed-jobs/{timed_job_id}", response_model=TimedJob)
async def update_timed_job(timed_job_id: str, payload: TimedJobWriteRequest) -> TimedJob:
    if not timed_job_id.strip():
        raise HTTPException(status_code=422, detail="Timed job id is required.")
    if not payload.prompt.strip():
        raise HTTPException(status_code=422, detail="Timed job prompt is required.")
    if not payload.channels:
        raise HTTPException(status_code=422, detail="At least one output channel is required.")
    return await upsert_timed_job(payload.model_dump(), timed_job_id=timed_job_id)


@app.delete("/api/timed-jobs/{timed_job_id}")
async def remove_timed_job(timed_job_id: str) -> dict[str, object]:
    deleted = await delete_timed_job(timed_job_id)
    return {"ok": True, "deleted": deleted}


@app.post("/api/timed-jobs/{timed_job_id}/trigger")
async def trigger_timed_job(timed_job_id: str) -> dict[str, object]:
    if not timed_job_id.strip():
        raise HTTPException(status_code=422, detail="Timed job id is required.")
    found = await trigger_timed_job_now(timed_job_id)
    if not found:
        raise HTTPException(status_code=404, detail="Timed job not found.")
    return {"ok": True}


@app.get("/api/mcps/git/ssh-key", response_model=GitSshKeyResponse)
async def get_git_ssh_key() -> GitSshKeyResponse:
    settings = await load_settings()
    git_mcp_config = settings.mcp_configs.get("git_ops") or McpConfig()
    workspace = get_workspace_path()
    private_key, public_key = await get_or_create_ssh_public_key(git_mcp_config.params, workspace)

    updated_params = dict(git_mcp_config.params)
    updated_params[SSH_PRIVATE_PARAM] = private_key
    updated_params[SSH_PUBLIC_PARAM] = public_key
    settings.mcp_configs["git_ops"] = McpConfig(enabled=git_mcp_config.enabled, params=updated_params)
    await save_settings(settings)

    return GitSshKeyResponse(public_key=public_key)


@app.post("/api/mcps/git/verify-ssh", response_model=GitSshVerifyResponse)
async def verify_git_ssh() -> GitSshVerifyResponse:
    settings = await load_settings()
    git_mcp_config = settings.mcp_configs.get("git_ops") or McpConfig()
    workspace = get_workspace_path()
    private_key, public_key = await get_or_create_ssh_public_key(git_mcp_config.params, workspace)

    updated_params = dict(git_mcp_config.params)
    updated_params[SSH_PRIVATE_PARAM] = private_key
    updated_params[SSH_PUBLIC_PARAM] = public_key
    settings.mcp_configs["git_ops"] = McpConfig(enabled=git_mcp_config.enabled, params=updated_params)
    await save_settings(settings)

    ok, detail = await verify_github_ssh_access(workspace, private_key)
    if not ok:
        raise HTTPException(status_code=422, detail=detail)
    return GitSshVerifyResponse(ok=True, detail=detail)


@app.post("/api/reset", response_model=Settings)
async def reset_settings() -> Settings:
    defaults = Settings()
    return await save_settings(defaults)


@app.post("/api/chat/stream")
async def chat_stream(payload: ChatRequest) -> StreamingResponse:
    settings = await load_settings()
    if not _is_setup_complete(settings):
        raise HTTPException(status_code=422, detail="Setup is not complete.")
    try:
        await register_user_message_and_maybe_extract(
            source_channel=payload.source_channel,
            source_chat_id=payload.source_chat_id,
        )
    except Exception:
        # Memory extraction triggering must not block chat.
        pass
    history = [turn.model_dump() for turn in payload.history]

    async def event_stream():
        try:
            queue: asyncio.Queue[str | None] = asyncio.Queue()
            orchestration_holder: dict[str, object] = {}

            async def _emit_tool_step(step: object) -> None:
                event_payload: dict[str, object]
                if isinstance(step, dict):
                    event_payload = {str(key): value for key, value in step.items()}
                else:
                    event_payload = {"system_type": "tool_step", "content": str(step)}
                await queue.put(_sse("tool_step", event_payload))

            async def run_orchestration() -> None:
                try:
                    orchestration_holder["result"] = await generate_chat_response(
                        settings=settings,
                        message=payload.message,
                        history=history,
                        memory_block=payload.memory_block,
                        provider_id=payload.provider_id,
                        model=payload.model,
                        api_key=payload.api_key,
                        bot_name=payload.bot_name,
                        system_prompt=payload.system_prompt,
                        source_channel=payload.source_channel,
                        source_chat_id=payload.source_chat_id,
                        on_tool_step=_emit_tool_step,
                    )
                except Exception as exc:
                    orchestration_holder["error"] = exc
                finally:
                    await queue.put(None)

            orchestration_task = asyncio.create_task(run_orchestration())

            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item

            await orchestration_task

            if "error" in orchestration_holder:
                yield _sse("error", {"detail": str(orchestration_holder["error"])})
                return

            orchestration_payload = orchestration_holder.get("result")
            if not (isinstance(orchestration_payload, tuple) and len(orchestration_payload) == 2):
                yield _sse("error", {"detail": "Missing orchestration result."})
                return

            orchestration, token_limit = orchestration_payload
            if not isinstance(orchestration, dict):
                yield _sse("error", {"detail": "Invalid orchestration payload."})
                return

            text = str(orchestration.get("text", ""))
            used_tokens = orchestration.get("used_tokens")
            used_mcp_tools = orchestration.get("used_mcp_tools", [])
            system_trace_messages = orchestration.get("system_trace_messages", [])

            used_value = used_tokens if isinstance(used_tokens, int) else 0
            used_percent = round((used_value / token_limit) * 100, 2) if token_limit else 0
            yield _sse(
                "meta",
                {
                    "used_tokens": used_value,
                    "token_limit": token_limit,
                    "used_percent": used_percent,
                    "used_mcp_tools": used_mcp_tools,
                    "system_trace_messages": system_trace_messages,
                },
            )

            for chunk in _chunk_text(str(text)):
                yield _sse("token", {"text": chunk})
                await asyncio.sleep(0.01)

            yield _sse("done", {"ok": True})
        except Exception as exc:
            logger.exception("Unhandled chat stream error")
            yield _sse("error", {"detail": f"Chat stream failed: {exc}"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/chat/compact", response_model=CompactChatResponse)
async def compact_chat(payload: CompactChatRequest) -> CompactChatResponse:
    settings = await load_settings()
    if not _is_setup_complete(settings):
        raise HTTPException(status_code=422, detail="Setup is not complete.")

    active_provider_id = settings.active_provider_id
    provider_config = settings.provider_configs.get(active_provider_id)
    if provider_config is None:
        raise HTTPException(status_code=422, detail="Active provider is not configured.")

    provider = get_provider(active_provider_id)
    if provider is None:
        raise HTTPException(status_code=422, detail="Active provider is unavailable.")

    incoming_history = [turn.model_dump() for turn in payload.history]
    if not incoming_history and not payload.memory_block.strip():
        return CompactChatResponse(memory_block="", history=[])

    try:
        compacted_text, used_tokens = await generate_with_retries(
            provider=provider,
            prompt=_build_compaction_prompt(payload.memory_block, payload.target_token_limit),
            system_prompt=_compaction_system_prompt(),
            model=provider_config.model,
            api_key=provider_config.api_key,
            history=incoming_history,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Compaction failed: {exc}") from exc

    memory_block = compacted_text.strip()
    if not memory_block:
        raise HTTPException(status_code=422, detail="Compaction failed: Provider returned empty compact memory.")

    return CompactChatResponse(memory_block=memory_block, history=[], used_tokens=used_tokens)


def _validate_provider_configs(settings: Settings) -> None:
    if settings.active_provider_id and settings.active_provider_id not in settings.provider_configs:
        raise HTTPException(status_code=422, detail="Active provider must exist in provider configs.")

    for provider_id, provider_config in settings.provider_configs.items():
        if not is_supported_provider(provider_id):
            raise HTTPException(status_code=422, detail=f"Unsupported LLM provider: {provider_id}")

        if not provider_config.model.strip():
            raise HTTPException(status_code=422, detail=f"Model is required for provider '{provider_id}'.")


def _validate_settings_payload(settings: Settings) -> None:
    _validate_provider_configs(settings)
    _validate_mcp_configs(settings)
    _validate_integration_configs(settings)

    if settings.setup_completed and not _can_complete_setup(settings):
        raise HTTPException(
            status_code=422,
            detail="Setup cannot be marked complete without active provider, model, and API key.",
        )


def _can_complete_setup(settings: Settings) -> bool:
    if not settings.active_provider_id:
        return False

    active_config = settings.provider_configs.get(settings.active_provider_id)
    if active_config is None:
        return False

    if not active_config.api_key.strip():
        return False

    if not active_config.model.strip():
        return False

    return True


def _validate_mcp_configs(settings: Settings) -> None:
    for mcp_id, mcp_config in settings.mcp_configs.items():
        if not is_supported_mcp(mcp_id):
            raise HTTPException(status_code=422, detail=f"Unsupported MCP: {mcp_id}")

        mcp = get_mcp(mcp_id)
        if mcp is None:
            raise HTTPException(status_code=422, detail=f"MCP unavailable: {mcp_id}")


def _merge_google_managed_oauth_params(existing: Settings, incoming: Settings) -> None:
    existing_google = existing.mcp_configs.get(GOOGLE_MCP_ID)
    incoming_google = incoming.mcp_configs.get(GOOGLE_MCP_ID)
    if incoming_google is None:
        if existing_google is not None:
            incoming.mcp_configs[GOOGLE_MCP_ID] = existing_google
        return

    if existing_google is None:
        return

    existing_params = dict(existing_google.params)
    merged_params = dict(incoming_google.params)

    existing_client_id = str(existing_params.get(CLIENT_ID_PARAM, "")).strip()
    incoming_client_id = str(merged_params.get(CLIENT_ID_PARAM, "")).strip()
    existing_client_secret = str(existing_params.get(CLIENT_SECRET_PARAM, "")).strip()
    incoming_client_secret = str(merged_params.get(CLIENT_SECRET_PARAM, "")).strip()
    credentials_changed = (
        (incoming_client_id and incoming_client_id != existing_client_id)
        or (incoming_client_secret and incoming_client_secret != existing_client_secret)
    )

    managed_keys = (
        ACCESS_TOKEN_PARAM,
        REFRESH_TOKEN_PARAM,
        TOKEN_EXPIRY_PARAM,
        SCOPES_PARAM,
        CONNECTED_EMAIL_PARAM,
    )

    if credentials_changed:
        for key in managed_keys:
            merged_params.pop(key, None)
    else:
        for key in managed_keys:
            existing_value = str(existing_params.get(key, "")).strip()
            if existing_value:
                merged_params[key] = existing_value

    incoming.mcp_configs[GOOGLE_MCP_ID] = McpConfig(enabled=incoming_google.enabled, params=merged_params)


def _merge_git_managed_ssh_params(existing: Settings, incoming: Settings) -> None:
    existing_git = existing.mcp_configs.get("git_ops")
    incoming_git = incoming.mcp_configs.get("git_ops")
    if incoming_git is None:
        if existing_git is not None:
            incoming.mcp_configs["git_ops"] = existing_git
        return

    if existing_git is None:
        return

    existing_params = dict(existing_git.params)
    merged_params = dict(incoming_git.params)

    for managed_key in (SSH_PRIVATE_PARAM, SSH_PUBLIC_PARAM):
        incoming_value = str(merged_params.get(managed_key, "") or "").strip()
        existing_value = str(existing_params.get(managed_key, "") or "").strip()
        if incoming_value:
            continue
        if existing_value:
            merged_params[managed_key] = existing_value

    incoming.mcp_configs["git_ops"] = McpConfig(enabled=incoming_git.enabled, params=merged_params)


async def _rehydrate_git_ssh_material() -> None:
    settings = await load_settings()
    git_config = settings.mcp_configs.get("git_ops")
    if git_config is None:
        return

    params = dict(git_config.params)
    configured_private = str(params.get(SSH_PRIVATE_PARAM, "") or "").strip()
    configured_public = str(params.get(SSH_PUBLIC_PARAM, "") or "").strip()
    if not configured_private and not configured_public:
        return

    workspace = get_workspace_path()
    private_key, public_key = await ensure_ssh_keypair(params, workspace)

    if private_key == configured_private and public_key == configured_public:
        return

    params[SSH_PRIVATE_PARAM] = private_key
    params[SSH_PUBLIC_PARAM] = public_key
    settings.mcp_configs["git_ops"] = McpConfig(enabled=git_config.enabled, params=params)
    await save_settings(settings)


def _validate_integration_configs(settings: Settings) -> None:
    for integration_id in settings.integration_configs.keys():
        if not is_supported_integration(integration_id):
            raise HTTPException(status_code=422, detail=f"Unsupported integration: {integration_id}")


def _is_setup_complete(settings: Settings) -> bool:
    if not settings.setup_completed:
        return False

    return _can_complete_setup(settings)


def _sse(event_name: str, payload: dict[str, object]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload, default=str)}\n\n"


def _compaction_system_prompt() -> str:
    return (
        "You compress chat history into a durable memory block. "
        "Keep only facts that matter for future turns: user preferences, goals, constraints, "
        "decisions, unresolved items, and concrete context. "
        "Do not invent facts. Keep compact wording and avoid filler."
    )


def _build_compaction_prompt(existing_memory: str, target_token_limit: int) -> str:
    lines = [
        "Create an updated compact memory block from the conversation history.",
        "Return plain text only.",
        "Use sections exactly in this order:",
        "1) User profile and preferences",
        "2) Confirmed facts and decisions",
        "3) Open tasks and pending questions",
        "4) Important style constraints",
        "Keep it concise and dense.",
    ]

    if target_token_limit > 0:
        lines.append(
            f"This memory will support a model with {target_token_limit} token context, so keep memory lean."
        )

    if existing_memory.strip():
        lines.append("Merge and refresh this previous memory block, keeping only still-relevant points:")
        lines.append(existing_memory.strip())

    return "\n".join(lines)


def _memory_compaction_system_prompt() -> str:
    return (
        "You are a lossless memory compactor. Compress memory text aggressively while preserving every concrete fact. "
        "Never invent information. Remove duplicates only when the factual meaning is identical. "
        "Preserve timestamp provenance by retaining all timestamp markers exactly as provided."
    )


def _build_memory_compaction_source(memories: list[MemoryEntry]) -> tuple[list[str], list[str], dict[str, str]]:
    lines: list[str] = []
    required_timestamps: list[str] = []
    by_marker: dict[str, str] = {}

    for entry in memories:
        timestamp = entry.created_at.strip() or "unknown"
        marker = f"[ts:{timestamp}]"
        required_timestamps.append(marker)
        source_line = f"{marker} {entry.content.strip()}"
        lines.append(source_line)
        by_marker[marker] = source_line

    return lines, required_timestamps, by_marker


def _build_memory_compaction_prompt(
    memory_type: Literal["core", "normal"],
    source_lines: list[str],
    required_timestamps: list[str],
) -> str:

    memory_label = "core" if memory_type == "core" else "normal"
    prompt_lines = [
        f"Compact the following {memory_label} memories into one dense memory entry.",
        "Goals:",
        "- Keep every concrete fact.",
        "- Remove duplicate statements.",
        "- Minimize token usage as much as possible.",
        "- Preserve timestamp provenance where possible by keeping timestamp markers in output.",
        "Output rules:",
        "- Return plain text only (no markdown code fences).",
        "- Keep timestamp markers when possible, but prioritize a useful compacted memory.",
        "- Keep wording compact and structured.",
        "Source memories:",
        *source_lines,
    ]
    return "\n".join(prompt_lines)


def _chunk_text(text: str) -> list[str]:
    tokens = text.split(" ")

    if len(tokens) <= 1:
        return [text]

    return [f"{token} " for token in tokens[:-1]] + [tokens[-1]]


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
        + "</p><p><a href='/gateway'>Return to Gateway</a></p></div>"
        "<script>window.setTimeout(function(){window.close();},1200);</script>"
        "</body></html>"
    )


def _google_oauth_start_html(auth_url: str) -> str:
    raw_url = str(auth_url)
    safe_url = raw_url.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    script_url = json.dumps(raw_url)
    return (
        "<!doctype html>"
        "<html><head><meta charset='utf-8'><title>Google Login</title><style>"
        "body{font-family:ui-sans-serif,Segoe UI,Arial,sans-serif;margin:0;padding:24px;background:#f7f8fa;color:#1d2330;}"
        ".card{max-width:560px;margin:0 auto;padding:20px;border:1px solid #d7dbe3;border-radius:12px;background:#ffffff;}"
        "h1{margin:0 0 12px;font-size:20px;color:#1b4baf;}"
        "p{margin:0 0 16px;line-height:1.5;}"
        "a{color:#1b4baf;text-decoration:none;}"
        "</style></head><body><div class='card'><h1>Opening Google login...</h1>"
        "<p>If you are not redirected automatically, click the link below.</p>"
        "<p><a id='oauth-link' href='"
        + safe_url
        + "'>Continue to Google OAuth</a></p></div>"
        "<script>window.location.replace("
        + script_url
        + ");</script>"
        "</body></html>"
    )
