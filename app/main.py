"""FastAPI entrypoint exposing setup, gateway, chat, and integration APIs."""

import asyncio
import base64
import binascii
import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile, File, Request
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .chat_engine import generate_chat_response
from .config import (
    ChatSession,
    DailyTokenUsage,
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
    load_chat_state,
    load_settings,
    resolve_short_term_memories,
    save_chat_state,
    save_settings,
    upsert_timed_job,
    view_braindump,
    ChatMessage,
    _server_timezone,
)

from .integrations import (
    get_integration,
    get_integration_options,
    get_runtime_integrations,
    is_supported_integration,
)
from .integrations.whatsapp.sidecar_manager import connect as whatsapp_connect
from .integrations.whatsapp.sidecar_manager import list_contacts as whatsapp_list_contacts
from .integrations.whatsapp.sidecar_manager import status as whatsapp_status
from .integrations.chat_runtime import ensure_runtime_context_seed
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
    normalize_google_access_mode,
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
from .auth import is_bootstrap_required, resolve_session_from_request
from .routers.auth import router as auth_router
from .routers.gemini_oauth import router as gemini_oauth_router
from .providers.vision import analyze_image
from .providers.resilience import generate_with_retries
from .routers.google_oauth import router as google_oauth_router
from .routers.openai_oauth import router as openai_oauth_router
from .usage import add_daily_usage
from .version import APP_VERSION
from .timed_jobs import get_timed_job_channel_options, start_timed_jobs_worker, stop_timed_jobs_worker
from .timed_jobs import get_timed_job_auth_alert_provider_ids
from .timed_jobs import trigger_timed_job_now


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

if os.name == "nt":
    try:
        policy = asyncio.get_event_loop_policy()
        proactor_policy = getattr(asyncio, "WindowsProactorEventLoopPolicy", None)
        if proactor_policy is not None and not isinstance(policy, proactor_policy):
            asyncio.set_event_loop_policy(proactor_policy())
    except Exception:
        pass

app = FastAPI(title="Krill")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(auth_router)
app.include_router(gemini_oauth_router)
app.include_router(google_oauth_router)
app.include_router(openai_oauth_router)
logger = logging.getLogger(__name__)


@app.middleware("http")
async def require_authentication(request: Request, call_next):
    path = request.url.path or "/"

    if await is_bootstrap_required():
        if path == "/auth/setup" or path.startswith("/api/auth/"):
            return await call_next(request)
        if path == "/login":
            return RedirectResponse(url="/auth/setup", status_code=307)
        if path.startswith("/api/"):
            return JSONResponse(status_code=428, content={"detail": "Authentication bootstrap is required."})
        return RedirectResponse(url="/auth/setup", status_code=307)

    if path in {"/login", "/favicon.ico"} or path.startswith("/api/auth/"):
        return await call_next(request)

    session = await resolve_session_from_request(request)
    if session is None:
        if path.startswith("/api/"):
            return JSONResponse(status_code=401, content={"detail": "Not authenticated."})
        return RedirectResponse(url="/login", status_code=307)

    request.state.auth_user_id = session["user_id"]
    request.state.auth_username = session["username"]
    return await call_next(request)


class ModelOption(BaseModel):
    id: str
    label: str
    token_limit: int


class ProviderOption(BaseModel):
    id: str
    label: str
    api_key_url: str
    auth_mode: str = "api_key"
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


class ActiveProviderModelRequest(BaseModel):
    provider_id: str
    model_id: str


class IntegrationStatusResponse(BaseModel):
    statuses: dict[str, dict[str, object]]


class GitSshKeyResponse(BaseModel):
    public_key: str


class GitSshVerifyResponse(BaseModel):
    ok: bool
    detail: str


class WhatsAppStatusResponse(BaseModel):
    connected: bool
    state: str
    qr_data_url: str = ""


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


class ChatEnqueueRequest(BaseModel):
    chat_id: str = Field(min_length=1)
    message: str = Field(default="", max_length=5000)
    provider_id: str = ""
    model: str = ""
    api_key: str = ""
    bot_name: str = Field(default="", max_length=30)
    system_prompt: str = Field(default="", max_length=1000)
    image: dict[str, str] | None = None


class ChatStopRequest(BaseModel):
    chat_id: str = Field(min_length=1)


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


