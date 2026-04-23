"""Smoke test for Telegram group ambient-context buffer.

This script verifies:
1) Non-addressed group messages are buffered (and ignored otherwise)
2) When the bot is addressed, prior buffered messages are injected as context
3) The bot's own reply is appended to the buffer for future context
4) The configured group_context_size is respected and clamped (1..100)
5) The current addressed message is not duplicated in the context block
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch


async def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    temp_dir = Path(tempfile.mkdtemp(prefix="krill_telegram_context_test_"))
    db_path = temp_dir / "braindump.db"
    os.environ["KRILL_BRAINDUMP_PATH"] = str(db_path)

    from app.config import (  # pylint: disable=import-outside-toplevel
        IntegrationConfig,
        ProviderConfig,
        ensure_settings_file,
        load_settings,
        save_settings,
    )
    import app.integrations.telegram.worker as telegram_worker  # pylint: disable=import-outside-toplevel

    await ensure_settings_file()
    settings = await load_settings()
    settings.setup_completed = True
    settings.active_provider_id = "gemini"
    settings.provider_configs["gemini"] = ProviderConfig(api_key="", model="gemini-2.5-flash")
    settings.integration_configs["telegram"] = IntegrationConfig(
        enabled=True,
        params={"bot_token": "dummy-token", "group_context_size": "5"},
    )

    OWNER_USER_ID = 111111
    OWNER_CHAT_ID = 222222
    GROUP_CHAT_ID = -100777
    settings.telegram_state.owner_user_id = str(OWNER_USER_ID)
    settings.telegram_state.owner_chat_id = str(OWNER_CHAT_ID)
    settings.telegram_state.approved_group_ids = []
    await save_settings(settings)

    BOT_USERNAME = "testbot"
    BOT_ID = 42

    sent_messages: list[dict[str, Any]] = []
    captured_calls: list[dict[str, Any]] = []

    def fake_telegram_send_message(token, chat_id, text, parse_mode=None):
        sent_messages.append({"chat_id": chat_id, "text": text, "parse_mode": parse_mode})
        return {"ok": True, "result": {"message_id": len(sent_messages)}}

    async def fake_generate_chat_response(**kwargs):
        captured_calls.append(kwargs)
        return {
            "text": "Cats are independent; dogs are loyal. Both are great.",
            "used_tokens": 10,
            "used_mcp_tools": [],
            "system_trace_messages": [],
        }, 10000

    def make_message(
        from_id: int,
        first_name: str,
        last_name: str,
        chat_id: int,
        chat_type: str,
        text: str,
        bot_username: str = "",
    ) -> dict[str, Any]:
        entities: list[dict[str, Any]] = []
        if bot_username and f"@{bot_username}" in text:
            idx = text.index(f"@{bot_username}")
            entities.append({"type": "mention", "offset": idx, "length": len(f"@{bot_username}")})
        return {
            "from": {"id": from_id, "is_bot": False, "first_name": first_name, "last_name": last_name},
            "chat": {"id": chat_id, "type": chat_type},
            "text": text,
            "entities": entities,
        }

    worker = telegram_worker.TelegramBridgeWorker()
    token = "dummy-token"

    with (
        patch.object(telegram_worker, "telegram_send_message", side_effect=fake_telegram_send_message),
        patch("app.integrations.telegram.worker.generate_chat_response", side_effect=fake_generate_chat_response),
        patch("app.integrations.telegram.worker.register_user_message_and_maybe_extract", new_callable=AsyncMock),
        patch("app.integrations.telegram.worker.register_completed_turn", new_callable=AsyncMock),
        patch("app.integrations.telegram.worker.add_daily_usage"),
        patch("app.integrations.telegram.worker.ensure_runtime_context_seed"),
    ):
        # Owner is in the group too. Owner doesn't need group approval.
        # Send three non-addressed messages from random users; they should be buffered, not answered.
        for sender_id, first, last, txt in [
            (OWNER_USER_ID, "Olive", "Owner", "I think cats are way better"),
            (555555, "Bob", "Builder", "Dogs are more loyal though"),
            (666666, "Alice", "Smith", "Cats are independent that's the point"),
        ]:
            msg = make_message(sender_id, first, last, GROUP_CHAT_ID, "supergroup", txt, BOT_USERNAME)
            await worker._handle_message(token, msg, BOT_USERNAME, BOT_ID)

        assert not sent_messages, "Non-addressed group messages should not produce replies"
        assert not captured_calls, "Non-addressed group messages should not call the LLM"
        buffer = worker._group_message_buffers.get(GROUP_CHAT_ID)
        assert buffer is not None and len(buffer) == 3, f"Buffer should have 3 entries, got {len(buffer) if buffer else 0}"
        names = [e["name"] for e in buffer]
        assert names == ["Olive O.", "Bob B.", "Alice S."], f"Sender name format wrong: {names}"
        print("PASS: Non-addressed group messages buffered, sender names formatted correctly")

        # Now owner addresses the bot. Context should be injected, current message excluded from context.
        captured_calls.clear()
        sent_messages.clear()
        msg = make_message(OWNER_USER_ID, "Olive", "Owner", GROUP_CHAT_ID, "supergroup", f"@{BOT_USERNAME} what do you think?", BOT_USERNAME)
        await worker._handle_message(token, msg, BOT_USERNAME, BOT_ID)
        active_run = worker._active_runs.get(GROUP_CHAT_ID)
        if active_run is not None:
            task = active_run.get("task")
            if task is not None:
                await asyncio.wait_for(task, timeout=5.0)

        assert captured_calls, "LLM should have been called"
        injected_message = captured_calls[-1].get("message", "")
        assert "Group conversation context" in injected_message, f"Context block missing: {injected_message[:200]!r}"
        assert "Olive O.: I think cats are way better" in injected_message
        assert "Bob B.: Dogs are more loyal though" in injected_message
        assert "Alice S.: Cats are independent" in injected_message
        # The current addressed message must not be duplicated inside the context block
        context_section = injected_message.split("[End of context")[0]
        assert "what do you think?" not in context_section, "Current message must not appear in the context block"
        # The actual prompt to answer must still be present after the context
        assert "what do you think?" in injected_message, "Current prompt missing after context block"
        print("PASS: Context injected on @mention, current message excluded from context block")

        # The bot's own reply should now be in the buffer for future context.
        buffer = worker._group_message_buffers.get(GROUP_CHAT_ID)
        assert buffer is not None
        last_entry = buffer[-1]
        assert last_entry["name"] == f"@{BOT_USERNAME}", f"Bot reply name wrong: {last_entry['name']}"
        assert "Cats are independent" in last_entry["text"], "Bot reply not buffered"
        print("PASS: Bot's own reply added to context buffer")

        # Test group_context_size config is respected: shrink to 2 and verify only the
        # last 2 entries (excluding the current message) are injected.
        settings = await load_settings()
        settings.integration_configs["telegram"].params["group_context_size"] = "2"
        await save_settings(settings)

        # Push more messages so the buffer has many entries.
        for sender_id, first, last, txt in [
            (777777, "Dave", "Doe", "msg-A"),
            (777777, "Dave", "Doe", "msg-B"),
            (888888, "Eve", "X", "msg-C"),
        ]:
            msg = make_message(sender_id, first, last, GROUP_CHAT_ID, "supergroup", txt, BOT_USERNAME)
            await worker._handle_message(token, msg, BOT_USERNAME, BOT_ID)

        captured_calls.clear()
        msg = make_message(OWNER_USER_ID, "Olive", "Owner", GROUP_CHAT_ID, "supergroup", f"@{BOT_USERNAME} continue", BOT_USERNAME)
        await worker._handle_message(token, msg, BOT_USERNAME, BOT_ID)
        active_run = worker._active_runs.get(GROUP_CHAT_ID)
        if active_run is not None:
            task = active_run.get("task")
            if task is not None:
                await asyncio.wait_for(task, timeout=5.0)

        assert captured_calls
        injected = captured_calls[-1].get("message", "")
        # With size=2, only the 2 most recent buffered entries (other than the current addressed msg) should appear.
        # Most recent entries before the @mention were: Dave: msg-B, Eve: msg-C
        assert "Eve X.: msg-C" in injected
        assert "Dave D.: msg-B" in injected
        assert "msg-A" not in injected, "Older entries should be trimmed when context size is 2"
        print("PASS: group_context_size respected (size=2 trims older entries)")

        # Test clamping: invalid value falls back to default (20)
        size = worker._get_group_context_size(settings)
        assert size == 2, f"Expected 2, got {size}"
        settings.integration_configs["telegram"].params["group_context_size"] = "not-a-number"
        size = worker._get_group_context_size(settings)
        assert size == 20, f"Invalid value should fall back to 20, got {size}"
        settings.integration_configs["telegram"].params["group_context_size"] = "9999"
        size = worker._get_group_context_size(settings)
        assert size == 100, f"Should clamp to 100, got {size}"
        settings.integration_configs["telegram"].params["group_context_size"] = "0"
        size = worker._get_group_context_size(settings)
        assert size == 1, f"Should clamp to 1, got {size}"
        print("PASS: group_context_size clamping (invalid->20, >100->100, <1->1)")

    print("\nAll tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
