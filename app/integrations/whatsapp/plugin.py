"""WhatsApp integration plugin lifecycle."""

from app.integrations.base import IntegrationPlugin

from .config import CONFIG_FIELDS, verify_whatsapp_config
from .worker import WhatsAppBridgeWorker


class WhatsAppIntegration(IntegrationPlugin):
    integration_id = "whatsapp"
    display_name = "WhatsApp"
    description = "Connects WhatsApp Web inbound messages to orchestrated Gateway chats."
    config_fields = CONFIG_FIELDS

    def __init__(self) -> None:
        self._worker = WhatsAppBridgeWorker()

    async def verify(self, params: dict[str, str]) -> tuple[bool, str]:
        return await verify_whatsapp_config(params)

    def start(self) -> None:
        self._worker.start()

    async def stop(self) -> None:
        await self._worker.stop()
