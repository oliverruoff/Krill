import asyncio
import contextlib
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.config import ChatMessage, ChatSession, DailyTokenUsage, IntegrationConfig, Settings, load_settings, save_settings
from app.providers import get_provider
from app.tooling import generate_with_tools

from .client import telegram_get_me, telegram_get_updates, telegram_send_message


class TelegramBridgeWorker:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                settings = await load_settings()
                token = _get_bot_token(settings)
                if not _bridge_is_enabled(settings, token):
                    await asyncio.sleep(2)
                    continue

                bot_me = await asyncio.to_thread(telegram_get_me, token)
                bot_result = bot_me.get("result") if isinstance(bot_me, dict) else {}
                bot_username = str(bot_result.get("username", "")).strip().lower() if isinstance(bot_result, dict) else ""
                bot_id = int(bot_result.get("id", 0)) if isinstance(bot_result, dict) else 0

                offset = settings.telegram_state.last_update_id + 1
                updates_payload = await asyncio.to_thread(telegram_get_updates, token, offset, 25)
                updates = updates_payload.get("result") if isinstance(updates_payload, dict) else []
                if not isinstance(updates, list) or not updates:
                    continue

                for update in updates:
                    if not isinstance(update, dict):
                        continue

                    update_id = update.get("update_id")
                    if not isinstance(update_id, int):
                        continue

                    message = update.get("message")
                    if not isinstance(message, dict):
                        await self._store_last_update_id(update_id)
                        continue

                    await self._handle_message(token, message, bot_username, bot_id)
                    await self._store_last_update_id(update_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(2)

    async def _store_last_update_id(self, update_id: int) -> None:
        settings = await load_settings()
        settings.telegram_state.last_update_id = max(settings.telegram_state.last_update_id, update_id)
        await save_settings(settings)

    async def _handle_message(self, token: str, message: dict[str, Any], bot_username: str, bot_id: int) -> None:
        chat = message.get("chat")
        sender = message.get("from")
        text = message.get("text")
        if not isinstance(chat, dict) or not isinstance(sender, dict) or not isinstance(text, str):
            return

        sender_id = sender.get("id")
        chat_id = chat.get("id")
        chat_type = str(chat.get("type", ""))
        if not isinstance(sender_id, int) or not isinstance(chat_id, int):
            return

        settings = await load_settings()
        owner_user_id = settings.telegram_state.owner_user_id.strip()
        if not owner_user_id:
            settings.telegram_state.owner_user_id = str(sender_id)
            await save_settings(settings)
            owner_user_id = str(sender_id)

        if str(sender_id) != owner_user_id:
            return

        is_group = chat_type in {"group", "supergroup"}
        if is_group and not _is_group_message_addressed_to_bot(message, bot_username, bot_id):
            return

        command, command_arg = _parse_command(text, bot_username)
        if command:
            response_text = await self._handle_command(settings, command, command_arg)
            if response_text:
                await asyncio.to_thread(telegram_send_message, token, chat_id, response_text)
            return

        response_text = await self._handle_user_message(settings, text)
        if response_text:
            for chunk in _chunk_telegram_text(response_text):
                await asyncio.to_thread(telegram_send_message, token, chat_id, chunk)

    async def _handle_command(self, settings: Settings, command: str, argument: str) -> str:
        if command == "new":
            chat = _create_chat_entry("New chat")
            settings.chats.append(chat)
            settings.active_chat_id = chat.id
            await save_settings(settings)
            return f"Started new chat: {chat.title}"

        if command == "where":
            active = _get_active_chat(settings)
            if active is None:
                return "No active chat yet. Send a message or use /new."
            return f"Active chat: {active.title} ({_short_chat_id(active.id)})"

        if command == "usage":
            active = _get_active_chat(settings)
            chat_tokens = active.total_tokens_used if active is not None else 0
            daily_tokens = _today_token_usage(settings)
            return f"Usage\nChat tokens: {chat_tokens}\nToday tokens: {daily_tokens}"

        if command == "help":
            return (
                "Available commands:\n"
                "/new - Create and switch to a new chat\n"
                "/chats - List recent chats\n"
                "/use <number> - Switch active chat\n"
                "/where - Show active chat\n"
                "/usage - Show chat and daily token usage\n"
                "/help - Show this help"
            )

        if command == "chats":
            if not settings.chats:
                return "No chats yet."
            lines = ["Recent chats:"]
            sorted_chats = sorted(settings.chats, key=_latest_timestamp_or_empty, reverse=True)
            for index, chat in enumerate(sorted_chats[:10], start=1):
                active_marker = " *" if chat.id == settings.active_chat_id else ""
                lines.append(f"{index}. {chat.title} ({_short_chat_id(chat.id)}){active_marker}")
            lines.append("Use /use <number> to switch.")
            return "\n".join(lines)

        if command == "use":
            if not settings.chats:
                return "No chats available."

            selected = _select_chat_by_argument(settings.chats, argument)
            if selected is None:
                return "Invalid chat selector. Use /chats first."
            settings.active_chat_id = selected.id
            await save_settings(settings)
            return f"Switched active chat to: {selected.title}"

        return "Unknown command. Use /help for available commands."

    async def _handle_user_message(self, settings: Settings, text: str) -> str:
        prompt = text.strip()
        if not prompt:
            return ""

        active_chat = _get_active_chat(settings)
        if active_chat is None:
            active_chat = _create_chat_entry(prompt)
            settings.chats.append(active_chat)
            settings.active_chat_id = active_chat.id
        elif not active_chat.messages and active_chat.title.strip().lower() == "new chat":
            active_chat.title = _derive_chat_title(prompt)

        user_timestamp = _timestamp()
        active_chat.messages.append(ChatMessage(role="user", content=prompt, timestamp=user_timestamp))
        await save_settings(settings)

        provider_id = settings.active_provider_id.strip()
        provider_config = settings.provider_configs.get(provider_id)
        if provider_config is None:
            return "Active provider is not configured."

        provider = get_provider(provider_id)
        if provider is None:
            return "Active provider is unavailable."

        history = [
            {"role": message.role, "content": message.content}
            for message in active_chat.messages
            if message.role in {"user", "assistant"} and message.content.strip()
        ]

        runtime_system_prompt = _compose_runtime_system_prompt(settings.bot_name, settings.system_prompt, active_chat.memory_block)

        try:
            orchestration = await generate_with_tools(
                provider=provider,
                settings=settings,
                prompt=prompt,
                system_prompt=runtime_system_prompt,
                model=provider_config.model,
                api_key=provider_config.api_key,
                history=history,
                max_tool_recursion=settings.tool_max_recursion,
                tool_timeout_seconds=settings.tool_timeout_seconds,
            )
            text_response = str(orchestration.get("text", "")).strip()
            used_tokens = orchestration.get("used_tokens")
            used_tools = orchestration.get("used_mcp_tools", [])
            trace_messages = orchestration.get("system_trace_messages", [])
        except Exception as exc:
            text_response = f"Hard error: {exc}"
            used_tokens = None
            used_tools = []
            trace_messages = []

        normalized_tool_usage: list[dict[str, str]] = []
        for entry in used_tools:
            if not isinstance(entry, dict):
                continue
            normalized_tool_usage.append(
                {
                    "mcp_id": str(entry.get("mcp_id", "")),
                    "mcp_label": str(entry.get("mcp_label", "")),
                    "tool_id": str(entry.get("tool_id", "")),
                    "tool_label": str(entry.get("tool_label", "")),
                }
            )

        final_timestamp = _timestamp()
        for entry in trace_messages:
            if not isinstance(entry, dict):
                continue
            content = entry.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            system_type = entry.get("system_type")
            active_chat.messages.append(
                ChatMessage(
                    role="system",
                    content=content.strip(),
                    timestamp=final_timestamp,
                    system_type=system_type if isinstance(system_type, str) else "orchestrator",
                )
            )

        active_chat.messages.append(
            ChatMessage(
                role="assistant",
                content=text_response,
                timestamp=final_timestamp,
                tool_usage=normalized_tool_usage,
                status="done",
            )
        )

        if isinstance(used_tokens, int) and used_tokens > 0:
            active_chat.total_tokens_used = max(0, active_chat.total_tokens_used) + used_tokens
            _add_daily_usage(settings, used_tokens)

        await save_settings(settings)
        return text_response


def _bridge_is_enabled(settings: Settings, token: str) -> bool:
    if not settings.setup_completed or not token:
        return False
    config = settings.integration_configs.get("telegram") or IntegrationConfig()
    return bool(config.enabled)


def _get_bot_token(settings: Settings) -> str:
    config = settings.integration_configs.get("telegram") or IntegrationConfig()
    token = config.params.get("bot_token", "")
    return token.strip() if isinstance(token, str) else ""


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _derive_chat_title(first_message: str, max_len: int = 24) -> str:
    normalized = " ".join(str(first_message).split()).strip()
    if not normalized:
        return "New chat"
    if len(normalized) <= max_len:
        return normalized
    return f"{normalized[:max_len].rstrip()}..."


def _create_chat_entry(first_message: str) -> ChatSession:
    return ChatSession(
        id=str(uuid4()),
        title=_derive_chat_title(first_message),
        type="normal",
        messages=[],
        memory_block="",
        total_tokens_used=0,
        collapse_system_trace=True,
    )


def _get_active_chat(settings: Settings) -> ChatSession | None:
    active_id = settings.active_chat_id.strip()
    if active_id:
        for chat in settings.chats:
            if chat.id == active_id:
                return chat
    if settings.chats:
        settings.active_chat_id = settings.chats[0].id
        return settings.chats[0]
    return None


def _latest_timestamp_or_empty(chat: ChatSession) -> str:
    if not chat.messages:
        return ""
    latest = chat.messages[-1].timestamp
    return latest if isinstance(latest, str) else ""


def _short_chat_id(chat_id: str) -> str:
    if len(chat_id) <= 8:
        return chat_id
    return chat_id[-8:]


def _select_chat_by_argument(chats: list[ChatSession], argument: str) -> ChatSession | None:
    raw = argument.strip()
    if not raw:
        return None

    sorted_chats = sorted(chats, key=_latest_timestamp_or_empty, reverse=True)
    if raw.isdigit():
        index = int(raw)
        if 1 <= index <= len(sorted_chats):
            return sorted_chats[index - 1]

    lowered = raw.lower()
    for chat in chats:
        if chat.id.lower().endswith(lowered) or chat.id.lower() == lowered:
            return chat
    return None


def _parse_command(text: str, bot_username: str) -> tuple[str, str]:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return "", ""

    first_token, _, remainder = stripped.partition(" ")
    command_token = first_token[1:]
    command_name = command_token
    command_target = ""
    if "@" in command_token:
        command_name, command_target = command_token.split("@", 1)

    normalized_name = command_name.strip().lower()
    if not normalized_name:
        return "", ""

    if command_target and bot_username and command_target.strip().lower() != bot_username:
        return "", ""

    return normalized_name, remainder.strip()


def _is_group_message_addressed_to_bot(message: dict[str, Any], bot_username: str, bot_id: int) -> bool:
    text = message.get("text")
    if not isinstance(text, str) or not text:
        return False

    entities = message.get("entities")
    if isinstance(entities, list) and bot_username:
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            entity_type = entity.get("type")
            offset = entity.get("offset")
            length = entity.get("length")
            if not isinstance(offset, int) or not isinstance(length, int):
                continue
            if offset < 0 or length <= 0 or offset + length > len(text):
                continue

            entity_text = text[offset : offset + length].strip().lower()
            if entity_type == "mention" and entity_text == f"@{bot_username}":
                return True
            if entity_type == "bot_command" and entity_text.startswith("/"):
                if "@" in entity_text and entity_text.split("@", 1)[1] == bot_username:
                    return True

    reply_to = message.get("reply_to_message")
    if isinstance(reply_to, dict):
        reply_from = reply_to.get("from")
        if isinstance(reply_from, dict):
            reply_from_id = reply_from.get("id")
            if isinstance(reply_from_id, int) and bot_id > 0 and reply_from_id == bot_id:
                return True

    return False


def _compose_runtime_system_prompt(bot_name: str, system_prompt: str, memory_block: str = "") -> str:
    invisible_context = (
        f"You are Krill assistant named '{bot_name}'. "
        f"This is the system prompt your user provided: {system_prompt}"
    )
    if memory_block.strip():
        invisible_context = f"{invisible_context}\n\nCompacted conversation memory:\n{memory_block.strip()}"
    return invisible_context


def _add_daily_usage(settings: Settings, tokens_to_add: int) -> None:
    if tokens_to_add <= 0:
        return
    date_key = datetime.now(timezone.utc).date().isoformat()
    for entry in settings.daily_token_usage:
        if entry.date == date_key:
            entry.tokens += tokens_to_add
            return
    settings.daily_token_usage.append(DailyTokenUsage(date=date_key, tokens=tokens_to_add))


def _today_token_usage(settings: Settings) -> int:
    date_key = datetime.now(timezone.utc).date().isoformat()
    for entry in settings.daily_token_usage:
        if entry.date == date_key:
            return max(0, int(entry.tokens))
    return 0


def _chunk_telegram_text(text: str, max_len: int = 3500) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, max_len)
        if split_at <= 0:
            split_at = remaining.rfind(" ", 0, max_len)
        if split_at <= 0:
            split_at = max_len
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].lstrip()
    return [chunk for chunk in chunks if chunk]