class ChatStateWriteRequest(BaseModel):
    chats: list[ChatSession] = Field(default_factory=list)
    active_chat_id: str = ""
    daily_token_usage: list[DailyTokenUsage] = Field(default_factory=list)


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
    interval: Literal[
        "daily",
        "weekly",
        "monthly",
        "once",
        "hourly",
        "every_30_min",
        "every_15_min",
        "every_10_min",
        "every_5_min",
    ] = "daily"
    start_date: str = ""
    time_of_day: str = "00:00"
    enabled: bool = False
    output_decision_enabled: bool = False
    channels: list[str] = Field(default_factory=lambda: ["gateway"])


class TimedJobsResponse(BaseModel):
    jobs: list[TimedJob]
    channels: list[dict[str, object]]


class TimedJobAuthAlertStatusResponse(BaseModel):
    active: bool
    provider_ids: list[str] = Field(default_factory=list)
    detail: str = ""


_gateway_chat_lock = asyncio.Lock()
_gateway_chat_queues: dict[str, list[dict[str, Any]]] = {}
_gateway_chat_tasks: dict[str, asyncio.Task[None]] = {}
_gateway_chat_active_request_ids: dict[str, str] = {}


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
    async with _gateway_chat_lock:
        tasks = list(_gateway_chat_tasks.values())
        _gateway_chat_tasks.clear()
        _gateway_chat_queues.clear()
        _gateway_chat_active_request_ids.clear()
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass
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
async def get_version() -> dict[str, object]:
    from datetime import datetime, timedelta, timezone
    now_utc = datetime.now(timezone.utc)
    name, tz = _server_timezone()
    offset = tz.utcoffset(now_utc.astimezone(tz)) or timedelta(minutes=0)
    offset_minutes = int(offset.total_seconds() // 60)
    return {
        "version": APP_VERSION,
        "server_timezone": name,
        "server_timezone_offset": offset_minutes,
    }



@app.get("/api/chat/state", response_model=ChatStateResponse)
async def get_chat_state() -> ChatStateResponse:
    settings = await load_chat_state()
    return ChatStateResponse(
        chats=[chat.model_dump() for chat in settings.chats],
        active_chat_id=settings.active_chat_id,
        daily_token_usage=[entry.model_dump() for entry in settings.daily_token_usage],
    )


@app.post("/api/chat/state", response_model=ChatStateResponse)
async def update_chat_state(payload: ChatStateWriteRequest) -> ChatStateResponse:
    persisted = await save_chat_state(payload.chats, payload.active_chat_id, payload.daily_token_usage)
    return ChatStateResponse(
        chats=[chat.model_dump() for chat in persisted.chats],
        active_chat_id=persisted.active_chat_id,
        daily_token_usage=[entry.model_dump() for entry in persisted.daily_token_usage],
    )


@app.post("/api/chat/enqueue")
async def enqueue_chat(payload: ChatEnqueueRequest) -> dict[str, object]:
    settings = await load_settings()
    if not _is_setup_complete(settings):
        raise HTTPException(status_code=422, detail="Setup is not complete.")

    chat_id = payload.chat_id.strip()
    target_chat = next((chat for chat in settings.chats if chat.id == chat_id), None)
    if target_chat is None:
        raise HTTPException(status_code=404, detail="Chat not found.")

    message_text = payload.message.strip()
    image_payload = _normalize_enqueued_image(payload.image)
    if not message_text and image_payload is None:
        raise HTTPException(status_code=422, detail="Either message text or one image is required.")

    user_content = message_text
    if image_payload is not None:
        if user_content:
            user_content = f"{user_content}\n\n[Image attached]"
        else:
            user_content = "[Image attached]"

    request_id = str(uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    ensure_runtime_context_seed(target_chat, settings)
    target_chat.messages.append(ChatMessage(role="user", content=user_content, timestamp=now_iso))
    target_chat.messages.append(
        ChatMessage(role="assistant", content="", timestamp=now_iso, request_id=request_id, status="queued")
    )
    settings.active_chat_id = chat_id
    await save_chat_state(settings.chats, settings.active_chat_id, settings.daily_token_usage)

    try:
        await register_user_message_and_maybe_extract(source_channel="gateway", source_chat_id=chat_id)
    except Exception:
        pass

    await _enqueue_gateway_chat_job(
        {
            "chat_id": chat_id,
            "request_id": request_id,
            "message": message_text,
            "image": image_payload,
            "provider_id": payload.provider_id.strip(),
            "model": payload.model.strip(),
            "api_key": payload.api_key,
            "bot_name": payload.bot_name,
            "system_prompt": payload.system_prompt,
        }
    )
    return {"ok": True, "request_id": request_id}


def _normalize_enqueued_image(raw: dict[str, str] | None) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    mime_type = str(raw.get("mime_type", "")).strip().lower()
    content_base64 = str(raw.get("content_base64", "")).strip()
    file_name = str(raw.get("file_name", "")).strip()
    if not mime_type and not content_base64:
        return None
    if not mime_type.startswith("image/"):
        raise HTTPException(status_code=422, detail="Only image attachments are supported.")
    if not content_base64:
        raise HTTPException(status_code=422, detail="Image content is missing.")
    try:
        image_bytes = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Image payload is not valid base64.") from exc
    if not image_bytes:
        raise HTTPException(status_code=422, detail="Image payload is empty.")
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="Image exceeds 10MB limit.")
    return {
        "mime_type": mime_type,
        "content_bytes": image_bytes,
        "file_name": file_name,
    }


@app.post("/api/chat/stop")
async def stop_chat(payload: ChatStopRequest) -> dict[str, object]:
    chat_id = payload.chat_id.strip()
    cancelled = await _stop_gateway_chat(chat_id)
    return {"ok": True, "cancelled": cancelled}


@app.get("/api/providers", response_model=list[ProviderOption])
async def get_providers() -> list[dict[str, object]]:
    return get_provider_options()


@app.post("/api/settings", response_model=Settings)
async def update_settings(settings: Settings) -> Settings:
    existing = await load_settings()
    settings = settings.model_copy(update={"user_message_count": existing.user_message_count})
    _merge_existing_provider_api_keys(existing, settings)
    _merge_google_managed_oauth_params(existing, settings)
    _merge_git_managed_ssh_params(existing, settings)
    _validate_settings_payload(settings)
    return await save_settings(settings)


@app.post("/api/settings/active-provider-model", response_model=Settings)
async def update_active_provider_model(payload: ActiveProviderModelRequest) -> Settings:
    provider_id = payload.provider_id.strip()
    model_id = payload.model_id.strip()
    if not provider_id:
        raise HTTPException(status_code=422, detail="Provider is required.")
    if not model_id:
        raise HTTPException(status_code=422, detail="Model is required.")

    settings = await load_settings()
    provider_config = settings.provider_configs.get(provider_id)
    if provider_config is None:
        raise HTTPException(status_code=422, detail="Selected provider is not configured.")

    updated_provider_configs = dict(settings.provider_configs)
    updated_provider_configs[provider_id] = provider_config.model_copy(update={"model": model_id})
    updated_settings = settings.model_copy(
        update={
            "active_provider_id": provider_id,
            "active_model_id": model_id,
            "provider_configs": updated_provider_configs,
        }
    )
    _validate_settings_payload(updated_settings)
    return await save_settings(updated_settings)


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

    compacted_memory = _normalize_compacted_memory_output(str(compacted_text), required_timestamps)
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

    # For OAuth providers with no api_key (credentials not yet obtained), skip verification.
    # User must complete OAuth flow first; model selection can be changed without full verification.
    auth_mode = getattr(provider, "auth_mode", "api_key") or "api_key"
    if auth_mode == "oauth" and not payload.api_key.strip():
        return VerifyProviderResponse(ok=True, detail="OAuth provider selected. Complete OAuth flow to activate.")

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


@app.get("/api/mcps/whatsapp/status", response_model=WhatsAppStatusResponse)
async def get_whatsapp_runtime_status() -> WhatsAppStatusResponse:
    payload = await whatsapp_status()
    state = str(payload.get("status", "")).strip().lower()
    return WhatsAppStatusResponse(
        connected=state == "ready",
        state=state or "unknown",
        qr_data_url=str(payload.get("qr_data_url", "")),
    )


@app.get("/api/mcps/whatsapp/contacts")
async def get_whatsapp_contacts() -> dict[str, object]:
    contacts = await whatsapp_list_contacts()
    return {"ok": True, "contacts": contacts}


@app.get("/api/mcps/whatsapp/connect")
async def whatsapp_connect_popup() -> HTMLResponse:
    try:
        await whatsapp_connect()
    except Exception as exc:
        return HTMLResponse(content=_whatsapp_popup_html(error=str(exc)))
    return HTMLResponse(content=_whatsapp_popup_html())


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
    whatsapp_config = settings.integration_configs.get("whatsapp") or IntegrationConfig()
    token_value = telegram_config.params.get("bot_token", "")
    token_configured = isinstance(token_value, str) and bool(token_value.strip())
    owner_user_id = settings.telegram_state.owner_user_id.strip()
    owner_chat_id = settings.telegram_state.owner_chat_id.strip()

    whatsapp_state = "disabled"
    whatsapp_connected = False
    if bool(whatsapp_config.enabled):
        try:
            runtime = await whatsapp_status()
            whatsapp_state = str(runtime.get("status", "")).strip().lower() or "unknown"
            whatsapp_connected = whatsapp_state == "ready"
        except Exception:
            whatsapp_state = "unavailable"

    return IntegrationStatusResponse(
        statuses={
            "telegram": {
                "enabled": bool(telegram_config.enabled),
                "token_configured": token_configured,
                "owner_user_id": owner_user_id,
                "owner_chat_id": owner_chat_id,
                "owner_bound": bool(owner_user_id),
            },
            "whatsapp": {
                "enabled": bool(whatsapp_config.enabled),
                "connected": whatsapp_connected,
                "state": whatsapp_state,
            },
        }
    )


@app.get("/api/timed-jobs", response_model=TimedJobsResponse)
async def get_timed_jobs() -> TimedJobsResponse:
    settings = await load_settings()
    jobs = await list_timed_jobs()
    channels = get_timed_job_channel_options(settings)
    return TimedJobsResponse(jobs=jobs, channels=channels)


@app.get("/api/timed-jobs/auth-alert-status", response_model=TimedJobAuthAlertStatusResponse)
async def get_timed_job_auth_alert_status() -> TimedJobAuthAlertStatusResponse:
    provider_ids = get_timed_job_auth_alert_provider_ids()
    detail = ""
    if provider_ids:
        joined = ", ".join(provider_ids)
        detail = (
            "Timed jobs detected expired provider authentication and suppressed repeated alerts "
            f"for: {joined}. Reconnect the provider in Setup."
        )
    return TimedJobAuthAlertStatusResponse(
        active=bool(provider_ids),
        provider_ids=provider_ids,
        detail=detail,
    )


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


async def _enqueue_gateway_chat_job(job: dict[str, Any]) -> None:
    chat_id = str(job.get("chat_id", "")).strip()
    if not chat_id:
        return
    async with _gateway_chat_lock:
        queue = _gateway_chat_queues.setdefault(chat_id, [])
        queue.append(job)
        task = _gateway_chat_tasks.get(chat_id)
        if task is None or task.done():
            _gateway_chat_tasks[chat_id] = asyncio.create_task(_process_gateway_chat_queue(chat_id))


async def _process_gateway_chat_queue(chat_id: str) -> None:
    try:
        while True:
            async with _gateway_chat_lock:
                queue = _gateway_chat_queues.get(chat_id, [])
                if not queue:
                    _gateway_chat_queues.pop(chat_id, None)
                    _gateway_chat_tasks.pop(chat_id, None)
                    _gateway_chat_active_request_ids.pop(chat_id, None)
                    return
                job = queue.pop(0)
                _gateway_chat_active_request_ids[chat_id] = str(job.get("request_id", "")).strip()
            await _process_gateway_chat_job(chat_id, job)
            async with _gateway_chat_lock:
                _gateway_chat_active_request_ids.pop(chat_id, None)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Gateway chat queue worker failed", extra={"chat_id": chat_id})
    finally:
        async with _gateway_chat_lock:
            if _gateway_chat_tasks.get(chat_id) is asyncio.current_task():
                _gateway_chat_tasks.pop(chat_id, None)
            _gateway_chat_active_request_ids.pop(chat_id, None)


async def _process_gateway_chat_job(chat_id: str, job: dict[str, Any]) -> None:
    request_id = str(job.get("request_id", "")).strip()
    message = str(job.get("message", "")).strip()
    image_payload = job.get("image") if isinstance(job.get("image"), dict) else None
    has_image = image_payload is not None
    if not request_id or (not message and not has_image):
        return

    settings = await load_settings()
    chat = _find_chat_by_id(settings, chat_id)
    if chat is None:
        return
    ensure_runtime_context_seed(chat, settings)

    assistant = _find_assistant_message_by_request_id(chat, request_id)
    if assistant is None:
        return

    assistant.status = "processing"
    assistant.timestamp = datetime.now(timezone.utc).isoformat()
    await save_chat_state(settings.chats, settings.active_chat_id, settings.daily_token_usage)

    resolved_provider_id = str(job.get("provider_id", "")).strip() or settings.active_provider_id
    resolved_provider_config = settings.provider_configs.get(resolved_provider_id)
    resolved_model = str(job.get("model", "")).strip() or (resolved_provider_config.model if resolved_provider_config else "")
    resolved_api_key = str(job.get("api_key", "")).strip() or (resolved_provider_config.api_key if resolved_provider_config else "")

    history = _build_gateway_history(chat.messages)
    image_analysis_text = ""
    image_analysis_tokens: int | None = None
    if has_image:
        image_mime = str(image_payload.get("mime_type", "")).strip()
        image_bytes = image_payload.get("content_bytes")
        if not image_mime.startswith("image/") or not isinstance(image_bytes, (bytes, bytearray)):
            await _mark_gateway_request_error(chat_id, request_id, "Hard error: Invalid image payload.")
            return
        try:
            image_analysis_text, image_analysis_tokens = await analyze_image(
                provider_id=resolved_provider_id,
                model=resolved_model,
                api_key=resolved_api_key,
                image_bytes=bytes(image_bytes),
                mime_type=image_mime,
                prompt=_image_analysis_prompt(message),
            )
        except Exception as exc:
            await _mark_gateway_request_error(chat_id, request_id, f"Image analysis failed: {exc}")
            return

        settings_with_analysis = await load_settings()
        chat_with_analysis = _find_chat_by_id(settings_with_analysis, chat_id)
        if chat_with_analysis is None:
            return
        analysis_message = ChatMessage(
            role="assistant",
            content=f"Image analysis: {image_analysis_text.strip()}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            request_id=request_id,
            status="done",
        )
        chat_with_analysis.messages.append(analysis_message)
        await save_chat_state(
            settings_with_analysis.chats,
            settings_with_analysis.active_chat_id,
            settings_with_analysis.daily_token_usage,
        )

        settings = settings_with_analysis
        chat = chat_with_analysis
        history = _build_gateway_history(chat.messages)

    model_message = message.strip()
    if has_image:
        analysis_block = image_analysis_text.strip()
        if model_message:
            model_message = f"{model_message}\n\nImage analysis:\n{analysis_block}"
        else:
            model_message = (
                "The user sent an image without text. Use this image analysis to respond helpfully:\n"
                f"{analysis_block}"
            )

    try:
        result, _ = await generate_chat_response(
            settings=settings,
            message=model_message,
            history=history,
            memory_block=chat.memory_block,
            provider_id=str(job.get("provider_id", "")),
            model=str(job.get("model", "")),
            api_key=str(job.get("api_key", "")),
            bot_name=str(job.get("bot_name", "")),
            system_prompt=str(job.get("system_prompt", "")),
            source_channel="gateway",
            source_chat_id=chat_id,
            source_request_id=request_id,
        )
    except asyncio.CancelledError:
        await _mark_gateway_requests_interrupted(chat_id, request_ids=[request_id], detail="Execution interrupted by user.")
        raise
    except Exception as exc:
        await _mark_gateway_request_error(chat_id, request_id, f"Hard error: {exc}")
        return

    settings = await load_settings()
    chat = _find_chat_by_id(settings, chat_id)
    if chat is None:
        return
    assistant = _find_assistant_message_by_request_id(chat, request_id)
    if assistant is None:
        return

    final_timestamp = datetime.now(timezone.utc).isoformat()
    trace_messages = result.get("system_trace_messages", []) if isinstance(result, dict) else []
    if isinstance(trace_messages, list):
        for entry in trace_messages:
            if not isinstance(entry, dict):
                continue
            content = str(entry.get("content", "")).strip()
            if not content:
                continue
            system_type = str(entry.get("system_type", "")).strip() or "orchestrator"
            chat.messages.append(
                ChatMessage(
                    role="system",
                    content=content,
                    timestamp=final_timestamp,
                    system_type=system_type,
                    request_id=request_id,
                )
            )

    assistant.content = str(result.get("text", "")).strip() if isinstance(result, dict) else ""
    assistant.timestamp = final_timestamp
    assistant.status = "done"
    raw_tool_usage = result.get("used_mcp_tools", []) if isinstance(result, dict) else []
    assistant.tool_usage = [
        {
            "mcp_id": str(item.get("mcp_id", "")),
            "mcp_label": str(item.get("mcp_label", "")),
            "tool_id": str(item.get("tool_id", "")),
            "tool_label": str(item.get("tool_label", "")),
        }
        for item in raw_tool_usage
        if isinstance(item, dict)
    ]

    used_tokens = result.get("used_tokens") if isinstance(result, dict) else None
    if isinstance(image_analysis_tokens, int) and image_analysis_tokens > 0:
        used_tokens = (used_tokens if isinstance(used_tokens, int) else 0) + image_analysis_tokens
    if isinstance(used_tokens, int) and used_tokens > 0:
        chat.total_tokens_used = max(0, chat.total_tokens_used) + used_tokens
        add_daily_usage(settings, used_tokens)

    await save_chat_state(settings.chats, settings.active_chat_id, settings.daily_token_usage)

    try:
        await register_completed_turn(
            source_channel="gateway",
            source_chat_id=chat_id,
            user_message=message or "[Image attached]",
            assistant_message=assistant.content,
        )
    except Exception:
        pass


async def _stop_gateway_chat(chat_id: str) -> int:
    queued_request_ids: list[str] = []
    active_request_id = ""

    async with _gateway_chat_lock:
        queue = _gateway_chat_queues.get(chat_id, [])
        for entry in queue:
            request_id = str(entry.get("request_id", "")).strip()
            if request_id:
                queued_request_ids.append(request_id)
        _gateway_chat_queues[chat_id] = []
        active_request_id = _gateway_chat_active_request_ids.get(chat_id, "").strip()
        task = _gateway_chat_tasks.pop(chat_id, None)
        _gateway_chat_active_request_ids.pop(chat_id, None)
        if task is not None:
            task.cancel()

    request_ids = [request_id for request_id in queued_request_ids if request_id]
    if active_request_id and active_request_id not in request_ids:
        request_ids.append(active_request_id)
    return await _mark_gateway_requests_interrupted(chat_id, request_ids=request_ids, detail="Execution interrupted by user.")


async def _mark_gateway_request_error(chat_id: str, request_id: str, detail: str) -> None:
    settings = await load_settings()
    chat = _find_chat_by_id(settings, chat_id)
    if chat is None:
        return
    message = _find_assistant_message_by_request_id(chat, request_id)
    if message is None:
        return
    message.status = "error"
    message.timestamp = datetime.now(timezone.utc).isoformat()
    existing = message.content.strip()
    message.content = f"{existing}\n\n{detail}".strip() if existing else detail
    await save_chat_state(settings.chats, settings.active_chat_id, settings.daily_token_usage)


async def _mark_gateway_requests_interrupted(chat_id: str, request_ids: list[str], detail: str) -> int:
    settings = await load_settings()
    chat = _find_chat_by_id(settings, chat_id)
    if chat is None:
        return 0

    target_ids = {request_id.strip() for request_id in request_ids if request_id.strip()}
    changed = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    for message in chat.messages:
        if message.role != "assistant":
            continue
        if message.status not in {"queued", "processing"}:
            continue
        if target_ids and message.request_id not in target_ids:
            continue
        existing = message.content.strip()
        message.content = f"{existing}\n\n{detail}".strip() if existing else detail
        message.status = "error"
        message.timestamp = now_iso
        changed += 1

    if changed > 0:
        await save_chat_state(settings.chats, settings.active_chat_id, settings.daily_token_usage)
    return changed


def _find_chat_by_id(settings: Settings, chat_id: str) -> Any:
    for chat in settings.chats:
        if chat.id == chat_id:
            return chat
    return None


def _find_assistant_message_by_request_id(chat: Any, request_id: str) -> Any:
    for message in chat.messages:
        if message.role == "assistant" and message.request_id == request_id:
            return message
    return None


def _build_gateway_history(messages: list[ChatMessage]) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for turn in messages:
        if turn.role not in {"user", "assistant", "system"}:
            continue
        content = turn.content.strip()
        if not content:
            continue
        if turn.role == "system" and turn.system_type != "runtime_context_seed":
            continue
        history.append({"role": turn.role, "content": content})
    return history


def _image_analysis_prompt(user_message: str) -> str:
    user_text = user_message.strip()
    if user_text:
        return (
            "Analyze this image for the current chat request. "
            "Provide a concise factual summary, visible text (OCR), and details relevant to the user request. "
            "Do not invent details.\n\n"
            f"User request: {user_text}"
        )
    return (
        "Analyze this image for chat context. Provide a concise factual summary, visible text (OCR), "
        "and relevant notable details. Do not invent details."
    )


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
            detail="Setup cannot be marked complete without user name fields, active provider, model, and API key.",
        )


