"""Regression checks for debug dump redaction."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from app.config import ChatMessage, ChatSession, MemoryEntry, Settings  # pylint: disable=import-outside-toplevel
    from app.debug_dumps import build_debug_dump_payload  # pylint: disable=import-outside-toplevel

    settings = Settings()
    settings.bot_name = "Krilly"
    settings.user_full_name = "Oliver Example"
    settings.user_call_name = "Oli"
    settings.system_prompt = "Be helpful."
    settings.active_provider_id = "minimax"
    settings.active_model_id = "MiniMax-M2.7"
    settings.core_memories = [
        MemoryEntry(content="the user's email address is: oliver93ruoff@gmail.com"),
        MemoryEntry(content="SSH host connection for Oli: host 192.168.1.126, user oli, password g3n4!"),
    ]

    chat = ChatSession(
        id="chat-1",
        title="Debug chat",
        messages=[
            ChatMessage(role="user", content="normal prompt", timestamp="2026-04-21T00:00:00Z"),
            ChatMessage(
                role="system",
                content=(
                    '{"mcp_id":"scripts","tool_id":"edit_script","arguments":'
                    '{"body":"DEFAULT_API_KEY = \"sk-cp-AX-93_FcSnHOyYwlInoOh224DzMlqLL21gwG1AS1WNv2FKqI04l_3xkc91MJq4Z-Whx4W76AsfrThzbzQDdJlQXpYzEH0kCQ9AbLnZHpGVnnbhAjL8dQ4YU\"",'
                    '"headers":{"Authorization":"Bearer sk-cp-AX-93_FcSnHOyYwlInoOh224DzMlqLL21gwG1AS1WNv2FKqI04l_3xkc91MJq4Z-Whx4W76AsfrThzbzQDdJlQXpYzEH0kCQ9AbLnZHpGVnnbhAjL8dQ4YU"}}}'
                ),
                timestamp="2026-04-21T00:00:30Z",
                system_type="tool_call",
            ),
            ChatMessage(
                role="assistant",
                content="Hard error: password g3n4! email oliver93ruoff@gmail.com",
                timestamp="2026-04-21T00:01:00Z",
                status="error",
            ),
        ],
    )

    payload = build_debug_dump_payload(
        chat,
        source_channel="telegram",
        settings=settings,
        triggered_by="unit_test",
    )

    settings_snapshot = payload.get("settings_snapshot")
    if not isinstance(settings_snapshot, dict):
        raise RuntimeError("Debug dump settings_snapshot missing or invalid.")

    memories = settings_snapshot.get("core_memories")
    if not isinstance(memories, list) or len(memories) != 2:
        raise RuntimeError(f"Unexpected redacted core memories payload: {memories!r}")
    if any("g3n4!" in str(item) or "oliver93ruoff@gmail.com" in str(item) for item in memories):
        raise RuntimeError(f"Sensitive memory content leaked into debug dump: {memories!r}")

    latest_errors = payload.get("latest_error_messages")
    if not isinstance(latest_errors, list) or not latest_errors:
        raise RuntimeError("Expected latest_error_messages entry in debug dump payload.")

    latest_error = latest_errors[0]
    if not isinstance(latest_error, dict):
        raise RuntimeError(f"Invalid latest_error_messages entry: {latest_error!r}")
    error_content = str(latest_error.get("content", ""))
    if "g3n4!" in error_content or "oliver93ruoff@gmail.com" in error_content:
        raise RuntimeError(f"Sensitive error content leaked into debug dump: {error_content!r}")
    if "normal prompt" not in str(payload.get("chat", {})):
        raise RuntimeError("Expected non-sensitive chat context to remain readable in debug dump payload.")
    payload_text = str(payload)
    if "sk-cp-AX-93_FcSnHOyYwlInoOh224DzMlqLL21gwG1AS1WNv2FKqI04l_3xkc91MJq4Z-Whx4W76AsfrThzbzQDdJlQXpYzEH0kCQ9AbLnZHpGVnnbhAjL8dQ4YU" in payload_text:
        raise RuntimeError("Sensitive API key leaked into debug dump payload.")
    if "Bearer sk-cp-AX-93_FcSnHOyYwlInoOh224DzMlqLL21gwG1AS1WNv2FKqI04l_3xkc91MJq4Z-Whx4W76AsfrThzbzQDdJlQXpYzEH0kCQ9AbLnZHpGVnnbhAjL8dQ4YU" in payload_text:
        raise RuntimeError("Sensitive Authorization header leaked into debug dump payload.")

    print("PASS: Debug dump payload redacts sensitive memory and error content.")


if __name__ == "__main__":
    main()
