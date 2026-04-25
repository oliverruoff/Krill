#!/usr/bin/env python3
"""Smoke tests for gateway chat request validation."""

from __future__ import annotations

import sys
from pathlib import Path

from pydantic import ValidationError


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))

    from app.routers.chat import ChatRequest  # pylint: disable=import-outside-toplevel

    runtime_seed = "Runtime context seed. " * 400
    system_prompt = "Friendly assistant. " * 250
    payload = ChatRequest(
        message="Hi",
        history=[{"role": "system", "content": runtime_seed}],
        system_prompt=system_prompt,
    )

    if payload.history[0].content != runtime_seed:
        raise RuntimeError("Long runtime context seed was not preserved.")
    if payload.system_prompt != system_prompt:
        raise RuntimeError("Configured system prompt was not preserved.")

    try:
        ChatRequest(message="x" * 5001)
    except ValidationError:
        pass
    else:
        raise RuntimeError("Oversized user message unexpectedly passed validation.")

    print("PASS: Chat request validation accepts long runtime context while limiting new messages.")


if __name__ == "__main__":
    main()
