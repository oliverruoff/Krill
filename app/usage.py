"""Shared token usage helpers for updating and reading daily usage counters."""

from datetime import datetime, timezone

from app.config import DailyTokenUsage, Settings


def add_daily_usage(settings: Settings, tokens_to_add: int) -> None:
    if tokens_to_add <= 0:
        return
    date_key = datetime.now(timezone.utc).date().isoformat()
    for entry in settings.daily_token_usage:
        if entry.date == date_key:
            entry.tokens += tokens_to_add
            return
    settings.daily_token_usage.append(DailyTokenUsage(date=date_key, tokens=tokens_to_add))


def get_today_token_usage(settings: Settings) -> int:
    date_key = datetime.now(timezone.utc).date().isoformat()
    for entry in settings.daily_token_usage:
        if entry.date == date_key:
            return max(0, int(entry.tokens))
    return 0
