"""WhatsApp integration configuration and verification helpers."""

from app.integrations.base import IntegrationConfigField

from .sidecar_manager import connect, status


CONFIG_FIELDS: list[IntegrationConfigField] = []


async def verify_whatsapp_config(params: dict[str, str]) -> tuple[bool, str]:
    del params
    await connect()
    current = await status()
    state = str(current.get("status", "")).strip().lower()
    if state == "ready":
        return True, "WhatsApp connected and ready."
    if state in {"qr", "authenticated", "initializing"}:
        return True, "WhatsApp sidecar reachable. Finish QR login if needed."
    return False, f"WhatsApp sidecar state: {state or 'unknown'}"
