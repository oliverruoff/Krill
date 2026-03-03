"""Telegram integration config schema and verification routine."""

import asyncio
from urllib import error

from app.integrations.base import IntegrationConfigField

from .client import telegram_get_me


CONFIG_FIELDS = [
    IntegrationConfigField(
        id="bot_token",
        label="Bot token",
        type="password",
        required=True,
        placeholder="123456:ABCDEF...",
        description="Telegram bot token from @BotFather.",
    ),
    IntegrationConfigField(
        id="markdown_enabled",
        label="Enable Markdown formatting",
        type="text",
        required=False,
        placeholder="true",
        description="Enable MarkdownV2 formatting in messages (bold, italic, code, etc). Default: true",
    ),
]


async def verify_telegram_config(params: dict[str, str]) -> tuple[bool, str]:
    token = params.get("bot_token", "").strip()
    if not token:
        return False, "Telegram bot token is required."

    try:
        payload = await asyncio.to_thread(telegram_get_me, token)
    except error.HTTPError as exc:
        if exc.code in {401, 403}:
            return False, "Telegram rejected the bot token."
        return False, f"Telegram verification failed ({exc.code})."
    except error.URLError:
        return False, "Network error while contacting Telegram."
    except Exception:
        return False, "Unexpected error while verifying Telegram token."

    ok = payload.get("ok")
    result = payload.get("result")
    if not ok or not isinstance(result, dict):
        return False, "Telegram verification failed."

    username = result.get("username")
    bot_name = f"@{username}" if isinstance(username, str) and username.strip() else "the bot"
    return True, f"Telegram token verified for {bot_name}."
