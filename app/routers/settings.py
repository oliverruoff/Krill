"""Settings management routes: read/write, provider-model switch, reset, version, and braindump."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..config import (
    McpConfig,
    Settings,
    create_braindump_snapshot,
    import_braindump_db,
    load_settings,
    save_settings,
    view_braindump,
    _server_timezone,
)
from ..integrations import is_supported_integration
from ..mcps import get_mcp, is_supported_mcp
from ..mcps.git_ops import (
    SSH_PRIVATE_PARAM,
    SSH_PUBLIC_PARAM,
    ensure_ssh_keypair,
    get_workspace_path,
)
from ..mcps.google_services import (
    ACCESS_MODE_PARAM,
    ACCESS_TOKEN_PARAM,
    CLIENT_ID_PARAM,
    CLIENT_SECRET_PARAM,
    CONNECTED_EMAIL_PARAM,
    GOOGLE_MCP_ID,
    REFRESH_TOKEN_PARAM,
    SCOPES_PARAM,
    TOKEN_EXPIRY_PARAM,
)
from ..providers import is_supported_provider
from ..version import APP_VERSION
from .helpers import _can_complete_setup

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ActiveProviderModelRequest(BaseModel):
    provider_id: str
    model_id: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/api/settings", response_model=Settings)
async def get_settings() -> Settings:
    return await load_settings()


@router.post("/api/settings", response_model=Settings)
async def update_settings(settings: Settings) -> Settings:
    existing = await load_settings()
    settings = settings.model_copy(update={"user_message_count": existing.user_message_count})
    _merge_existing_provider_api_keys(existing, settings)
    _merge_google_managed_oauth_params(existing, settings)
    _merge_git_managed_ssh_params(existing, settings)
    _validate_settings_payload(settings)
    return await save_settings(settings)


@router.post("/api/settings/active-provider-model", response_model=Settings)
async def update_active_provider_model(payload: ActiveProviderModelRequest) -> Settings:
    provider_id = payload.provider_id.strip()
    model_id = payload.model_id.strip()
    if not provider_id:
        raise HTTPException(status_code=422, detail="Provider is required.")
    if not model_id:
        raise HTTPException(status_code=422, detail="Model is required.")

    settings = await load_settings()
    provider_config = settings.provider_configs.get(provider_id)
    if provider_config is None:
        raise HTTPException(status_code=422, detail="Selected provider is not configured.")

    updated_provider_configs = dict(settings.provider_configs)
    updated_provider_configs[provider_id] = provider_config.model_copy(update={"model": model_id})
    updated_settings = settings.model_copy(
        update={
            "active_provider_id": provider_id,
            "active_model_id": model_id,
            "provider_configs": updated_provider_configs,
        }
    )
    _validate_settings_payload(updated_settings)
    return await save_settings(updated_settings)


@router.post("/api/reset", response_model=Settings)
async def reset_settings() -> Settings:
    defaults = Settings()
    return await save_settings(defaults)


@router.get("/api/version")
async def get_version() -> dict[str, object]:
    now_utc = datetime.now(timezone.utc)
    name, tz = _server_timezone()
    offset = tz.utcoffset(now_utc.astimezone(tz)) or timedelta(minutes=0)
    offset_minutes = int(offset.total_seconds() // 60)
    return {
        "version": APP_VERSION,
        "server_timezone": name,
        "server_timezone_offset": offset_minutes,
    }


@router.get("/api/braindump/download")
async def download_braindump(background_tasks: BackgroundTasks):
    fd, tmp_path_str = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    tmp_path = Path(tmp_path_str)

    try:
        await create_braindump_snapshot(tmp_path)
        background_tasks.add_task(tmp_path.unlink, missing_ok=True)
        return FileResponse(
            tmp_path,
            media_type="application/x-sqlite3",
            filename="braindump.db",
            background=background_tasks,
        )
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Download failed: {exc}")


@router.post("/api/braindump/import")
async def import_braindump(file: UploadFile = File(...)):
    fd, tmp_path_str = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    tmp_path = Path(tmp_path_str)

    try:
        content = await file.read()
        tmp_path.write_bytes(content)
        await import_braindump_db(tmp_path)
        await rehydrate_git_ssh_material()
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}")
    finally:
        tmp_path.unlink(missing_ok=True)


@router.get("/api/braindump/view")
async def get_braindump_view() -> dict[str, object]:
    return await view_braindump(show_secrets=True)


# ---------------------------------------------------------------------------
# Startup helper (called from main.py)
# ---------------------------------------------------------------------------

async def rehydrate_git_ssh_material() -> None:
    """Restore SSH key files on disk from persisted params. Called on startup and after import."""
    settings = await load_settings()
    git_config = settings.mcp_configs.get("git_ops")
    if git_config is None:
        return

    params = dict(git_config.params)
    configured_private = str(params.get(SSH_PRIVATE_PARAM, "") or "").strip()
    configured_public = str(params.get(SSH_PUBLIC_PARAM, "") or "").strip()
    if not configured_private and not configured_public:
        return

    workspace = get_workspace_path()
    private_key, public_key = await ensure_ssh_keypair(params, workspace)

    if private_key == configured_private and public_key == configured_public:
        return

    params[SSH_PRIVATE_PARAM] = private_key
    params[SSH_PUBLIC_PARAM] = public_key
    settings.mcp_configs["git_ops"] = McpConfig(enabled=git_config.enabled, params=params)
    await save_settings(settings)


# ---------------------------------------------------------------------------
# Settings validation and merge helpers
# ---------------------------------------------------------------------------

def _validate_provider_configs(settings: Settings) -> None:
    if settings.active_provider_id and settings.active_provider_id not in settings.provider_configs:
        raise HTTPException(status_code=422, detail="Active provider must exist in provider configs.")

    for provider_id, provider_config in settings.provider_configs.items():
        if not is_supported_provider(provider_id):
            raise HTTPException(status_code=422, detail=f"Unsupported LLM provider: {provider_id}")

        if not provider_config.model.strip():
            raise HTTPException(status_code=422, detail=f"Model is required for provider '{provider_id}'.")


def _validate_mcp_configs(settings: Settings) -> None:
    valid_configs = {}
    for mcp_id, mcp_config in settings.mcp_configs.items():
        if not is_supported_mcp(mcp_id):
            continue

        mcp = get_mcp(mcp_id)
        if mcp is None:
            continue

        valid_configs[mcp_id] = mcp_config

    settings.mcp_configs = valid_configs


def _validate_integration_configs(settings: Settings) -> None:
    for integration_id in settings.integration_configs.keys():
        if not is_supported_integration(integration_id):
            raise HTTPException(status_code=422, detail=f"Unsupported integration: {integration_id}")


def _validate_settings_payload(settings: Settings) -> None:
    _validate_provider_configs(settings)
    _validate_mcp_configs(settings)
    _validate_integration_configs(settings)

    if settings.setup_completed and not _can_complete_setup(settings):
        raise HTTPException(
            status_code=422,
            detail="Setup cannot be marked complete without user name fields, active provider, model, and API key.",
        )


def _merge_existing_provider_api_keys(existing: Settings, incoming: Settings) -> None:
    for provider_id, incoming_config in list(incoming.provider_configs.items()):
        incoming_key = incoming_config.api_key.strip()
        if incoming_key:
            continue
        existing_config = existing.provider_configs.get(provider_id)
        if existing_config is None:
            continue
        existing_key = existing_config.api_key.strip()
        if not existing_key:
            continue
        incoming.provider_configs[provider_id] = incoming_config.model_copy(update={"api_key": existing_key})


def _merge_google_managed_oauth_params(existing: Settings, incoming: Settings) -> None:
    existing_google = existing.mcp_configs.get(GOOGLE_MCP_ID)
    incoming_google = incoming.mcp_configs.get(GOOGLE_MCP_ID)
    if incoming_google is None:
        if existing_google is not None:
            incoming.mcp_configs[GOOGLE_MCP_ID] = existing_google
        return

    if existing_google is None:
        return

    existing_params = dict(existing_google.params)
    merged_params = dict(incoming_google.params)

    existing_client_id = str(existing_params.get(CLIENT_ID_PARAM, "")).strip()
    incoming_client_id = str(merged_params.get(CLIENT_ID_PARAM, "")).strip()
    existing_client_secret = str(existing_params.get(CLIENT_SECRET_PARAM, "")).strip()
    incoming_client_secret = str(merged_params.get(CLIENT_SECRET_PARAM, "")).strip()
    credentials_changed = (
        (incoming_client_id and incoming_client_id != existing_client_id)
        or (incoming_client_secret and incoming_client_secret != existing_client_secret)
    )

    managed_keys = (
        ACCESS_TOKEN_PARAM,
        REFRESH_TOKEN_PARAM,
        TOKEN_EXPIRY_PARAM,
        SCOPES_PARAM,
        CONNECTED_EMAIL_PARAM,
    )

    if credentials_changed:
        for key in managed_keys:
            merged_params.pop(key, None)
    else:
        for key in managed_keys:
            existing_value = str(existing_params.get(key, "")).strip()
            if existing_value:
                merged_params[key] = existing_value

    incoming.mcp_configs[GOOGLE_MCP_ID] = McpConfig(enabled=incoming_google.enabled, params=merged_params)


def _merge_git_managed_ssh_params(existing: Settings, incoming: Settings) -> None:
    existing_git = existing.mcp_configs.get("git_ops")
    incoming_git = incoming.mcp_configs.get("git_ops")
    if incoming_git is None:
        if existing_git is not None:
            incoming.mcp_configs["git_ops"] = existing_git
        return

    if existing_git is None:
        return

    existing_params = dict(existing_git.params)
    merged_params = dict(incoming_git.params)

    for managed_key in (SSH_PRIVATE_PARAM, SSH_PUBLIC_PARAM):
        incoming_value = str(merged_params.get(managed_key, "") or "").strip()
        existing_value = str(existing_params.get(managed_key, "") or "").strip()
        if incoming_value:
            continue
        if existing_value:
            merged_params[managed_key] = existing_value

    incoming.mcp_configs["git_ops"] = McpConfig(enabled=incoming_git.enabled, params=merged_params)
