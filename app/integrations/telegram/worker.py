"""Telegram polling worker with owner checks and ephemeral Telegram chat sessions."""

import asyncio
import contextlib
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.chat_engine import generate_chat_response
from app.config import ChatMessage, ChatSession, IntegrationConfig, Settings, load_settings, save_settings
from app.integrations.chat_runtime import build_model_history, ensure_runtime_context_seed, is_over_context_threshold
from app.providers import get_provider, get_provider_model_limit
from app.providers.resilience import generate_with_retries
from app.providers.vision import analyze_image
from app.memory_extraction import register_completed_turn, register_user_message_and_maybe_extract
from app.shared_files import get_shared_file_entry
from app.usage import add_daily_usage, get_today_token_usage

from .client import (
    telegram_download_file_bytes,
    telegram_send_document,
    telegram_get_file_path,
    telegram_get_me,
    telegram_get_updates,
    telegram_send_audio,
    telegram_send_message,
)
from .utils import chunk_telegram_text, markdown_to_html


TELEGRAM_POLL_TIMEOUT_SECONDS = 25
TELEGRAM_DRAIN_BATCH_TIMEOUT_SECONDS = 0
TELEGRAM_DRAIN_MAX_BATCHES = 40
TELEGRAM_UPDATES_PER_CYCLE = 5
TELEGRAM_CONTEXT_WINDOW_WARNING = (
    "Heads up: this chat is above 75% of the model context window. "
    "Consider /new to start a fresh chat."
)


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
        if not isinstance(chat, dict) or not isinstance(sender, dict):
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
            settings.telegram_state.owner_chat_id = str(chat_id)
            await save_settings(settings)
            owner_user_id = str(sender_id)

        if str(sender_id) != owner_user_id:
            return

        owner_chat_id = settings.telegram_state.owner_chat_id.strip()
        if owner_chat_id != str(chat_id):
            settings.telegram_state.owner_chat_id = str(chat_id)
            await save_settings(settings)

        is_group = chat_type in {"group", "supergroup"}
        if is_group and not _is_group_message_addressed_to_bot(message, bot_username, bot_id):
            return

        text = message.get("text")
        caption = message.get("caption")
        prompt_text = text if isinstance(text, str) else (caption if isinstance(caption, str) else "")

        try:
            image_payload = await self._extract_message_image(token, message)
        except Exception as exc:
            # Error messages: escape for MarkdownV2 (no markdown expected)
            error_text = _escape_markdown_v2(f"Image handling failed: {exc}")
            await asyncio.to_thread(telegram_send_message, token, chat_id, error_text, "MarkdownV2")
            return

        command, command_arg = _parse_command(prompt_text, bot_username)
        if command:
            response_text = await self._handle_command(command, command_arg, settings)
            if response_text:
                # Command responses: escape for MarkdownV2 (plain text, no markdown)
                escaped_response = _escape_markdown_v2(response_text)
                await asyncio.to_thread(telegram_send_message, token, chat_id, escaped_response, "MarkdownV2")
            return

        response_text = await self._handle_user_message(settings, prompt_text, image=image_payload)
        if response_text:
            # Extract TTS audio URLs before sending text
            tts_audio_files = _extract_tts_audio_files(response_text)
            shared_file_tokens = _extract_shared_file_tokens(response_text)
            clean_text = _strip_tts_audio_urls(response_text)
            clean_text = _strip_shared_file_urls(clean_text)
            if clean_text.strip():
                for chunk in chunk_telegram_text(clean_text):
                    # LLM responses: convert markdown to HTML
                    html_chunk = markdown_to_html(chunk)
                    await asyncio.to_thread(telegram_send_message, token, chat_id, html_chunk, "HTML")
            for shared_token in shared_file_tokens:
                try:
                    shared_payload = await _read_shared_file_payload(shared_token)
                    if shared_payload is None:
                        continue
                    payload_bytes = shared_payload.get("content_bytes")
                    payload_filename = str(shared_payload.get("filename", "file.bin") or "file.bin")
                    payload_mime = str(shared_payload.get("mime_type", "application/octet-stream") or "application/octet-stream")
                    if not isinstance(payload_bytes, bytes):
                        continue
                    await asyncio.to_thread(
                        telegram_send_document,
                        token,
                        chat_id,
                        payload_bytes,
                        payload_filename,
                        None,
                        None,
                        payload_mime,
                    )
                except Exception:
                    pass
            # Send any TTS audio files as Telegram audio messages
            for audio_filename in tts_audio_files:
                try:
                    audio_bytes = _read_tts_audio_file(audio_filename)
                    if audio_bytes:
                        await asyncio.to_thread(
                            telegram_send_audio, token, chat_id, audio_bytes, audio_filename,
                        )
                except Exception:
                    pass

    async def _extract_message_image(self, token: str, message: dict[str, Any]) -> dict[str, object] | None:
        photo = message.get("photo")
        selected_file_id = ""
        mime_type = "image/jpeg"

        if isinstance(photo, list) and photo:
            best = None
            best_size = -1
            for item in photo:
                if not isinstance(item, dict):
                    continue
                file_id = item.get("file_id")
                if not isinstance(file_id, str) or not file_id.strip():
                    continue
                width = int(item.get("width", 0)) if isinstance(item.get("width"), int) else 0
                height = int(item.get("height", 0)) if isinstance(item.get("height"), int) else 0
                score = width * height
                if score > best_size:
                    best_size = score
                    best = file_id.strip()
            if isinstance(best, str) and best:
                selected_file_id = best

        if not selected_file_id:
            document = message.get("document")
            if isinstance(document, dict):
                file_id = document.get("file_id")
                mime = str(document.get("mime_type", "")).strip().lower()
                if isinstance(file_id, str) and file_id.strip() and mime.startswith("image/"):
                    selected_file_id = file_id.strip()
                    mime_type = mime

        if not selected_file_id:
            return None

        file_path = await asyncio.to_thread(telegram_get_file_path, token, selected_file_id)
        image_bytes = await asyncio.to_thread(telegram_download_file_bytes, token, file_path)
        if not image_bytes:
            return None
        if len(image_bytes) > 10 * 1024 * 1024:
            raise RuntimeError("Telegram image exceeds 10MB limit.")
        return {
            "mime_type": mime_type,
            "content_bytes": image_bytes,
            "telegram_file_id": selected_file_id,
        }

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
            context_tokens = _estimate_chat_context_tokens(active)
            provider_id = settings.active_provider_id.strip()
            provider_config = settings.provider_configs.get(provider_id)
            model_id = provider_config.model.strip() if provider_config is not None else ""
            token_limit = get_provider_model_limit(provider_id, model_id) if provider_id and model_id else None
            usage_line = f"Session context: {context_tokens}"
            if isinstance(token_limit, int) and token_limit > 0:
                used_percent = round((context_tokens / token_limit) * 100)
                if context_tokens > 0 and used_percent == 0:
                    used_percent = 1
                usage_line = f"Session context: {context_tokens} / {token_limit} ({used_percent}%)"
            daily_tokens = get_today_token_usage(settings)
            return f"Usage\n{usage_line}\nToday tokens: {daily_tokens}"

        if command == "help":
            return (
                "Available commands:\n"
                "/new - Create and switch to a new chat\n"
                "/chats - List recent Telegram chats\n"
                "/use <number> - Switch active Telegram chat\n"
                "/status - Show Telegram chat status\n"
                "/where - Alias for /status\n"
                "/usage - Show chat and daily token usage\n"
                "/compaction - Compact active chat and start fresh\n"
                "/help - Show this help"
            )

        if command == "compaction":
            active = _get_active_chat(self._telegram_chats, self._active_chat_id)
            self._active_chat_id = active.id if active is not None else ""
            if active is None:
                return "No active chat available to compact."

            try:
                compacted_memory, used_tokens = await _compact_telegram_chat(settings, active)
            except Exception as exc:
                return f"Compaction failed: {exc}"

            compacted_text = compacted_memory.strip()
            if not compacted_text:
                return "Compaction failed: Provider returned empty compact memory."

            new_chat = _create_chat_entry(f"{active.title} compacted")
            new_chat.memory_block = compacted_text
            ensure_runtime_context_seed(new_chat, settings)
            new_chat.messages.append(
                ChatMessage(
                    role="system",
                    content=f"Compacted memory\n\n{compacted_text}",
                    timestamp=_timestamp(),
                    system_type="memory_compaction",
                )
            )
            self._telegram_chats.append(new_chat)
            self._active_chat_id = new_chat.id

            used_suffix = f"\nCompaction tokens used: {used_tokens}" if isinstance(used_tokens, int) and used_tokens > 0 else ""
            return (
                f"Compaction complete.\n"
                f"New active chat: {new_chat.title} ({_short_chat_id(new_chat.id)})"
                f"{used_suffix}"
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

    async def _handle_user_message(self, settings: Settings, text: str, *, image: dict[str, object] | None = None) -> str:
        prompt = text.strip()
        if not prompt and image is None:
            return ""

        active_chat = _get_active_chat(self._telegram_chats, self._active_chat_id)
        if active_chat is None:
            active_chat = _create_chat_entry(prompt)
            self._telegram_chats.append(active_chat)
            self._active_chat_id = active_chat.id
        elif not active_chat.messages and active_chat.title.strip().lower() == "new chat":
            active_chat.title = _derive_chat_title(prompt)

        user_timestamp = _timestamp()
        user_content = prompt
        if image is not None:
            user_content = f"{user_content}\n\n[Image attached]".strip() if user_content else "[Image attached]"
        active_chat.messages.append(ChatMessage(role="user", content=user_content, timestamp=user_timestamp))
        await register_user_message_and_maybe_extract(
            source_channel="telegram",
            source_chat_id=active_chat.id,
        )

        ensure_runtime_context_seed(active_chat, settings)
        image_tokens: int | None = None
        image_analysis_for_reply = ""
        if image is not None:
            provider_id = settings.active_provider_id.strip()
            provider_config = settings.provider_configs.get(provider_id)
            model_id = provider_config.model.strip() if provider_config is not None else ""
            api_key = provider_config.api_key if provider_config is not None else ""
            image_bytes = image.get("content_bytes") if isinstance(image, dict) else None
            image_mime = str(image.get("mime_type", "")).strip() if isinstance(image, dict) else ""
            if not isinstance(image_bytes, (bytes, bytearray)) or not image_mime.startswith("image/"):
                return "Image analysis failed: Invalid image payload from Telegram."
            try:
                analysis_text, image_tokens = await analyze_image(
                    provider_id=provider_id,
                    model=model_id,
                    api_key=api_key,
                    image_bytes=bytes(image_bytes),
                    mime_type=image_mime,
                    prompt=_image_analysis_prompt(prompt),
                )
            except Exception as exc:
                return f"Image analysis failed: {exc}"

            active_chat.messages.append(
                ChatMessage(
                    role="assistant",
                    content=f"Image analysis: {analysis_text.strip()}",
                    timestamp=_timestamp(),
                    status="done",
                )
            )
            image_analysis_for_reply = analysis_text.strip()

        history = build_model_history(active_chat)
        final_prompt = prompt
        if image is not None:
            analysis_context = str(active_chat.messages[-1].content).replace("Image analysis:", "", 1).strip()
            if final_prompt:
                final_prompt = f"{final_prompt}\n\nImage analysis:\n{analysis_context}"
            else:
                final_prompt = f"The user sent an image without text. Use this image analysis:\n{analysis_context}"

        try:
            engine_result, token_limit = await generate_chat_response(
                settings=settings,
                message=final_prompt,
                history=history,
                memory_block=active_chat.memory_block,
                source_channel="telegram",
                source_chat_id=active_chat.id,
            )
            text_response = engine_result["text"]
            used_tokens = engine_result["used_tokens"]
            used_tools = engine_result["used_mcp_tools"]
            trace_messages = engine_result["system_trace_messages"]
            if is_over_context_threshold(used_tokens, token_limit, threshold=0.75):
                text_response = f"{text_response}\n\n{TELEGRAM_CONTEXT_WINDOW_WARNING}" if text_response else TELEGRAM_CONTEXT_WINDOW_WARNING
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
            user_message=prompt or "[Image attached]",
            assistant_message=text_response,
        )

        if isinstance(used_tokens, int) and used_tokens > 0:
            active_chat.total_tokens_used = max(0, active_chat.total_tokens_used) + used_tokens
            add_daily_usage(settings, used_tokens)
        if isinstance(image_tokens, int) and image_tokens > 0:
            active_chat.total_tokens_used = max(0, active_chat.total_tokens_used) + image_tokens
            add_daily_usage(settings, image_tokens)
        if (isinstance(used_tokens, int) and used_tokens > 0) or (isinstance(image_tokens, int) and image_tokens > 0):
            await save_settings(settings)

        if image_analysis_for_reply:
            return f"Image analysis: {image_analysis_for_reply}\n\n{text_response}".strip()
        return text_response


