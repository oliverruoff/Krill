"""Smoke test for Telegram group access control logic.

This script tests:
1) Non-owner in private DM is ignored
2) Non-owner in unapproved group is ignored
3) Non-owner in approved group gets a restricted response (allowed_mcp_ids enforced)
4) /approve command adds group to approved list
5) /unapprove command removes group from approved list
6) owner_chat_id is only updated from private chats (not group messages)
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch


async def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    temp_dir = Path(tempfile.mkdtemp(prefix="krill_telegram_group_test_"))
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
    settings.integration_configs["telegram"] = IntegrationConfig(enabled=True, params={"bot_token": "dummy-token"})

    OWNER_USER_ID = 111111
    OWNER_CHAT_ID = 222222
    NON_OWNER_USER_ID = 333333
    GROUP_CHAT_ID = -100999

    settings.telegram_state.owner_user_id = str(OWNER_USER_ID)
    settings.telegram_state.owner_chat_id = str(OWNER_CHAT_ID)
    settings.telegram_state.approved_group_ids = []
    settings.telegram_state.guest_allowed_mcp_ids = ["brain_access"]
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
            "text": "response",
            "used_tokens": 10,
            "used_mcp_tools": [],
            "system_trace_messages": [],
        }, 10000

    def make_message(from_id: int, chat_id: int, chat_type: str, text: str, bot_username: str = "") -> dict[str, Any]:
        entities = []
        if text.startswith("/") and "@" in text and bot_username:
            entities.append({"type": "bot_command", "offset": 0, "length": len(text.split()[0])})
        elif f"@{bot_username}" in text:
            idx = text.index(f"@{bot_username}")
            entities.append({"type": "mention", "offset": idx, "length": len(f"@{bot_username}")})
        return {
            "from": {"id": from_id, "is_bot": False},
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
        # Test 1: Non-owner in private DM is ignored
        sent_messages.clear()
        captured_calls.clear()
        msg = make_message(NON_OWNER_USER_ID, NON_OWNER_USER_ID, "private", "hello")
        await worker._handle_message(token, msg, BOT_USERNAME, BOT_ID)
        assert not sent_messages, "Non-owner in private DM should be silently ignored"
        assert not captured_calls, "No LLM call should happen for non-owner in private DM"
        print("PASS: Non-owner private DM ignored")

        # Test 2: Non-owner in unapproved group (even when @mentioned) is ignored
        sent_messages.clear()
        captured_calls.clear()
        msg = make_message(NON_OWNER_USER_ID, GROUP_CHAT_ID, "supergroup", f"@{BOT_USERNAME} hello", BOT_USERNAME)
        await worker._handle_message(token, msg, BOT_USERNAME, BOT_ID)
        assert not sent_messages, "Non-owner in unapproved group should be silently ignored"
        assert not captured_calls, "No LLM call for non-owner in unapproved group"
        print("PASS: Non-owner in unapproved group ignored")

        # Test 3: Owner /approve command adds group to approved list
        sent_messages.clear()
        settings = await load_settings()
        assert str(GROUP_CHAT_ID) not in settings.telegram_state.approved_group_ids
        msg = make_message(OWNER_USER_ID, GROUP_CHAT_ID, "supergroup", f"/approve@{BOT_USERNAME}", BOT_USERNAME)
        await worker._handle_message(token, msg, BOT_USERNAME, BOT_ID)
        settings = await load_settings()
        assert str(GROUP_CHAT_ID) in settings.telegram_state.approved_group_ids, "Group should now be approved"
        print("PASS: /approve added group to approved list")

        # Test 4: Non-owner in now-approved group gets LLM response with restricted allowed_mcp_ids
        sent_messages.clear()
        captured_calls.clear()
        msg = make_message(NON_OWNER_USER_ID, GROUP_CHAT_ID, "supergroup", f"@{BOT_USERNAME} what can you do?", BOT_USERNAME)
        # Run the task created by _handle_message
        await worker._handle_message(token, msg, BOT_USERNAME, BOT_ID)
        # Give the task a moment to complete
        active_run = worker._active_runs.get(GROUP_CHAT_ID)
        if active_run is not None:
            task = active_run.get("task")
            if task is not None:
                await asyncio.wait_for(task, timeout=5.0)
        assert captured_calls, "LLM should be called for non-owner in approved group"
        last_call = captured_calls[-1]
        assert last_call.get("allowed_mcp_ids") == ["brain_access"], (
            f"Guest should get restricted MCP list, got: {last_call.get('allowed_mcp_ids')}"
        )
        print("PASS: Non-owner in approved group gets restricted MCP allowlist")

        # Test 5: owner_chat_id is NOT updated when owner sends from a group
        settings = await load_settings()
        original_owner_chat_id = settings.telegram_state.owner_chat_id
        msg = make_message(OWNER_USER_ID, GROUP_CHAT_ID, "supergroup", f"@{BOT_USERNAME} hello owner", BOT_USERNAME)
        await worker._handle_message(token, msg, BOT_USERNAME, BOT_ID)
        settings = await load_settings()
        assert settings.telegram_state.owner_chat_id == original_owner_chat_id, (
            f"owner_chat_id should not be updated from group. Got: {settings.telegram_state.owner_chat_id}"
        )
        print("PASS: owner_chat_id not updated from group message")

        # Test 6: /unapprove removes group from approved list
        sent_messages.clear()
        msg = make_message(OWNER_USER_ID, GROUP_CHAT_ID, "supergroup", f"/unapprove@{BOT_USERNAME}", BOT_USERNAME)
        await worker._handle_message(token, msg, BOT_USERNAME, BOT_ID)
        settings = await load_settings()
        assert str(GROUP_CHAT_ID) not in settings.telegram_state.approved_group_ids, (
            "Group should be removed after /unapprove"
        )
        print("PASS: /unapprove removed group from approved list")

    print("\nAll tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
