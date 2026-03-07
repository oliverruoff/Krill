"""Provider call resilience helpers with retry/backoff for transient failures."""

from __future__ import annotations

import asyncio
import random
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Awaitable, Callable

from .base import LLMProvider


ProviderRetryCallback = Callable[[int, int, float, str], Awaitable[None]]

_DEFAULT_MAX_ATTEMPTS = 3
_BASE_DELAY_SECONDS = 0.6
_MAX_DELAY_SECONDS = 4.0
_JITTER_SECONDS = 0.25


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

            delay = _compute_retry_delay_seconds(exc, attempt)
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


def _compute_retry_delay_seconds(exc: Exception, attempt: int) -> float:
    header_delay = _retry_after_seconds_from_exception(exc)
    if header_delay is not None:
        return max(0.1, min(_MAX_DELAY_SECONDS, header_delay))

    exponential = min(_MAX_DELAY_SECONDS, _BASE_DELAY_SECONDS * (2 ** (attempt - 1)))
    jitter = random.uniform(0.0, _JITTER_SECONDS)
    return max(0.1, min(_MAX_DELAY_SECONDS, exponential + jitter))


def _retry_after_seconds_from_exception(exc: Exception) -> float | None:
    # Common response header containers seen across provider clients.
    candidate_headers: list[object] = []
    for attr in ("response_headers", "headers"):
        candidate = getattr(exc, attr, None)
        if candidate is not None:
            candidate_headers.append(candidate)

    for headers in candidate_headers:
        parsed = _retry_after_seconds_from_headers(headers)
        if parsed is not None:
            return parsed

    return None


def _retry_after_seconds_from_headers(headers: object) -> float | None:
    if not isinstance(headers, dict):
        return None

    normalized = {str(key).lower(): value for key, value in headers.items()}

    retry_after_ms = normalized.get("retry-after-ms")
    parsed_ms = _coerce_float(retry_after_ms)
    if parsed_ms is not None and parsed_ms >= 0:
        return parsed_ms / 1000.0

    retry_after = normalized.get("retry-after")
    parsed_seconds = _coerce_float(retry_after)
    if parsed_seconds is not None and parsed_seconds >= 0:
        return parsed_seconds

    if isinstance(retry_after, str):
        try:
            target = parsedate_to_datetime(retry_after)
            now = datetime.now(target.tzinfo) if target.tzinfo is not None else datetime.now()
            remaining = (target - now).total_seconds()
            if remaining >= 0:
                return remaining
        except Exception:
            return None

    return None


def _coerce_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _error_message(exc: Exception) -> str:
    try:
        return str(exc).strip()
    except Exception:
        return ""
