from app.integrations.base import IntegrationConfigField, IntegrationPlugin

from .config import CONFIG_FIELDS, verify_telegram_config
from .worker import TelegramBridgeWorker


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
