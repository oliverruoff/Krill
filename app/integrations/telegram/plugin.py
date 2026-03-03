"""Telegram integration plugin wiring verify/start/stop lifecycle behavior."""

from __future__ import annotations

import asyncio

from app.config import IntegrationConfig, Settings, TimedJob
from app.integrations.base import IntegrationConfigField, IntegrationPlugin

from .client import telegram_send_message
from .config import CONFIG_FIELDS, verify_telegram_config
from .utils import chunk_telegram_text, markdown_to_html
from .worker import TelegramBridgeWorker

_TIMED_JOB_TITLE_MAX_LEN = 120


class TelegramIntegration(IntegrationPlugin):
    integration_id = "telegram"
    display_name = "Telegram"
    description = "Connects Telegram bot updates to Krill chats."
    config_fields: list[IntegrationConfigField] = CONFIG_FIELDS

    def __init__(self) -> None:
        self._worker = TelegramBridgeWorker()

    async def verify(self, params: dict[str, str]) -> tuple[bool, str]:
        return await verify_telegram_config(params)

    def start(self) -> None:
        self._worker.start()

    async def stop(self) -> None:
        await self._worker.stop()

    # ------------------------------------------------------------------
    # Timed job dispatch
    # ------------------------------------------------------------------

    def _get_target(self, settings: Settings) -> tuple[str, int] | None:
        """Return (bot_token, owner_chat_id) or None if Telegram is not ready."""
        config = settings.integration_configs.get("telegram") or IntegrationConfig()
        if not config.enabled:
            return None
        token = str(config.params.get("bot_token", "")).strip()
        if not token:
            return None
        raw_chat_id = settings.telegram_state.owner_chat_id.strip()
        if not raw_chat_id:
            raw_chat_id = settings.telegram_state.owner_user_id.strip()
        if not raw_chat_id:
            return None
        try:
            chat_id = int(raw_chat_id)
        except ValueError:
            return None
        return token, chat_id

    async def dispatch_timed_job(
        self,
        job: TimedJob,
        text: str,
        settings: Settings,
    ) -> None:
        """Send timed job output to the Telegram owner chat."""
        target = self._get_target(settings)
        if target is None:
            return
        token, chat_id = target
        title = " ".join(job.title.split()).strip()[:_TIMED_JOB_TITLE_MAX_LEN]
        decorated = f"{title}\n\n{text}" if title else text
        for chunk in chunk_telegram_text(decorated):
            html_chunk = markdown_to_html(chunk)
            await asyncio.to_thread(telegram_send_message, token, chat_id, html_chunk, "HTML")

    def get_timed_job_channel_option(
        self,
        settings: Settings,
    ) -> dict[str, object] | None:
        """Return channel picker option for timed jobs UI."""
        available = self._get_target(settings) is not None
        description = (
            "Sends job output to Telegram owner chat."
            if available
            else "Unavailable: enable Telegram, set bot token, and send one owner message first."
        )
        return {
            "id": self.integration_id,
            "label": self.display_name,
            "description": description,
            "available": available,
            "default": False,
        }
