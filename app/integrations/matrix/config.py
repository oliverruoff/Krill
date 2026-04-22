"""Matrix integration configuration and verification helpers."""

from __future__ import annotations

import asyncio
from urllib import error

from app.integrations.base import IntegrationConfigField

from .client import matrix_whoami


CONFIG_FIELDS = [
    IntegrationConfigField(
        id="homeserver_url",
        label="Homeserver URL",
        type="text",
        required=True,
        placeholder="https://matrix.example.com",
        description="Self-hosted Matrix homeserver base URL.",
    ),
    IntegrationConfigField(
        id="access_token",
        label="Access token",
        type="password",
        required=True,
        placeholder="syt_...",
        description="Matrix bot access token for the bot account.",
    ),
]


async def verify_matrix_config(params: dict[str, str]) -> tuple[bool, str]:
    homeserver_url = str(params.get("homeserver_url", "")).strip()
    access_token = str(params.get("access_token", "")).strip()
    if not homeserver_url:
        return False, "Matrix homeserver URL is required."
    if not access_token:
        return False, "Matrix access token is required."

    try:
        payload = await asyncio.to_thread(matrix_whoami, homeserver_url, access_token)
    except ValueError as exc:
        return False, str(exc)
    except error.HTTPError as exc:
        if exc.code in {401, 403}:
            return False, "Matrix rejected the access token."
        return False, f"Matrix verification failed ({exc.code})."
    except error.URLError:
        return False, "Network error while contacting the Matrix homeserver."
    except Exception:
        return False, "Unexpected error while verifying Matrix access."

    user_id = str(payload.get("user_id", "")).strip()
    if not user_id:
        return False, "Matrix verification failed: bot user id missing."
    return True, f"Matrix token verified for {user_id}."
