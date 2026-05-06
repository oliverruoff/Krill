"""Shared chat-session runtime helpers for optional chat integrations."""

from datetime import datetime, timezone

from app.config import ChatMessage, ChatSession, Settings

RUNTIME_CONTEXT_SYSTEM_TYPE = "runtime_context_seed"


def build_runtime_context_seed(settings: Settings) -> str:
    """Build a stable per-chat runtime seed with identity and core memories."""
    bot_name = settings.bot_name.strip() or "Krill"
    user_full_name = settings.user_full_name.strip() or "the user"
    user_call_name = settings.user_call_name.strip() or "the user"
    behavior = settings.system_prompt.strip()
    seed = (
        f"You are Krill assistant named '{bot_name}'. "
        f"You are the assistant of '{user_full_name}'. "
        f"Call your human user '{user_call_name}'."
    )

    if behavior:
        seed = (
            f"{seed} "
            f"This is the system prompt your user provided: {behavior}"
        )

    seed = (
        f"{seed}\n\n"
        "Identity reminder:\n"
        "- When memories mention this person, or mention 'the user', that always refers to your human user."
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
    seed_content = build_runtime_context_seed(settings)
    for message in chat.messages:
        if message.role == "system" and message.system_type == RUNTIME_CONTEXT_SYSTEM_TYPE:
            if message.content != seed_content:
                message.content = seed_content
            return

    chat.messages.insert(
        0,
        ChatMessage(
            role="system",
            content=seed_content,
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
        if not message.archived
        and message.role in {"user", "assistant", "system"}
        and message.content.strip()
        and (
            message.role != "system"
            or message.system_type in {RUNTIME_CONTEXT_SYSTEM_TYPE, "integration_context"}
        )
    ]


def is_over_context_threshold(used_tokens: int | None, token_limit: int | None, threshold: float = 0.75) -> bool:
    """Return True when used tokens meet/exceed threshold of token window."""
    if not isinstance(used_tokens, int) or used_tokens <= 0:
        return False
    if not isinstance(token_limit, int) or token_limit <= 0:
        return False
    return used_tokens >= int(token_limit * threshold)
