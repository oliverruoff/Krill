"""WhatsApp integration worker polling sidecar events and dispatching orchestrated chats."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import uuid4

from app.chat_engine import generate_chat_response
from app.config import ChatMessage, ChatSession, IntegrationConfig, load_settings, save_settings
from app.integrations.chat_runtime import build_model_history, ensure_runtime_context_seed
from app.memory_extraction import register_completed_turn, register_user_message_and_maybe_extract
from app.usage import add_daily_usage

from .sidecar_manager import parse_allowlist, poll_events, send_message, set_allowlist

LOGGER = logging.getLogger(__name__)


class WhatsAppBridgeWorker:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._seen_event_ids: set[str] = set()

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
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("WhatsApp worker poll failed")
            await asyncio.sleep(2.0)

    async def _poll_once(self) -> None:
        settings = await load_settings()
        integration_config = settings.integration_configs.get("whatsapp") or IntegrationConfig()
        if not integration_config.enabled:
            return

        mcp_config = settings.mcp_configs.get("whatsapp")
        if mcp_config is None or not mcp_config.enabled:
            return

        allowlist = parse_allowlist(mcp_config.params.get("allowed_numbers", ""))
        prompt = str(mcp_config.params.get("automation_prompt", "")).strip()
        if not allowlist or not prompt:
            return

        await set_allowlist(allowlist)

        events = await poll_events()
        for event in events:
            event_id = str(event.get("id", "")).strip()
            if event_id and event_id in self._seen_event_ids:
                continue
            if event_id:
                self._seen_event_ids.add(event_id)
                if len(self._seen_event_ids) > 1000:
                    self._seen_event_ids = set(list(self._seen_event_ids)[-500:])

            number = str(event.get("from_number", "")).strip()
            text = str(event.get("text", "")).strip()
            if not number or number not in allowlist or not text:
                continue

            await self._dispatch_inbound_message(settings, number, text, prompt)

    async def _dispatch_inbound_message(self, settings, number: str, inbound_text: str, prompt: str) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        chat = ChatSession(
            id=str(uuid4()),
            title=f"WhatsApp {number}",
            type="normal",
            messages=[],
            memory_block="",
            total_tokens_used=0,
            collapse_system_trace=True,
        )
        ensure_runtime_context_seed(chat, settings)
        chat.messages.append(
            ChatMessage(
                role="system",
                content=f"Inbound WhatsApp from {number}: {inbound_text}",
                timestamp=now_iso,
                system_type="integration_context",
            )
        )
        chat.messages.append(ChatMessage(role="user", content=prompt, timestamp=now_iso))
        settings.chats.append(chat)
        settings.active_chat_id = chat.id
        await save_settings(settings)

        await register_user_message_and_maybe_extract(source_channel="whatsapp", source_chat_id=chat.id)
        history = build_model_history(chat)
        result, _ = await generate_chat_response(
            settings=settings,
            message=prompt,
            history=history,
            memory_block=chat.memory_block,
            source_channel="whatsapp",
            source_chat_id=chat.id,
            source_request_id=f"whatsapp-{chat.id}",
        )

        final_text = str(result.get("text", "")).strip()
        chat.messages.append(
            ChatMessage(
                role="assistant",
                content=final_text,
                timestamp=datetime.now(timezone.utc).isoformat(),
                status="done",
            )
        )
        used_tokens = result.get("used_tokens")
        if isinstance(used_tokens, int) and used_tokens > 0:
            chat.total_tokens_used += used_tokens
            add_daily_usage(settings, used_tokens)
        await save_settings(settings)

        if final_text:
            try:
                await send_message(number, final_text)
            except Exception:
                LOGGER.exception("WhatsApp auto-reply send failed for %s", number)

        await register_completed_turn(
            source_channel="whatsapp",
            source_chat_id=chat.id,
            user_message=f"Inbound WhatsApp from {number}: {inbound_text}\n\n{prompt}",
            assistant_message=final_text,
        )
