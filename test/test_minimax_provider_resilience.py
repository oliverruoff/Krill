"""Deterministic MiniMax provider resilience checks."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


class _FakeResponse:
    def __init__(self, body: str, status: int = 200):
        self._body = body.encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


async def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    import app.providers.minimax as minimax  # pylint: disable=import-outside-toplevel
    import app.providers.resilience as resilience  # pylint: disable=import-outside-toplevel
    from app.providers.errors import ProviderRequestError  # pylint: disable=import-outside-toplevel

    extracted = minimax._extract_text(
        {
            "choices": [
                {"message": {"content": ""}},
                {"message": {"content": [{"type": "text", "text": "Visible reply"}]}},
            ]
        }
    )
    if extracted != "Visible reply":
        raise RuntimeError(f"Expected alternate MiniMax payload extraction to succeed, got: {extracted!r}")

    original_urlopen = minimax.request.urlopen
    try:
        minimax.request.urlopen = lambda req, timeout=30: _FakeResponse("{not-json")
        try:
            minimax._post_json_return_body("https://example.test", {"hello": "world"}, "dummy")
        except ProviderRequestError as exc:
            if exc.retry_class != "server_error" or not exc.retryable:
                raise RuntimeError(f"Malformed JSON should be retryable server_error, got: {exc}")
        else:
            raise RuntimeError("Expected malformed MiniMax JSON to raise ProviderRequestError.")

        minimax.request.urlopen = lambda req, timeout=30: _FakeResponse(
            '{"base_resp":{"status_code":1002,"status_msg":"busy"},"choices":[]}'
        )
        try:
            minimax._post_json_return_body("https://example.test", {"hello": "world"}, "dummy")
        except ProviderRequestError as exc:
            if exc.status_code != 1002:
                raise RuntimeError(f"Expected MiniMax base status 1002, got: {exc.status_code}")
            if exc.retry_class != "rate_limit" or not exc.retryable:
                raise RuntimeError(f"Expected rate_limit retryable error for base_resp 1002, got: {exc}")
        else:
            raise RuntimeError("Expected MiniMax base_resp error to raise ProviderRequestError.")
    finally:
        minimax.request.urlopen = original_urlopen

    if not minimax._empty_response_retryable(
        {
            "choices": [
                {
                    "message": {
                        "reasoning_content": "thinking...",
                    }
                }
            ]
        }
    ):
        raise RuntimeError("Expected reasoning-only MiniMax empty response to be treated as retryable.")

    original_sleep = resilience.asyncio.sleep
    recorded_delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        recorded_delays.append(delay)

    class _RetryAfterProvider:
        def __init__(self) -> None:
            self.calls = 0

        async def generate(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise ProviderRequestError(
                    "MiniMax request failed (429): busy",
                    provider_id="minimax",
                    status_code=429,
                    headers={"Retry-After": "0.2"},
                    retry_class="rate_limit",
                    retryable=True,
                )
            return "ok", 7

    resilience.asyncio.sleep = fake_sleep
    try:
        text, used_tokens = await resilience.generate_with_retries(
            provider=_RetryAfterProvider(),
            prompt="hi",
            system_prompt="",
            model="MiniMax-M2.7",
            api_key="dummy",
            history=[],
        )
    finally:
        resilience.asyncio.sleep = original_sleep

    if text != "ok" or used_tokens != 7:
        raise RuntimeError(f"Retry flow returned unexpected result: text={text!r} tokens={used_tokens!r}")
    if not recorded_delays:
        raise RuntimeError("Expected retry loop to sleep before retrying MiniMax request.")
    if abs(recorded_delays[0] - 0.2) > 0.001:
        raise RuntimeError(f"Expected Retry-After delay of 0.2 seconds, got: {recorded_delays[0]}")

    print("PASS: MiniMax resilience helpers handle malformed responses, base_resp errors, and Retry-After delays.")


if __name__ == "__main__":
    asyncio.run(main())
