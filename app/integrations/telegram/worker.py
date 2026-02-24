"""Telegram polling worker with owner checks and ephemeral Telegram chat sessions."""

import asyncio
import contextlib
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.chat_engine import generate_chat_response
from app.config import ChatMessage, ChatSession, IntegrationConfig, Settings, load_settings, save_settings
from app.memory_extraction import register_completed_turn, register_user_message_and_maybe_extract
from app.usage import add_daily_usage, get_today_token_usage

from .client import telegram_get_me, telegram_get_updates, telegram_send_message


TELEGRAM_POLL_TIMEOUT_SECONDS = 25
TELEGRAM_DRAIN_BATCH_TIMEOUT_SECONDS = 0
TELEGRAM_DRAIN_MAX_BATCHES = 40
TELEGRAM_UPDATES_PER_CYCLE = 5


class TelegramBridgeWorker:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._bridge_active = False
        self._last_token = ""
        self._telegram_chats: list[ChatSession] = []
        self._active_chat_id = ""

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
                    self._bridge_active = False
                    self._last_token = ""
                    await asyncio.sleep(2)
                    continue

                if not self._bridge_active or token != self._last_token:
                    await self._drain_pending_updates(token, settings.telegram_state.last_update_id + 1)
                    self._bridge_active = True
                    self._last_token = token
                    settings = await load_settings()

                bot_me = await asyncio.to_thread(telegram_get_me, token)
                bot_result = bot_me.get("result") if isinstance(bot_me, dict) else {}
                bot_username = str(bot_result.get("username", "")).strip().lower() if isinstance(bot_result, dict) else ""
                bot_id = int(bot_result.get("id", 0)) if isinstance(bot_result, dict) else 0

                offset = settings.telegram_state.last_update_id + 1
                updates_payload = await asyncio.to_thread(telegram_get_updates, token, offset, TELEGRAM_POLL_TIMEOUT_SECONDS)
                updates = updates_payload.get("result") if isinstance(updates_payload, dict) else []
                if not isinstance(updates, list) or not updates:
                    continue

                for update in updates[:TELEGRAM_UPDATES_PER_CYCLE]:
                    if not isinstance(update, dict):
                        continue

                    update_id = update.get("update_id")
                    if not isinstance(update_id, int):
                        continue

                    message = update.get("message")
                    if isinstance(message, dict):
                        await self._handle_message(token, message, bot_username, bot_id)

                    await self._store_last_update_id(update_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(2)

    async def _drain_pending_updates(self, token: str, offset: int) -> None:
        next_offset = max(1, offset)
        highest_seen = 0

        for _ in range(TELEGRAM_DRAIN_MAX_BATCHES):
            payload = await asyncio.to_thread(
                telegram_get_updates,
                token,
                next_offset,
                TELEGRAM_DRAIN_BATCH_TIMEOUT_SECONDS,
            )
            updates = payload.get("result") if isinstance(payload, dict) else []
            if not isinstance(updates, list) or not updates:
                break

            for update in updates:
                if not isinstance(update, dict):
                    continue
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    highest_seen = max(highest_seen, update_id)

            if highest_seen > 0:
                next_offset = highest_seen + 1

        if highest_seen > 0:
            await self._store_last_update_id(highest_seen)

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
        if not _bridge_is_enabled(settings, _get_bot_token(settings)):
            return

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
            response_text = await self._handle_command(command, command_arg, settings)
            if response_text:
                await asyncio.to_thread(telegram_send_message, token, chat_id, response_text)
            return

        response_text = await self._handle_user_message(settings, text)
        if response_text:
            for chunk in _chunk_telegram_text(response_text):
                await asyncio.to_thread(telegram_send_message, token, chat_id, chunk)

    async def _handle_command(self, command: str, argument: str, settings: Settings) -> str:
        if command == "new":
            chat = _create_chat_entry("New chat")
            self._telegram_chats.append(chat)
            self._active_chat_id = chat.id
            return f"Started new chat: {chat.title}"

        if command in {"status", "where"}:
            active = _get_active_chat(self._telegram_chats, self._active_chat_id)
            self._active_chat_id = active.id if active is not None else ""
            owner_bound = "yes" if settings.telegram_state.owner_user_id.strip() else "no"
            if active is None:
                return f"Status\nOwner bound: {owner_bound}\nActive chat: none"
            return f"Status\nOwner bound: {owner_bound}\nActive chat: {active.title} ({_short_chat_id(active.id)})"

        if command == "usage":
            active = _get_active_chat(self._telegram_chats, self._active_chat_id)
            self._active_chat_id = active.id if active is not None else ""
            chat_tokens = active.total_tokens_used if active is not None else 0
            daily_tokens = get_today_token_usage(settings)
            return f"Usage\nChat tokens: {chat_tokens}\nToday tokens: {daily_tokens}"

        if command == "help":
            return (
                "Available commands:\n"
                "/new - Create and switch to a new chat\n"
                "/chats - List recent Telegram chats\n"
                "/use <number> - Switch active Telegram chat\n"
                "/status - Show Telegram chat status\n"
                "/where - Alias for /status\n"
                "/usage - Show chat and daily token usage\n"
                "/help - Show this help"
            )

        if command == "chats":
            if not self._telegram_chats:
                return "No Telegram chats yet."
            lines = ["Recent Telegram chats:"]
            sorted_chats = sorted(self._telegram_chats, key=_latest_timestamp_or_empty, reverse=True)
            for index, chat in enumerate(sorted_chats[:10], start=1):
                active_marker = " *" if chat.id == self._active_chat_id else ""
                lines.append(f"{index}. {chat.title} ({_short_chat_id(chat.id)}){active_marker}")
            lines.append("Use /use <number> to switch.")
            return "\n".join(lines)

        if command == "use":
            if not self._telegram_chats:
                return "No Telegram chats available."

            selected = _select_chat_by_argument(self._telegram_chats, argument)
            if selected is None:
                return "Invalid chat selector. Use /chats first."
            self._active_chat_id = selected.id
            return f"Switched active chat to: {selected.title}"

        return "Unknown command. Use /help for available commands."

    async def _handle_user_message(self, settings: Settings, text: str) -> str:
        prompt = text.strip()
        if not prompt:
            return ""

        active_chat = _get_active_chat(self._telegram_chats, self._active_chat_id)
        if active_chat is None:
            active_chat = _create_chat_entry(prompt)
            self._telegram_chats.append(active_chat)
            self._active_chat_id = active_chat.id
        elif not active_chat.messages and active_chat.title.strip().lower() == "new chat":
            active_chat.title = _derive_chat_title(prompt)

        user_timestamp = _timestamp()
        active_chat.messages.append(ChatMessage(role="user", content=prompt, timestamp=user_timestamp))
        await register_user_message_and_maybe_extract(
            source_channel="telegram",
            source_chat_id=active_chat.id,
        )

        history = [
            {"role": message.role, "content": message.content}
            for message in active_chat.messages
            if message.role in {"user", "assistant"} and message.content.strip()
        ]

        try:
            engine_result, _ = await generate_chat_response(
                settings=settings,
                message=prompt,
                history=history,
                memory_block=active_chat.memory_block,
            )
            text_response = engine_result["text"]
            used_tokens = engine_result["used_tokens"]
            used_tools = engine_result["used_mcp_tools"]
            trace_messages = engine_result["system_trace_messages"]
        except Exception as exc:
            text_response = f"Hard error: {exc}"
            used_tokens = None
            used_tools = []
            trace_messages = []

        final_timestamp = _timestamp()
        for entry in trace_messages:
            content = entry.get("content") if isinstance(entry, dict) else None
            if not isinstance(content, str) or not content.strip():
                continue
            system_type = entry.get("system_type") if isinstance(entry, dict) else None
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
                tool_usage=[
                    {
                        "mcp_id": str(entry.get("mcp_id", "")),
                        "mcp_label": str(entry.get("mcp_label", "")),
                        "tool_id": str(entry.get("tool_id", "")),
                        "tool_label": str(entry.get("tool_label", "")),
                    }
                    for entry in used_tools
                    if isinstance(entry, dict)
                ],
                status="done",
            )
        )

        await register_completed_turn(
            source_channel="telegram",
            source_chat_id=active_chat.id,
            user_message=prompt,
            assistant_message=text_response,
        )

        if isinstance(used_tokens, int) and used_tokens > 0:
            active_chat.total_tokens_used = max(0, active_chat.total_tokens_used) + used_tokens
            add_daily_usage(settings, used_tokens)
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


def _get_active_chat(chats: list[ChatSession], active_chat_id: str) -> ChatSession | None:
    active_id = active_chat_id.strip()
    if active_id:
        for chat in chats:
            if chat.id == active_id:
                return chat
    return chats[0] if chats else None


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
