import asyncio
import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import BRAINDUMP_PATH, IntegrationConfig, McpConfig, Settings, ensure_settings_file, load_settings, save_settings
from .integrations import (
    get_integration,
    get_integration_options,
    get_runtime_integrations,
    is_supported_integration,
)
from .mcps.git_ops import (
    SSH_PRIVATE_PARAM,
    SSH_PUBLIC_PARAM,
    get_or_create_ssh_public_key,
    get_workspace_path,
    verify_github_ssh_access,
)
from .mcps import get_mcp, get_mcp_options, is_supported_mcp
from .providers import get_provider, get_provider_model_limit, get_provider_options, is_supported_provider
from .tooling import generate_with_tools


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Krill")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


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


class GitSshKeyResponse(BaseModel):
    public_key: str


class GitSshVerifyResponse(BaseModel):
    ok: bool
    detail: str


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
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
    telegram_state: dict[str, object]
    telegram_enabled: bool
    telegram_token_configured: bool


@app.on_event("startup")
async def startup_event() -> None:
    await ensure_settings_file()
    for integration in get_runtime_integrations():
        integration.start()


@app.on_event("shutdown")
async def shutdown_event() -> None:
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


@app.get("/api/braindump/download", response_class=FileResponse)
async def download_braindump() -> FileResponse:
    await ensure_settings_file()
    return FileResponse(BRAINDUMP_PATH, media_type="application/json", filename="braindump.json")


@app.get("/api/settings", response_model=Settings)
async def get_settings() -> Settings:
    return await load_settings()


@app.get("/api/chat/state", response_model=ChatStateResponse)
async def get_chat_state() -> ChatStateResponse:
    settings = await load_settings()
    telegram_config = settings.integration_configs.get("telegram") or IntegrationConfig()
    bot_token = telegram_config.params.get("bot_token", "")
    token_configured = isinstance(bot_token, str) and bool(bot_token.strip())
    return ChatStateResponse(
        chats=[chat.model_dump() for chat in settings.chats],
        active_chat_id=settings.active_chat_id,
        daily_token_usage=[entry.model_dump() for entry in settings.daily_token_usage],
        telegram_state={"owner_user_id": settings.telegram_state.owner_user_id},
        telegram_enabled=bool(telegram_config.enabled),
        telegram_token_configured=token_configured,
    )


@app.get("/api/providers", response_model=list[ProviderOption])
async def get_providers() -> list[dict[str, object]]:
    return get_provider_options()


@app.post("/api/settings", response_model=Settings)
async def update_settings(settings: Settings) -> Settings:
    _validate_settings_payload(settings)
    return await save_settings(settings)


@app.post("/api/braindump/import", response_model=Settings)
async def import_braindump(settings: Settings) -> Settings:
    normalized = settings.model_copy(update={"setup_completed": True})
    _validate_settings_payload(normalized)
    return await save_settings(normalized)


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

    ok, detail = await mcp.verify(payload.params)
    if not ok:
        raise HTTPException(status_code=422, detail=detail)

    return VerifyMcpResponse(ok=True, detail=detail)


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

    active_provider_id = payload.provider_id.strip() if payload.provider_id.strip() else settings.active_provider_id
    provider_config = settings.provider_configs.get(active_provider_id)

    if provider_config is None:
        raise HTTPException(status_code=422, detail="Active provider is not configured.")

    provider = get_provider(active_provider_id)
    if provider is None:
        raise HTTPException(status_code=422, detail="Active provider is unavailable.")

    model_id = payload.model.strip() if payload.model.strip() else provider_config.model
    api_key = payload.api_key if payload.api_key.strip() else provider_config.api_key

    token_limit = get_provider_model_limit(active_provider_id, model_id)
    history = [turn.model_dump() for turn in payload.history]
    runtime_system_prompt = _compose_runtime_system_prompt_from_values(
        bot_name=payload.bot_name.strip() if payload.bot_name.strip() else settings.bot_name,
        system_prompt=payload.system_prompt.strip() if payload.system_prompt.strip() else settings.system_prompt,
        memory_block=payload.memory_block,
    )

    async def event_stream():
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        orchestration_holder: dict[str, object] = {}

        async def _emit_tool_step(step: object) -> None:
            payload: dict[str, object]
            if isinstance(step, dict):
                payload = {str(key): value for key, value in step.items()}
            else:
                payload = {"system_type": "tool_step", "content": str(step)}
            await queue.put(_sse("tool_step", payload))

        async def run_orchestration() -> None:
            try:
                orchestration_holder["result"] = await generate_with_tools(
                    provider=provider,
                    settings=settings,
                    prompt=payload.message,
                    system_prompt=runtime_system_prompt,
                    model=model_id,
                    api_key=api_key,
                    history=history,
                    max_tool_recursion=settings.tool_max_recursion,
                    tool_timeout_seconds=settings.tool_timeout_seconds,
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

        orchestration = orchestration_holder.get("result")
        if not isinstance(orchestration, dict):
            yield _sse("error", {"detail": "Missing orchestration result."})
            return

        text = orchestration.get("text", "")
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
        compacted_text, used_tokens = await provider.generate(
            prompt=_build_compaction_prompt(payload.memory_block, payload.target_token_limit),
            system_prompt=_compaction_system_prompt(),
            model=provider_config.model,
            api_key=provider_config.api_key,
            history=incoming_history,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Compaction failed: {exc}") from exc

    trimmed_history = payload.history[-4:] if len(payload.history) > 4 else payload.history
    memory_block = compacted_text.strip()
    if not memory_block:
        raise HTTPException(status_code=422, detail="Compaction failed: Provider returned empty compact memory.")

    return CompactChatResponse(memory_block=memory_block, history=trimmed_history, used_tokens=used_tokens)


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


def _validate_integration_configs(settings: Settings) -> None:
    for integration_id in settings.integration_configs.keys():
        if not is_supported_integration(integration_id):
            raise HTTPException(status_code=422, detail=f"Unsupported integration: {integration_id}")


def _is_setup_complete(settings: Settings) -> bool:
    if not settings.setup_completed:
        return False

    return _can_complete_setup(settings)


def _sse(event_name: str, payload: dict[str, object]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"


def _compose_runtime_system_prompt(settings: Settings, memory_block: str = "") -> str:
    return _compose_runtime_system_prompt_from_values(settings.bot_name, settings.system_prompt, memory_block)


def _compose_runtime_system_prompt_from_values(bot_name: str, system_prompt: str, memory_block: str = "") -> str:
    invisible_context = (
        f"You are Krill assistant named '{bot_name}'. "
        f"This is the system prompt your user provided: {system_prompt}"
    )

    if memory_block.strip():
        invisible_context = f"{invisible_context}\n\nCompacted conversation memory:\n{memory_block.strip()}"

    return invisible_context


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


def _chunk_text(text: str) -> list[str]:
    tokens = text.split(" ")

    if len(tokens) <= 1:
        return [text]

    return [f"{token} " for token in tokens[:-1]] + [tokens[-1]]
