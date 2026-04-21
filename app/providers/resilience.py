"""Provider call resilience helpers with retry/backoff for transient failures."""

from __future__ import annotations

import asyncio
import random
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Awaitable, Callable, TypedDict

from .base import LLMProvider
from .errors import ProviderRequestError
from app.tooling.execution import CancellationToken




class ProviderRetryMetadata(TypedDict):
    retry_class: str
    delay_source: str
    next_retry_at: str


ProviderRetryCallback = Callable[[int, int, float, str, ProviderRetryMetadata], Awaitable[None]]

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
    cancellation_token: CancellationToken | None = None,
) -> tuple[str, int | None]:
    """Calls provider.generate with retry/backoff on transient failures."""
    attempts = max(1, min(5, int(max_attempts)))
    retry_history: list[dict[str, object]] = []
    for attempt in range(1, attempts + 1):
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        try:
            return await provider.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                model=model,
                api_key=api_key,
                history=history,
            )
        except Exception as exc:
            retryable = _is_retryable_provider_error(exc)
            if attempt >= attempts or not retryable:
                _attach_retry_history(exc, retry_history)
                raise

            delay = _compute_retry_delay_seconds(exc, attempt)
            delay_source = "retry-after" if _retry_after_seconds_from_exception(exc) is not None else "backoff"
            now = datetime.now().astimezone()
            metadata: ProviderRetryMetadata = {
                "retry_class": _classify_retryable_provider_error(exc),
                "delay_source": delay_source,
                "next_retry_at": datetime.fromtimestamp(now.timestamp() + delay, tz=now.tzinfo).isoformat(),
            }
            retry_history.append(
                {
                    "attempt": attempt,
                    "max_attempts": attempts,
                    "delay_seconds": round(delay, 3),
                    "reason": _error_message(exc),
                    **metadata,
                }
            )
            if on_retry is not None:
                await on_retry(attempt, attempts, delay, _error_message(exc), metadata)
            if cancellation_token is not None:
                try:
                    await asyncio.wait_for(cancellation_token.wait(), timeout=delay)
                    cancellation_token.raise_if_cancelled()
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(delay)

    raise RuntimeError("Provider retry loop failed unexpectedly.")


def _is_retryable_provider_error(exc: Exception) -> bool:
    if isinstance(exc, ProviderRequestError):
        return bool(exc.retryable)
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


def _classify_retryable_provider_error(exc: Exception) -> str:
    if isinstance(exc, ProviderRequestError):
        return str(exc.retry_class or "unknown")
    if isinstance(exc, TimeoutError):
        return "timeout"

    message = _error_message(exc).lower()
    if not message:
        return "unknown"
    if "429" in message or "too many requests" in message or "rate limit" in message:
        return "rate_limit"
    if any(marker in message for marker in ("timeout", "timed out")):
        return "timeout"
    if any(marker in message for marker in ("network error", "connection reset", "connection refused", "connection aborted")):
        return "network"
    if any(marker in message for marker in ("(500)", "(502)", "(503)", "(504)", "service unavailable", "temporarily unavailable", "overloaded")):
        return "server_error"
    return "transient"


def _compute_retry_delay_seconds(exc: Exception, attempt: int) -> float:
    header_delay = _retry_after_seconds_from_exception(exc)
    if header_delay is not None:
        return max(0.1, min(_MAX_DELAY_SECONDS, header_delay))

    exponential = min(_MAX_DELAY_SECONDS, _BASE_DELAY_SECONDS * (2 ** (attempt - 1)))
    jitter = random.uniform(0.0, _JITTER_SECONDS)
    return max(0.1, min(_MAX_DELAY_SECONDS, exponential + jitter))


def _retry_after_seconds_from_exception(exc: Exception) -> float | None:
    if isinstance(exc, ProviderRequestError):
        parsed = _retry_after_seconds_from_headers(exc.response_headers)
        if parsed is not None:
            return parsed

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


def _attach_retry_history(exc: Exception, retry_history: list[dict[str, object]]) -> None:
    if not retry_history:
        return
    copied_history = [dict(entry) for entry in retry_history]
    if isinstance(exc, ProviderRequestError):
        exc.retry_history = copied_history
        return
    try:
        setattr(exc, "retry_history", copied_history)
    except Exception:
        return
