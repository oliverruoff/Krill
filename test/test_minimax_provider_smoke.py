"""Smoke test for MiniMax provider chat generation.

This script verifies that the MiniMax provider:
1) merges multiple system messages into a single MiniMax-compatible system turn
2) can complete a simple chat request with a real API key
3) strips MiniMax reasoning blocks from the visible reply
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path


def _safe_print(text: str) -> None:
    sys.stdout.buffer.write(f"{text}\n".encode("utf-8", errors="backslashreplace"))


async def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from app.providers.minimax import (  # pylint: disable=import-outside-toplevel
        MiniMaxProvider,
        _build_messages,
    )

    api_key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Set MINIMAX_API_KEY before running this smoke test.")

    system_prompt = "You are Krill. Reply briefly and helpfully."
    history = [
        {"role": "system", "content": "Call the user Oli."},
        {"role": "assistant", "content": "Previous assistant reply."},
        {"role": "user", "content": "Previous user reply."},
    ]

    messages = _build_messages(history, "hi", system_prompt)
    system_count = sum(1 for message in messages if message.get("role") == "system")
    if system_count != 1:
        raise RuntimeError(f"Expected exactly 1 merged system message, got {system_count}: {messages}")

    provider = MiniMaxProvider()
    for model in ("MiniMax-M2.7", "MiniMax-M2.5"):
        text, used_tokens = await provider.generate(
            prompt="hi",
            system_prompt=system_prompt,
            model=model,
            api_key=api_key,
            history=history,
        )

        if not text.strip():
            raise RuntimeError(f"{model} returned empty visible text.")
        if "<think>" in text.lower():
            raise RuntimeError(f"Visible MiniMax reply still contains reasoning tags for {model}: {text}")
        if not isinstance(used_tokens, int) or used_tokens <= 0:
            raise RuntimeError(f"Expected positive token usage for {model}, got: {used_tokens}")

        _safe_print(f"PASS: {model} generated a visible reply.")
        _safe_print(f"Reply: {text}")
        _safe_print(f"Used tokens: {used_tokens}")


if __name__ == "__main__":
    asyncio.run(main())