def _bridge_is_enabled(settings: Settings, token: str) -> bool:
    if not settings.setup_completed or not token:
        return False
    config = settings.integration_configs.get("telegram") or IntegrationConfig()
    return bool(config.enabled)


def _escape_markdown_v2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2 parse_mode.
    
    MarkdownV2 requires escaping these 18 special characters: _*[]()~`>#+-=|{}.!
    Each must be prefixed with a backslash.
    
    Note: This is kept for error messages. For LLM responses, use HTML mode instead.
    """
    special_chars = "_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{char}" if char in special_chars else char for char in text)


_TTS_URL_PATTERN = r"/api/tts/audio/([a-f0-9\-]+\.mp3)"
_SHARED_FILE_URL_PATTERN = r"(?:https?://[^\s)\]]+)?/api/files/shared/([A-Za-z0-9_-]{10,200})"


def _extract_tts_audio_files(text: str) -> list[str]:
    """Return list of TTS audio filenames found in the response text."""
    import re
    return re.findall(_TTS_URL_PATTERN, text)


def _extract_shared_file_tokens(text: str) -> list[str]:
    import re

    matches = re.findall(_SHARED_FILE_URL_PATTERN, text)
    deduped: list[str] = []
    for token in matches:
        normalized = str(token or "").strip()
        if not normalized or normalized in deduped:
            continue
        deduped.append(normalized)
    return deduped


def _strip_tts_audio_urls(text: str) -> str:
    """Remove TTS audio URL lines from text so Telegram gets clean prose."""
    import re
    # Remove lines that contain only a TTS audio URL (possibly in markdown link syntax)
    cleaned = re.sub(
        r"(?:^|\n)\s*(?:\[[^\]]*\]\()?/api/tts/audio/[a-f0-9\-]+\.mp3\)?\s*(?:\n|$)",
        "\n",
        text,
    )
    # Also remove inline TTS URLs that may appear mid-text
    cleaned = re.sub(
        r"(?:\[[^\]]*\]\()?/api/tts/audio/[a-f0-9\-]+\.mp3\)?",
        "",
        cleaned,
    )
    return cleaned.strip()


def _strip_shared_file_urls(text: str) -> str:
    import re

    cleaned = re.sub(
        r"(?:^|\n)\s*(?:\[[^\]]*\]\()?(?:https?://[^\s)\]]+)?/api/files/shared/[A-Za-z0-9_-]{10,200}\)?\s*(?:\n|$)",
        "\n",
        text,
    )
    cleaned = re.sub(
        r"(?:\[[^\]]*\]\()?(?:https?://[^\s)\]]+)?/api/files/shared/[A-Za-z0-9_-]{10,200}\)?",
        "",
        cleaned,
    )
    return cleaned.strip()


async def _read_shared_file_payload(token: str) -> dict[str, object] | None:
    entry = await get_shared_file_entry(token)
    if entry is None:
        return None

    from pathlib import Path

    resolved = Path(str(entry.get("path", ""))).expanduser().resolve()
    if not resolved.exists() or not resolved.is_file():
        return None

    try:
        content_bytes = await asyncio.to_thread(resolved.read_bytes)
    except Exception:
        return None

    if not content_bytes:
        return None

    return {
        "content_bytes": content_bytes,
        "filename": str(entry.get("filename", resolved.name) or resolved.name),
        "mime_type": str(entry.get("media_type", "application/octet-stream") or "application/octet-stream"),
    }


def _read_tts_audio_file(filename: str) -> bytes | None:
    """Read a TTS audio file from the data directory. Returns None if not found."""
    import re
    from app.config import DATA_DIR
    if not re.fullmatch(r"[a-f0-9\-]+\.mp3", filename):
        return None
    path = (DATA_DIR / "tts_audio" / filename).resolve()
    tts_dir = (DATA_DIR / "tts_audio").resolve()
    if not str(path).startswith(str(tts_dir)):
        return None
    if not path.is_file():
        return None
    return path.read_bytes()


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




def _image_analysis_prompt(user_message: str) -> str:
    message = user_message.strip()
    if message:
        return (
            "Analyze this image for the user's request. "
            "Provide concise factual details, visible text (OCR), and relevant context. "
            "Do not invent details.\n\n"
            f"User request: {message}"
        )
    return (
        "Analyze this image and provide concise factual details, visible text (OCR), "
        "and relevant context. Do not invent details."
    )


def _estimate_chat_context_tokens(chat: ChatSession | None) -> int:
    if chat is None:
        return 0

    memory_block = chat.memory_block if isinstance(chat.memory_block, str) else ""
    memory_tokens = max(0, (len(memory_block) + 3) // 4)
    history_tokens = 0
    for item in chat.messages:
        role = item.role if isinstance(item.role, str) else ""
        if role not in {"user", "assistant"}:
            continue
        content = item.content if isinstance(item.content, str) else ""
        history_tokens += max(0, (len(role) + len(content) + 3) // 4)

    return max(0, memory_tokens + history_tokens)


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


def _build_compaction_history(messages: list[ChatMessage]) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for message in messages:
        if message.role not in {"user", "assistant"}:
            continue
        content = message.content.strip()
        if not content:
            continue
        history.append({"role": message.role, "content": content})
    return history


async def _compact_telegram_chat(settings: Settings, chat: ChatSession) -> tuple[str, int | None]:
    if not settings.setup_completed:
        raise RuntimeError("Setup is not complete.")

    active_provider_id = settings.active_provider_id.strip()
    provider_config = settings.provider_configs.get(active_provider_id)
    if provider_config is None:
        raise RuntimeError("Active provider is not configured.")

    provider = get_provider(active_provider_id)
    if provider is None:
        raise RuntimeError("Active provider is unavailable.")

    model_id = provider_config.model.strip()
    if not model_id:
        raise RuntimeError("Active model is not configured.")

    api_key = provider_config.api_key.strip()
    if not api_key:
        raise RuntimeError("Provider API key is missing.")

    history = _build_compaction_history(chat.messages)
    previous_memory = chat.memory_block.strip()
    if not history and not previous_memory:
        raise RuntimeError("Nothing to compact in the active chat.")

    token_limit = get_provider_model_limit(active_provider_id, model_id) or 0
    compacted_text, used_tokens = await generate_with_retries(
        provider=provider,
        prompt=_build_compaction_prompt(previous_memory, token_limit),
        system_prompt=_compaction_system_prompt(),
        model=model_id,
        api_key=api_key,
        history=history,
    )
    return compacted_text, used_tokens
