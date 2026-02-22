"""Registry for runtime integrations such as Telegram."""

from .base import IntegrationPlugin
from .telegram import TelegramIntegration


_INTEGRATIONS: dict[str, IntegrationPlugin] = {
    "telegram": TelegramIntegration(),
}


def get_integration(integration_id: str) -> IntegrationPlugin | None:
    return _INTEGRATIONS.get(integration_id)


def is_supported_integration(integration_id: str) -> bool:
    return integration_id in _INTEGRATIONS


def get_integration_options() -> list[dict[str, object]]:
    options: list[dict[str, object]] = []
    for integration in _INTEGRATIONS.values():
        options.append(
            {
                "id": integration.integration_id,
                "label": integration.display_name,
                "description": integration.description,
                "config_fields": [field.model_dump() for field in integration.config_fields],
            }
        )
    return options


def get_runtime_integrations() -> list[IntegrationPlugin]:
    return list(_INTEGRATIONS.values())
