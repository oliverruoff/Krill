"""Shared chat execution engine used by Gateway SSE and Telegram integration."""

from typing import Awaitable, Callable, TypedDict

from app.config import Settings
from app.providers import get_provider, get_provider_model_limit
from app.runtime_prompt import compose_runtime_system_prompt
from app.tooling import generate_with_tools


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


ToolStepCallback = Callable[[ChatEngineTraceMessage], Awaitable[None]]


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
    on_tool_step: ToolStepCallback | None = None,
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
    runtime_system_prompt = compose_runtime_system_prompt(
        bot_name=bot_name.strip() if bot_name.strip() else settings.bot_name,
        system_prompt=system_prompt.strip() if system_prompt.strip() else settings.system_prompt,
        memory_block=memory_block,
        core_memories=[memory.model_dump() for memory in settings.core_memories],
    )
    token_limit = get_provider_model_limit(active_provider_id, model_id)

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
        on_tool_step=on_tool_step,
    )

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

    used_tokens = orchestration.get("used_tokens")
    result: ChatEngineResult = {
        "text": str(orchestration.get("text", "")).strip(),
        "used_tokens": used_tokens if isinstance(used_tokens, int) else None,
        "used_mcp_tools": normalized_tools,
        "system_trace_messages": normalized_trace,
    }
    return result, token_limit
