"""Shared chat-session runtime helpers for optional chat integrations."""

from datetime import datetime, timezone

from app.config import ChatMessage, ChatSession, Settings

RUNTIME_CONTEXT_SYSTEM_TYPE = "runtime_context_seed"


def build_runtime_context_seed(settings: Settings) -> str:
    """Build a stable per-chat runtime seed with identity and core memories."""
    bot_name = settings.bot_name.strip() or "Krill"
    behavior = settings.system_prompt.strip()
    seed = (
        f"You are Krill assistant named '{bot_name}'. "
        f"This is the system prompt your user provided: {behavior}"
    )

    memory_lines = [
        f"- {memory.content.strip()}"
        for memory in settings.core_memories
        if memory.content.strip()
    ]
    if memory_lines:
        seed = (
            f"{seed}\n\n"
            "Core memories (background context from the user):\n"
            "Use these memories subtly and only when they are relevant and helpful. "
            "Do not repeatedly mention or announce these memories. "
            "Keep the response natural, personal, and context-aware.\n"
            + "\n".join(memory_lines)
        )

    return seed


def ensure_runtime_context_seed(chat: ChatSession, settings: Settings) -> None:
    """Ensure exactly one runtime seed system message exists in a chat."""
    has_seed = any(
        message.role == "system" and message.system_type == RUNTIME_CONTEXT_SYSTEM_TYPE
        for message in chat.messages
    )
    if has_seed:
        return

    chat.messages.insert(
        0,
        ChatMessage(
            role="system",
            content=build_runtime_context_seed(settings),
            timestamp=datetime.now(timezone.utc).isoformat(),
            system_type=RUNTIME_CONTEXT_SYSTEM_TYPE,
            tool_usage=[],
            request_id="",
            status="",
        ),
    )


def build_model_history(chat: ChatSession) -> list[dict[str, str]]:
    """Build provider history from a chat with runtime-seed filtering."""
    return [
        {"role": message.role, "content": message.content}
        for message in chat.messages
        if message.role in {"user", "assistant", "system"}
        and message.content.strip()
        and (message.role != "system" or message.system_type == RUNTIME_CONTEXT_SYSTEM_TYPE)
    ]


def is_over_context_threshold(used_tokens: int | None, token_limit: int | None, threshold: float = 0.75) -> bool:
    """Return True when used tokens meet/exceed threshold of token window."""
    if not isinstance(used_tokens, int) or used_tokens <= 0:
        return False
    if not isinstance(token_limit, int) or token_limit <= 0:
        return False
    return used_tokens >= int(token_limit * threshold)
