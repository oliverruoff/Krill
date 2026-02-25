"""Provider call resilience helpers with retry/backoff for transient failures."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from .base import LLMProvider


ProviderRetryCallback = Callable[[int, int, float, str], Awaitable[None]]

_DEFAULT_MAX_ATTEMPTS = 3
_BASE_DELAY_SECONDS = 0.6
_MAX_DELAY_SECONDS = 4.0


async def generate_with_retries(
    *,
    provider: LLMProvider,
    prompt: str,
    system_prompt: str,
    model: str,
    api_key: str,
    history: list[dict[str, str]],
    on_retry: ProviderRetryCallback | None = None,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
) -> tuple[str, int | None]:
    """Calls provider.generate with retry/backoff on transient failures."""
    attempts = max(1, min(5, int(max_attempts)))
    for attempt in range(1, attempts + 1):
        try:
            return await provider.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                model=model,
                api_key=api_key,
                history=history,
            )
        except Exception as exc:
            if attempt >= attempts or not _is_retryable_provider_error(exc):
                raise

            delay = min(_MAX_DELAY_SECONDS, _BASE_DELAY_SECONDS * (2 ** (attempt - 1)))
            if on_retry is not None:
                await on_retry(attempt, attempts, delay, _error_message(exc))
            await asyncio.sleep(delay)

    raise RuntimeError("Provider retry loop failed unexpectedly.")


def _is_retryable_provider_error(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True

    message = _error_message(exc).lower()
    if not message:
        return False

    retryable_markers = (
        "network error",
        "timed out",
        "timeout",
        "temporarily unavailable",
        "service unavailable",
        "connection reset",
        "connection refused",
        "connection aborted",
        "unexpected error while contacting",
        "too many requests",
        "rate limit",
        " 429",
        "(429)",
        "(500)",
        "(502)",
        "(503)",
        "(504)",
        "overloaded",
    )
    return any(marker in message for marker in retryable_markers)


def _error_message(exc: Exception) -> str:
    try:
        return str(exc).strip()
    except Exception:
        return ""
