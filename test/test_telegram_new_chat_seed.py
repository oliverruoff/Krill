"""Smoke test for Telegram /new chat seed injection behavior.

This script uses the Telegram worker entrypoints with mocked transport/model calls.
It verifies that:
1) /new starts a Telegram chat session
2) runtime seed includes behavior + core memories
3) a follow-up question can be answered from seeded memory context
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


async def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    temp_dir = Path(tempfile.mkdtemp(prefix="krill_telegram_seed_test_"))
    db_path = temp_dir / "braindump.db"
    os.environ["KRILL_BRAINDUMP_PATH"] = str(db_path)

    from app.config import (  # pylint: disable=import-outside-toplevel
        IntegrationConfig,
        MemoryEntry,
        ProviderConfig,
        ensure_settings_file,
        load_settings,
        save_settings,
    )
    import app.integrations.telegram.worker as telegram_worker  # pylint: disable=import-outside-toplevel

    await ensure_settings_file()
    settings = await load_settings()

    settings.setup_completed = True
    settings.bot_name = "KrillDeutsch"
    settings.system_prompt = "Sprich nur Deutsch."
    settings.active_provider_id = "gemini"
    settings.provider_configs["gemini"] = ProviderConfig(api_key="", model="gemini-2.5-flash")
    settings.core_memories = [
        MemoryEntry(
            content="Die Lieblingsfarbe des Nutzers ist Gruen.",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    ]
    settings.integration_configs["telegram"] = IntegrationConfig(enabled=True, params={"bot_token": "dummy-token"})
    await save_settings(settings)

    sent_messages: list[str] = []
    captured_history: list[dict[str, str]] = []

    async def fake_generate_chat_response(**kwargs):
        history = kwargs.get("history", [])
        prompt = str(kwargs.get("message", ""))

        if isinstance(history, list):
            captured_history.clear()
            captured_history.extend(entry for entry in history if isinstance(entry, dict))

        if "lieblingsfarbe" in prompt.lower():
            return {
                "text": "Deine Lieblingsfarbe ist Gruen.",
                "used_tokens": 150,
                "used_mcp_tools": [],
                "system_trace_messages": [],
            }, 1000

        return {
            "text": "Ich antworte auf Deutsch.",
            "used_tokens": 120,
            "used_mcp_tools": [],
            "system_trace_messages": [],
        }, 1000

    def fake_send_message(token: str, chat_id: int, text: str):
        if token != "dummy-token":
            raise RuntimeError("Unexpected token in telegram_send_message mock.")
        if chat_id != 456:
            raise RuntimeError("Unexpected chat id in telegram_send_message mock.")
        sent_messages.append(text)
        return {"ok": True}

    original_generate = telegram_worker.generate_chat_response
    original_send = telegram_worker.telegram_send_message
    telegram_worker.generate_chat_response = fake_generate_chat_response
    telegram_worker.telegram_send_message = fake_send_message

    try:
        worker = telegram_worker.TelegramBridgeWorker()

        base_message = {
            "chat": {"id": 456, "type": "private"},
            "from": {"id": 123},
        }

        await worker._handle_message("dummy-token", {**base_message, "text": "/new"}, bot_username="krill_bot", bot_id=999)
        await worker._handle_message(
            "dummy-token",
            {**base_message, "text": "Was ist meine Lieblingsfarbe?"},
            bot_username="krill_bot",
            bot_id=999,
        )
    finally:
        telegram_worker.generate_chat_response = original_generate
        telegram_worker.telegram_send_message = original_send

    if len(sent_messages) < 2:
        raise RuntimeError(f"Expected at least 2 Telegram replies, got {len(sent_messages)}: {sent_messages}")

    if not any("Started new chat" in text for text in sent_messages):
        raise RuntimeError(f"Missing /new confirmation reply. Replies: {sent_messages}")

    answer = sent_messages[-1]
    if "Gruen" not in answer:
        raise RuntimeError(f"Expected memory-based answer with 'Gruen'. Got: {answer}")

    seed_messages = [entry for entry in captured_history if entry.get("role") == "system"]
    if not seed_messages:
        raise RuntimeError("No system seed message found in Telegram model history.")

    seed_text = "\n".join(str(entry.get("content", "")) for entry in seed_messages)
    if "Sprich nur Deutsch" not in seed_text:
        raise RuntimeError("Behavior prompt was not present in injected runtime seed.")
    if "Lieblingsfarbe" not in seed_text and "lieblingsfarbe" not in seed_text.lower():
        raise RuntimeError("Core memory was not present in injected runtime seed.")

    print("PASS: Telegram /new seed injection includes behavior + core memory and supports memory answer.")
    print(f"Temporary DB used: {db_path}")
    print(f"Replies: {sent_messages}")


if __name__ == "__main__":
    asyncio.run(main())
