"""Integration management routes: listing, verification, and status."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import IntegrationConfig, load_settings
from ..integrations import (
    get_integration,
    get_integration_options,
    is_supported_integration,
)
from ..integrations.whatsapp.sidecar_manager import status as whatsapp_status

router = APIRouter()


class VerifyIntegrationRequest(BaseModel):
    integration_id: str
    params: dict[str, str] = {}


class VerifyIntegrationResponse(BaseModel):
    ok: bool
    detail: str


class IntegrationStatusResponse(BaseModel):
    statuses: dict[str, dict[str, object]]


@router.get("/api/integrations")
async def get_integrations() -> list[dict[str, object]]:
    return get_integration_options()


@router.post("/api/integrations/verify", response_model=VerifyIntegrationResponse)
async def verify_integration(payload: VerifyIntegrationRequest) -> VerifyIntegrationResponse:
    if not is_supported_integration(payload.integration_id):
        raise HTTPException(status_code=422, detail="Unsupported integration.")

    integration = get_integration(payload.integration_id)
    if integration is None:
        raise HTTPException(status_code=422, detail="Integration not found.")

    ok, detail = await integration.verify(payload.params)
    if not ok:
        raise HTTPException(status_code=422, detail=detail)

    return VerifyIntegrationResponse(ok=True, detail=detail)


@router.get("/api/integrations/status", response_model=IntegrationStatusResponse)
async def get_integration_status() -> IntegrationStatusResponse:
    settings = await load_settings()
    telegram_config = settings.integration_configs.get("telegram") or IntegrationConfig()
    whatsapp_config = settings.integration_configs.get("whatsapp") or IntegrationConfig()
    token_value = telegram_config.params.get("bot_token", "")
    token_configured = isinstance(token_value, str) and bool(token_value.strip())
    owner_user_id = settings.telegram_state.owner_user_id.strip()
    owner_chat_id = settings.telegram_state.owner_chat_id.strip()

    whatsapp_state = "disabled"
    whatsapp_connected = False
    if bool(whatsapp_config.enabled):
        try:
            runtime = await whatsapp_status()
            whatsapp_state = str(runtime.get("status", "")).strip().lower() or "unknown"
            whatsapp_connected = whatsapp_state == "ready"
        except Exception:
            whatsapp_state = "unavailable"

    return IntegrationStatusResponse(
        statuses={
            "telegram": {
                "enabled": bool(telegram_config.enabled),
                "token_configured": token_configured,
                "owner_user_id": owner_user_id,
                "owner_chat_id": owner_chat_id,
                "owner_bound": bool(owner_user_id),
            },
            "whatsapp": {
                "enabled": bool(whatsapp_config.enabled),
                "connected": whatsapp_connected,
                "state": whatsapp_state,
            },
        }
    )
