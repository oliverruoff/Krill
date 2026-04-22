"""Shared chat execution engine used by Gateway SSE and Telegram integration."""

import asyncio
from typing import Awaitable, Callable, TypedDict, cast

from app.config import load_settings, save_settings, Settings
from app.providers import get_provider, get_provider_model_limit
from app.providers.openai_codex_oauth import (
    OPENAI_CODEX_OAUTH_PROVIDER_ID,
    get_refreshed_bundle_for_persistence,
)
from app.runtime_prompt import compose_runtime_system_prompt
from app.tooling import generate_with_tools
from app.tooling.execution import (
    CancellationToken,
    ExecutionEvent,
    build_conversation_key,
    register_execution,
    unregister_execution,
)
from app.tooling.runtime_context import reset_runtime_context, set_runtime_context


class ChatEngineToolUsage(TypedDict):
    mcp_id: str
    mcp_label: str
    tool_id: str
    tool_label: str


class ChatEngineTraceMessage(TypedDict):
    system_type: str
    content: str


class ChatEngineResult(TypedDict):
    text: str
    used_tokens: int | None
    used_mcp_tools: list[ChatEngineToolUsage]
    system_trace_messages: list[ChatEngineTraceMessage]
    execution_events: list[ExecutionEvent]


ExecutionEventCallback = Callable[[ExecutionEvent], Awaitable[None]]


async def generate_chat_response(
    *,
    settings: Settings,
    message: str,
    history: list[dict[str, str]],
    memory_block: str = "",
    provider_id: str = "",
    model: str = "",
    api_key: str = "",
    bot_name: str = "",
    system_prompt: str = "",
    source_channel: str = "gateway",
    source_chat_id: str = "",
    source_request_id: str = "",
    source_user_id: str = "",
    source_user_role: str = "",
    source_room_id: str = "",
    source_room_mode: str = "",
    allowed_mcp_ids: list[str] | None = None,
    on_execution_event: ExecutionEventCallback | None = None,
    cancellation_token: CancellationToken | None = None,
) -> tuple[ChatEngineResult, int | None]:
    active_provider_id = provider_id.strip() if provider_id.strip() else settings.active_provider_id
    provider_config = settings.provider_configs.get(active_provider_id)
    if provider_config is None:
        raise RuntimeError("Active provider is not configured.")

    provider = get_provider(active_provider_id)
    if provider is None:
        raise RuntimeError("Active provider is unavailable.")

    model_id = model.strip() if model.strip() else provider_config.model
    api_key_value = api_key if api_key.strip() else provider_config.api_key
    used_stored_provider_api_key = not api_key.strip()
    runtime_system_prompt = compose_runtime_system_prompt(
        settings=settings,
        memory_block=memory_block,
        source_channel=source_channel,
    )
    token_limit = get_provider_model_limit(active_provider_id, model_id)

    token = cancellation_token or CancellationToken()
    conversation_key = build_conversation_key(source_channel, source_chat_id)
    current_task = asyncio.current_task()
    await register_execution(
        conversation_key=conversation_key,
        request_id=source_request_id,
        token=token,
        task=current_task,
    )
    context_token = set_runtime_context(
        source_channel=source_channel,
        source_chat_id=source_chat_id,
        source_request_id=source_request_id,
        cancellation_token=token,
        source_user_id=source_user_id,
        source_user_role=source_user_role,
        source_room_id=source_room_id,
        source_room_mode=source_room_mode,
        allowed_mcp_ids=allowed_mcp_ids,
    )
    try:
        orchestration = await generate_with_tools(
            provider=provider,
            settings=settings,
            prompt=message,
            system_prompt=runtime_system_prompt,
            model=model_id,
            api_key=api_key_value,
            history=history,
            max_tool_recursion=settings.tool_max_recursion,
            tool_timeout_seconds=settings.tool_timeout_seconds,
            on_execution_event=on_execution_event,
            cancellation_token=token,
        )
    finally:
        reset_runtime_context(context_token)
        await unregister_execution(request_id=source_request_id, conversation_key=conversation_key)

    if used_stored_provider_api_key and active_provider_id == OPENAI_CODEX_OAUTH_PROVIDER_ID:
        await _persist_refreshed_openai_oauth_bundle_if_needed()

    normalized_tools: list[ChatEngineToolUsage] = []
    raw_tools = orchestration.get("used_mcp_tools", [])
    if isinstance(raw_tools, list):
        for entry in raw_tools:
            if not isinstance(entry, dict):
                continue
            normalized_tools.append(
                {
                    "mcp_id": str(entry.get("mcp_id", "")),
                    "mcp_label": str(entry.get("mcp_label", "")),
                    "tool_id": str(entry.get("tool_id", "")),
                    "tool_label": str(entry.get("tool_label", "")),
                }
            )

    normalized_trace: list[ChatEngineTraceMessage] = []
    raw_trace = orchestration.get("system_trace_messages", [])
    if isinstance(raw_trace, list):
        for entry in raw_trace:
            if not isinstance(entry, dict):
                continue
            normalized_trace.append(
                {
                    "system_type": str(entry.get("system_type", "")),
                    "content": str(entry.get("content", "")),
                }
            )

    normalized_events: list[ExecutionEvent] = []
    raw_events = orchestration.get("execution_events", [])
    if isinstance(raw_events, list):
        for entry in raw_events:
            if not isinstance(entry, dict):
                continue
            normalized_events.append(cast(ExecutionEvent, {str(key): value for key, value in entry.items()}))

    used_tokens = orchestration.get("used_tokens")
    result: ChatEngineResult = {
        "text": str(orchestration.get("text", "")).strip(),
        "used_tokens": used_tokens if isinstance(used_tokens, int) else None,
        "used_mcp_tools": normalized_tools,
        "system_trace_messages": normalized_trace,
        "execution_events": normalized_events,
    }
    return result, token_limit


async def _persist_refreshed_openai_oauth_bundle_if_needed() -> None:
    settings = await load_settings()
    provider_config = settings.provider_configs.get(OPENAI_CODEX_OAUTH_PROVIDER_ID)
    if provider_config is None:
        return

    refreshed_bundle = get_refreshed_bundle_for_persistence(provider_config.api_key)
    if not refreshed_bundle:
        return

    settings.provider_configs[OPENAI_CODEX_OAUTH_PROVIDER_ID] = provider_config.model_copy(
        update={"api_key": refreshed_bundle}
    )
    await save_settings(settings)
