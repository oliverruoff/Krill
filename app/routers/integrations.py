"""Integration management routes: listing, verification, and status."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import IntegrationConfig, MatrixRoomAccess, MatrixUserAccess, load_settings, save_settings
from ..integrations import (
    get_integration,
    get_integration_options,
    is_supported_integration,
)
from ..mcps.registry import get_all_mcps
from ..integrations.matrix.client import matrix_room_name, matrix_whoami
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


class MatrixAccessResponse(BaseModel):
    users: list[MatrixUserAccess] = Field(default_factory=list)
    approved_rooms: list[MatrixRoomAccess] = Field(default_factory=list)
    assistant_allowed_mcp_ids: list[str] = Field(default_factory=list)
    available_mcps: list[dict[str, str]] = Field(default_factory=list)
    bot_user_id: str = ""


class UpdateMatrixAccessRequest(BaseModel):
    users: list[MatrixUserAccess] = Field(default_factory=list)
    approved_rooms: list[MatrixRoomAccess] = Field(default_factory=list)
    assistant_allowed_mcp_ids: list[str] = Field(default_factory=list)


class MatrixRefreshIdentityResponse(BaseModel):
    bot_user_id: str


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
    matrix_config = settings.integration_configs.get("matrix") or IntegrationConfig()
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

    matrix_homeserver = str(matrix_config.params.get("homeserver_url", "")).strip()
    matrix_access_token = str(matrix_config.params.get("access_token", "")).strip()
    matrix_bot_user_id = settings.matrix_state.bot_user_id.strip()

    return IntegrationStatusResponse(
        statuses={
            "matrix": {
                "enabled": bool(matrix_config.enabled),
                "homeserver_configured": bool(matrix_homeserver),
                "access_token_configured": bool(matrix_access_token),
                "connected": bool(matrix_bot_user_id and not settings.matrix_state.last_sync_error.strip()),
                "bot_user_id": matrix_bot_user_id,
                "last_sync_error": settings.matrix_state.last_sync_error.strip(),
                "last_sync_at": settings.matrix_state.last_sync_at.strip(),
                "user_count": len(settings.matrix_state.users),
                "admin_count": len([entry for entry in settings.matrix_state.users if entry.role == "admin_usage"]),
                "approved_room_count": len([entry for entry in settings.matrix_state.approved_rooms if entry.active]),
                "assistant_allowed_mcp_count": len(settings.matrix_state.assistant_allowed_mcp_ids),
            },
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


@router.get("/api/integrations/matrix/access", response_model=MatrixAccessResponse)
async def get_matrix_access() -> MatrixAccessResponse:
    settings = await load_settings()
    available_mcps = [
        {"id": mcp_id, "label": plugin.display_name}
        for mcp_id, plugin in sorted(get_all_mcps().items())
    ]
    return MatrixAccessResponse(
        users=settings.matrix_state.users,
        approved_rooms=settings.matrix_state.approved_rooms,
        assistant_allowed_mcp_ids=settings.matrix_state.assistant_allowed_mcp_ids,
        available_mcps=available_mcps,
        bot_user_id=settings.matrix_state.bot_user_id,
    )


@router.put("/api/integrations/matrix/access", response_model=MatrixAccessResponse)
async def update_matrix_access(payload: UpdateMatrixAccessRequest) -> MatrixAccessResponse:
    settings = await load_settings()
    users_by_mxid: dict[str, MatrixUserAccess] = {}
    for entry in payload.users:
        mxid = entry.mxid.strip()
        if not mxid:
            continue
        users_by_mxid[mxid.lower()] = MatrixUserAccess(
            mxid=mxid,
            role=entry.role,
            note=entry.note.strip(),
        )
    rooms_by_id: dict[str, MatrixRoomAccess] = {}
    for entry in payload.approved_rooms:
        room_id = entry.room_id.strip()
        if not room_id:
            continue
        rooms_by_id[room_id] = MatrixRoomAccess(
            room_id=room_id,
            room_name=entry.room_name.strip(),
            approved_by_mxid=entry.approved_by_mxid.strip(),
            is_direct=bool(entry.is_direct),
            active=bool(entry.active),
        )
    allowed_mcp_ids = sorted({
        mcp_id.strip()
        for mcp_id in payload.assistant_allowed_mcp_ids
        if mcp_id.strip() in get_all_mcps()
    })
    settings.matrix_state.users = sorted(users_by_mxid.values(), key=lambda entry: entry.mxid.lower())
    settings.matrix_state.approved_rooms = sorted(rooms_by_id.values(), key=lambda entry: (entry.room_name or entry.room_id).lower())
    settings.matrix_state.assistant_allowed_mcp_ids = allowed_mcp_ids
    await save_settings(settings)
    return await get_matrix_access()


@router.post("/api/integrations/matrix/refresh-identity", response_model=MatrixRefreshIdentityResponse)
async def refresh_matrix_identity() -> MatrixRefreshIdentityResponse:
    settings = await load_settings()
    matrix_config = settings.integration_configs.get("matrix") or IntegrationConfig()
    homeserver_url = str(matrix_config.params.get("homeserver_url", "")).strip()
    access_token = str(matrix_config.params.get("access_token", "")).strip()
    if not homeserver_url or not access_token:
        raise HTTPException(status_code=422, detail="Matrix homeserver URL and access token are required.")
    try:
        payload = await asyncio.to_thread(matrix_whoami, homeserver_url, access_token)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Matrix identity refresh failed: {exc}") from exc
    bot_user_id = str(payload.get("user_id", "")).strip()
    if not bot_user_id:
        raise HTTPException(status_code=422, detail="Matrix identity refresh failed: user id missing.")
    settings.matrix_state.bot_user_id = bot_user_id
    settings.matrix_state.last_sync_error = ""
    await save_settings(settings)
    return MatrixRefreshIdentityResponse(bot_user_id=bot_user_id)


@router.post("/api/integrations/matrix/resolve-room")
async def resolve_matrix_room(payload: dict[str, str]) -> dict[str, str]:
    settings = await load_settings()
    matrix_config = settings.integration_configs.get("matrix") or IntegrationConfig()
    homeserver_url = str(matrix_config.params.get("homeserver_url", "")).strip()
    access_token = str(matrix_config.params.get("access_token", "")).strip()
    room_id = str(payload.get("room_id", "")).strip()
    if not homeserver_url or not access_token or not room_id:
        raise HTTPException(status_code=422, detail="Matrix homeserver, access token, and room id are required.")
    try:
        room_name = await asyncio.to_thread(matrix_room_name, homeserver_url, access_token, room_id)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Matrix room lookup failed: {exc}") from exc
    return {"room_id": room_id, "room_name": room_name}
