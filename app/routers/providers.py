"""Provider management routes: listing and verification."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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


@router.get("/api/providers", response_model=list[ProviderOption])
async def get_providers() -> list[dict[str, object]]:
    return get_provider_options()


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
