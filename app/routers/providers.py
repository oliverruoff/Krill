"""Provider management routes: listing and verification."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..model_commands import execute_model_command, parse_model_chat_command
from ..providers import get_provider, get_provider_options, is_supported_provider

router = APIRouter()


class ModelOption(BaseModel):
    id: str
    label: str
    token_limit: int


class ProviderOption(BaseModel):
    id: str
    label: str
    api_key_url: str
    auth_mode: str = "api_key"
    models: list[ModelOption]


class VerifyProviderRequest(BaseModel):
    provider_id: str
    model: str
    api_key: str


class VerifyProviderResponse(BaseModel):
    ok: bool
    detail: str


class ModelCommandExecuteRequest(BaseModel):
    message: str = Field(default="", max_length=200)


@router.get("/api/providers", response_model=list[ProviderOption])
async def get_providers() -> list[dict[str, object]]:
    return get_provider_options()


@router.post("/api/providers/model-command")
async def execute_model_chat_command(payload: ModelCommandExecuteRequest) -> dict[str, object]:
    parsed = parse_model_chat_command(payload.message)
    if parsed is None:
        raise HTTPException(status_code=422, detail="Unsupported model command.")

    result = await execute_model_command(parsed.argument)
    settings_payload = result.settings.model_dump() if result.settings is not None else None
    return {
        "ok": result.ok,
        "text": result.text,
        "command_name": result.command_name,
        "provider_id": result.provider_id,
        "model_id": result.model_id,
        "settings": settings_payload,
    }


@router.post("/api/providers/verify", response_model=VerifyProviderResponse)
async def verify_provider(payload: VerifyProviderRequest) -> VerifyProviderResponse:
    if not is_supported_provider(payload.provider_id):
        raise HTTPException(status_code=422, detail="Unsupported LLM provider.")

    if not payload.model.strip():
        raise HTTPException(status_code=422, detail="Model is required.")

    provider = get_provider(payload.provider_id)
    if provider is None:
        raise HTTPException(status_code=422, detail="Provider not found.")

    # For OAuth providers with no api_key (credentials not yet obtained), skip verification.
    # User must complete OAuth flow first; model selection can be changed without full verification.
    auth_mode = getattr(provider, "auth_mode", "api_key") or "api_key"
    if auth_mode == "oauth" and not payload.api_key.strip():
        return VerifyProviderResponse(ok=True, detail="OAuth provider selected. Complete OAuth flow to activate.")

    ok, detail = await provider.verify(payload.model, payload.api_key)
    if not ok:
        raise HTTPException(status_code=422, detail=detail)

    return VerifyProviderResponse(ok=True, detail=detail)
