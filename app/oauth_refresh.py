"""Background worker that proactively refreshes OAuth tokens before they expire.

This prevents the common scenario where a user leaves Krill idle for hours/days,
the access token expires, the refresh token gets rotated by the provider, and
on next use (or after a container restart) the stored credentials are stale.

The worker checks stored OAuth credentials every ``_POLL_INTERVAL_SECONDS`` and
refreshes any that are within ``_REFRESH_BUFFER_SECONDS`` of expiry, persisting
the new credentials to the database immediately.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from app.config import ProviderConfig, load_settings, save_settings
from app.providers.openai_codex_oauth import (
    OPENAI_CODEX_OAUTH_PROVIDER_ID,
    parse_oauth_bundle,
    refresh_access_token,
    serialize_oauth_bundle,
    _TOKEN_CACHE_BY_REFRESH,
)

_logger = logging.getLogger(__name__)

# How often we check for tokens that need refreshing (seconds).
_POLL_INTERVAL_SECONDS = 30 * 60  # 30 minutes

# Refresh a token when it has this many seconds (or fewer) remaining.
_REFRESH_BUFFER_SECONDS = 10 * 60  # 10 minutes

_WORKER_TASK: asyncio.Task[None] | None = None
_STOP_EVENT = asyncio.Event()


async def start_oauth_refresh_worker() -> None:
    """Start the background OAuth refresh worker (idempotent)."""
    global _WORKER_TASK
    if _WORKER_TASK is not None and not _WORKER_TASK.done():
        return
    _STOP_EVENT.clear()
    _WORKER_TASK = asyncio.create_task(_oauth_refresh_loop())


async def stop_oauth_refresh_worker() -> None:
    """Stop the background OAuth refresh worker gracefully."""
    global _WORKER_TASK
    _STOP_EVENT.set()
    if _WORKER_TASK is None:
        return
    _WORKER_TASK.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _WORKER_TASK
    _WORKER_TASK = None


async def _oauth_refresh_loop() -> None:
    """Main loop: periodically refresh OAuth tokens that are near expiry."""
    while not _STOP_EVENT.is_set():
        try:
            await _refresh_openai_oauth_if_needed()
        except asyncio.CancelledError:
            raise
        except Exception:
            _logger.debug("OAuth background refresh cycle failed.", exc_info=True)

        # Sleep in small increments so we can respond to stop quickly.
        for _ in range(_POLL_INTERVAL_SECONDS):
            if _STOP_EVENT.is_set():
                return
            await asyncio.sleep(1)


async def _refresh_openai_oauth_if_needed() -> None:
    """Check the stored OpenAI OAuth credentials and refresh if near expiry."""
    settings = await load_settings()
    provider_config = settings.provider_configs.get(OPENAI_CODEX_OAUTH_PROVIDER_ID)
    if provider_config is None or not provider_config.api_key.strip():
        return

    try:
        credentials = parse_oauth_bundle(provider_config.api_key)
    except Exception:
        return

    now = int(time.time())
    remaining = credentials.expires_at_unix - now

    if remaining > _REFRESH_BUFFER_SECONDS:
        _logger.debug(
            "OpenAI OAuth token still valid for %d seconds; no proactive refresh needed.",
            remaining,
        )
        return

    _logger.info(
        "OpenAI OAuth token expires in %d seconds (buffer=%d); proactively refreshing.",
        remaining,
        _REFRESH_BUFFER_SECONDS,
    )

    try:
        refreshed = await asyncio.to_thread(refresh_access_token, credentials.refresh_token)
    except Exception:
        _logger.warning("Proactive OpenAI OAuth token refresh failed.", exc_info=True)
        return

    # Update in-memory cache.
    _TOKEN_CACHE_BY_REFRESH[credentials.refresh_token] = refreshed
    _TOKEN_CACHE_BY_REFRESH[refreshed.refresh_token] = refreshed

    # Persist to database.
    bundle = serialize_oauth_bundle(refreshed)
    existing_model = provider_config.model.strip() or "gpt-5.3-codex"
    settings.provider_configs[OPENAI_CODEX_OAUTH_PROVIDER_ID] = provider_config.model_copy(
        update={"api_key": bundle, "model": existing_model}
    )
    await save_settings(settings)
    _logger.info("Proactively refreshed and persisted OpenAI OAuth credentials.")
