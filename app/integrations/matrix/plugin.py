"""Matrix integration plugin lifecycle."""

from __future__ import annotations

from app.integrations.base import IntegrationConfigField, IntegrationPlugin

from .config import CONFIG_FIELDS, verify_matrix_config
from .worker import MatrixBridgeWorker


class MatrixIntegration(IntegrationPlugin):
    integration_id = "matrix"
    display_name = "Matrix"
    description = "Connects a self-hosted Matrix bot to Krill rooms and direct chats."
    config_fields: list[IntegrationConfigField] = CONFIG_FIELDS

    def __init__(self) -> None:
        self._worker = MatrixBridgeWorker()

    async def verify(self, params: dict[str, str]) -> tuple[bool, str]:
        return await verify_matrix_config(params)

    def start(self) -> None:
        self._worker.start()

    async def stop(self) -> None:
        await self._worker.stop()
