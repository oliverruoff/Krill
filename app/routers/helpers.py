"""Shared helpers used across multiple routers."""

from __future__ import annotations

from ..config import Settings


def _is_setup_complete(settings: Settings) -> bool:
    if not settings.setup_completed:
        return False
    return _can_complete_setup(settings)


def _can_complete_setup(settings: Settings) -> bool:
    if not settings.user_full_name.strip():
        return False

    if not settings.user_call_name.strip():
        return False

    if not settings.active_provider_id:
        return False

    active_config = settings.provider_configs.get(settings.active_provider_id)
    if active_config is None:
        return False

    if not active_config.api_key.strip():
        return False

    if not active_config.model.strip():
        return False

    return True