def _can_complete_setup(settings: Settings) -> bool:
    if not settings.user_full_name.strip():
        return False

    if not settings.user_call_name.strip():
        return False

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
    valid_configs = {}
    for mcp_id, mcp_config in settings.mcp_configs.items():
        if not is_supported_mcp(mcp_id):
            continue

        mcp = get_mcp(mcp_id)
        if mcp is None:
            continue
            
        valid_configs[mcp_id] = mcp_config
        
    settings.mcp_configs = valid_configs


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


def _merge_existing_provider_api_keys(existing: Settings, incoming: Settings) -> None:
    for provider_id, incoming_config in list(incoming.provider_configs.items()):
        incoming_key = incoming_config.api_key.strip()
        if incoming_key:
            continue
        existing_config = existing.provider_configs.get(provider_id)
        if existing_config is None:
            continue
        existing_key = existing_config.api_key.strip()
        if not existing_key:
            continue
        incoming.provider_configs[provider_id] = incoming_config.model_copy(update={"api_key": existing_key})


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
        "Preserve timestamp provenance by retaining all timestamps exactly as provided."
    )


def _normalize_memory_compaction_text(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalize_memory_timestamp_precision(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "unknown"
    if raw.lower() == "unknown":
        return "unknown"

    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.isoformat(timespec="seconds")
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

    return raw


def _looks_like_memory_timestamp(value: str) -> bool:
    candidate = str(value or "").strip()
    if not candidate:
        return False
    if candidate.lower() == "unknown":
        return True
    try:
        normalized = _normalize_memory_timestamp_precision(candidate)
        datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        return True
    except ValueError:
        pass
    try:
        datetime.strptime(candidate, "%Y-%m-%d %H:%M:%S")
        return True
    except ValueError:
        return False


def _build_memory_compaction_source(memories: list[MemoryEntry]) -> tuple[list[str], list[str], dict[str, str]]:
    lines: list[str] = []
    required_timestamps: list[str] = []
    by_marker: dict[str, str] = {}

    for entry in memories:
        timestamp = _normalize_memory_timestamp_precision(entry.created_at)
        normalized_content = _normalize_memory_compaction_text(entry.content)
        if not normalized_content:
            continue
        marker = timestamp
        required_timestamps.append(marker)
        source_line = f"{marker}: {normalized_content}"
        lines.append(source_line)
        by_marker[marker] = source_line

    return lines, required_timestamps, by_marker


def _normalize_compacted_memory_output(raw_text: str, required_timestamps: list[str]) -> str:
    allowed = {value.strip() for value in required_timestamps if value.strip()}
    fallback_timestamp = required_timestamps[0].strip() if required_timestamps else "unknown"
    normalized_lines: list[str] = []

    for raw_line in str(raw_text or "").splitlines():
        line = str(raw_line).strip()
        if not line:
            continue
        line = line.lstrip("-•* ").strip()
        if not line:
            continue

        timestamp = ""
        memory_text = ""

        if line.startswith("[ts:") and "]" in line:
            end_idx = line.find("]")
            timestamp = line[4:end_idx].strip()
            memory_text = line[end_idx + 1 :].lstrip(" :").strip()
        elif ":" in line:
            candidate_ts, rest = line.split(":", 1)
            timestamp = candidate_ts.strip()
            memory_text = rest.strip()
        else:
            memory_text = line

        timestamp = _normalize_memory_timestamp_precision(timestamp)
        timestamp = timestamp if timestamp in allowed else timestamp.strip()
        if not _looks_like_memory_timestamp(timestamp):
            timestamp = fallback_timestamp
        if not memory_text:
            continue

        normalized_lines.append(f"{timestamp}: {_normalize_memory_compaction_text(memory_text)}")

    if normalized_lines:
        return "\n".join(normalized_lines)

    fallback_text = _normalize_memory_compaction_text(raw_text)
    if not fallback_text:
        return ""
    return f"{fallback_timestamp}: {fallback_text}"


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
        "- Preserve timestamp provenance in every output row.",
        "Output rules:",
        "- Return plain text only (no markdown code fences).",
        "- One memory per line in this exact format: <timestamp>: <memory>",
        "- Timestamp must have second precision (no milliseconds or microseconds).",
        "- Every non-empty line must include exactly one ':' separator between timestamp and memory text.",
        "- Do not use bullets or numbering.",
        "- Use only these timestamps (copy exactly):",
        *[f"  - {timestamp}" for timestamp in required_timestamps],
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


def _whatsapp_popup_html(error: str = "") -> str:
    safe_error = str(error).replace("<", "&lt;").replace(">", "&gt;").strip()
    return (
        "<!doctype html>"
        "<html><head><meta charset='utf-8'><title>WhatsApp Connect</title><style>"
        "body{font-family:ui-sans-serif,Segoe UI,Arial,sans-serif;margin:0;padding:24px;background:#f7f8fa;color:#1d2330;}"
        ".card{max-width:640px;margin:0 auto;padding:20px;border:1px solid #d7dbe3;border-radius:12px;background:#ffffff;}"
        "h1{margin:0 0 10px;font-size:20px;color:#1f6f43;}"
        "p{margin:0 0 10px;line-height:1.5;}"
        ".qr{display:flex;justify-content:center;align-items:center;min-height:320px;border:1px dashed #cfd8e3;border-radius:10px;background:#fbfcff;}"
        ".hint{color:#5f6f86;font-size:13px;}"
        "</style></head><body><div class='card'>"
        "<h1>WhatsApp Connect</h1>"
        + (f"<p style='color:#a1302d'>{safe_error}</p>" if safe_error else "<p>Scan the QR with WhatsApp Web to connect.</p>")
        + "<div id='status' class='hint'>Loading status...</div>"
        "<div id='qr' class='qr'>Waiting for QR...</div>"
        "</div><script>"
        "async function tick(){"
        "try{const r=await fetch('/api/mcps/whatsapp/status',{cache:'no-store'});"
        "const p=await r.json();"
        "const state=String(p.state||'unknown');"
        "const normalizedState=state.toLowerCase();"
        "document.getElementById('status').textContent='State: '+state;"
        "if(p.connected||normalizedState==='ready'){"
        "try{if(window.opener){window.opener.postMessage({type:'krill-whatsapp-connected',state:normalizedState},window.location.origin);}}catch(_e){}"
        "try{const cr=await fetch('/api/mcps/whatsapp/contacts',{cache:'no-store'});"
        "if(cr.ok){document.getElementById('qr').innerHTML='<p>Connected and contacts loaded. Closing...</p>';window.setTimeout(function(){window.close();},900);return;}}catch(_e){}"
        "document.getElementById('qr').innerHTML='<p>Connected. You can close this window.</p>';window.setTimeout(function(){window.close();},1200);return;}"
        "if(normalizedState==='authenticated'){document.getElementById('qr').innerHTML='<p>Authenticated. Finalizing connection...</p>'; }"
        "if(p.qr_data_url){document.getElementById('qr').innerHTML='<img alt=\"WhatsApp QR\" style=\"max-width:280px\" src=\"'+p.qr_data_url+'\" />';}"
        "}catch(_e){document.getElementById('status').textContent='Failed to load status';}"
        "window.setTimeout(tick,1500);}"
        "tick();"
        "</script></body></html>"
    )
