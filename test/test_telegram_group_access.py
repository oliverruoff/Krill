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

    async def wait_for_active_run(chat_id: int) -> None:
        active_run = worker._active_runs.get(chat_id)
        if active_run is not None:
            task = active_run.get("task")
            if task is not None:
                await asyncio.wait_for(task, timeout=5.0)

    def find_telegram_context(call: dict[str, Any]) -> str:
        history = call.get("history")
        assert isinstance(history, list), f"Expected history list, got: {history!r}"
        contexts = [
            str(entry.get("content", ""))
            for entry in history
            if isinstance(entry, dict)
            and entry.get("role") == "system"
            and "Telegram identity rules:" in str(entry.get("content", ""))
        ]
        assert contexts, f"Telegram integration context missing from history: {history!r}"
        return contexts[-1]

    def make_message(
        from_id: int,
        chat_id: int,
        chat_type: str,
        text: str,
        bot_username: str = "",
        first_name: str = "",
        last_name: str = "",
        username: str = "",
    ) -> dict[str, Any]:
        entities = []
        if text.startswith("/") and "@" in text and bot_username:
            entities.append({"type": "bot_command", "offset": 0, "length": len(text.split()[0])})
        elif f"@{bot_username}" in text:
            idx = text.index(f"@{bot_username}")
            entities.append({"type": "mention", "offset": idx, "length": len(f"@{bot_username}")})
        sender: dict[str, Any] = {"id": from_id, "is_bot": False}
        if first_name:
            sender["first_name"] = first_name
        if last_name:
            sender["last_name"] = last_name
        if username:
            sender["username"] = username
        return {
            "from": sender,
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
        # Test 0: First contact from a group must not bind that sender as owner
        settings = await load_settings()
        settings.telegram_state.owner_user_id = ""
        settings.telegram_state.owner_chat_id = ""
        await save_settings(settings)
        sent_messages.clear()
        captured_calls.clear()
        msg = make_message(NON_OWNER_USER_ID, GROUP_CHAT_ID, "supergroup", f"@{BOT_USERNAME} hello", BOT_USERNAME)
        await worker._handle_message(token, msg, BOT_USERNAME, BOT_ID)
        settings = await load_settings()
        assert settings.telegram_state.owner_user_id == "", "Group sender should not be auto-bound as owner"
        assert not sent_messages, "Unbound group contact should be ignored"
        assert not captured_calls, "No LLM call should happen before owner private binding"
        settings.telegram_state.owner_user_id = str(OWNER_USER_ID)
        settings.telegram_state.owner_chat_id = str(OWNER_CHAT_ID)
        await save_settings(settings)
        print("PASS: Group message cannot auto-bind owner")

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
        msg = make_message(
            NON_OWNER_USER_ID,
            GROUP_CHAT_ID,
            "supergroup",
            f"@{BOT_USERNAME} do you know who I am?",
            BOT_USERNAME,
            first_name="Guest",
            last_name="Person",
            username="guestperson",
        )
        # Run the task created by _handle_message
        await worker._handle_message(token, msg, BOT_USERNAME, BOT_ID)
        # Give the task a moment to complete
        await wait_for_active_run(GROUP_CHAT_ID)
        assert captured_calls, "LLM should be called for non-owner in approved group"
        last_call = captured_calls[-1]
        assert last_call.get("allowed_mcp_ids") == ["brain_access"], (
            f"Guest should get restricted MCP list, got: {last_call.get('allowed_mcp_ids')}"
        )
        assert last_call.get("source_user_role") == "assistant_usage", (
            f"Guest should have source_user_role='assistant_usage' so orchestrator enforces allowlist, "
            f"got: {last_call.get('source_user_role')!r}"
        )
        guest_context = find_telegram_context(last_call)
        assert f"Telegram current sender id: {NON_OWNER_USER_ID}" in guest_context, guest_context
        assert "Telegram current sender display name: Guest P." in guest_context, guest_context
        assert "Telegram current sender username: @guestperson" in guest_context, guest_context
        assert "Telegram current sender role: assistant_usage" in guest_context, guest_context
        assert "This current sender is not the configured owner." in guest_context, guest_context
        assert "Do not claim this sender is the owner" in guest_context, guest_context
        print("PASS: Non-owner in approved group gets restricted MCP allowlist")
        print("PASS: Non-owner group request injects guest sender identity context")

        # Test 5: owner_chat_id is NOT updated when owner sends from a group
        captured_calls.clear()
        settings = await load_settings()
        original_owner_chat_id = settings.telegram_state.owner_chat_id
        msg = make_message(
            OWNER_USER_ID,
            GROUP_CHAT_ID,
            "supergroup",
            f"@{BOT_USERNAME} hello owner",
            BOT_USERNAME,
            first_name="Olive",
            last_name="Owner",
            username="oliveowner",
        )
        await worker._handle_message(token, msg, BOT_USERNAME, BOT_ID)
        await wait_for_active_run(GROUP_CHAT_ID)
        settings = await load_settings()
        assert settings.telegram_state.owner_chat_id == original_owner_chat_id, (
            f"owner_chat_id should not be updated from group. Got: {settings.telegram_state.owner_chat_id}"
        )
        assert captured_calls, "Owner group message should call the LLM"
        owner_context = find_telegram_context(captured_calls[-1])
        assert f"Telegram current sender id: {OWNER_USER_ID}" in owner_context, owner_context
        assert "Telegram current sender display name: Olive O." in owner_context, owner_context
        assert "Telegram current sender username: @oliveowner" in owner_context, owner_context
        assert "Telegram current sender role: owner" in owner_context, owner_context
        assert "This current sender is not the configured owner." not in owner_context, owner_context
        print("PASS: owner_chat_id not updated from group message")
        print("PASS: Owner group request injects owner sender identity context")

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
