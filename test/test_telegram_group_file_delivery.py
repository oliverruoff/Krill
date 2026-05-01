"""Smoke test for Telegram group shared-file delivery.

This script verifies that an owner message in a Telegram group can trigger a
shared-file response and that the Telegram integration uploads the file to the
group with sendDocument instead of leaving only the shared download URL in chat.
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

    temp_dir = Path(tempfile.mkdtemp(prefix="krill_telegram_group_file_test_"))
    db_path = temp_dir / "braindump.db"
    os.environ["KRILL_BRAINDUMP_PATH"] = str(db_path)

    from app.config import (  # pylint: disable=import-outside-toplevel
        IntegrationConfig,
        ProviderConfig,
        ensure_settings_file,
        load_settings,
        save_settings,
    )
    from app.shared_files import create_shared_file_link  # pylint: disable=import-outside-toplevel
    import app.integrations.telegram.worker as telegram_worker  # pylint: disable=import-outside-toplevel

    await ensure_settings_file()
    settings = await load_settings()

    settings.setup_completed = True
    settings.active_provider_id = "gemini"
    settings.provider_configs["gemini"] = ProviderConfig(api_key="", model="gemini-2.5-flash")
    settings.integration_configs["telegram"] = IntegrationConfig(enabled=True, params={"bot_token": "dummy-token"})

    OWNER_USER_ID = 111111
    OWNER_CHAT_ID = 222222
    GROUP_CHAT_ID = -1001234567890
    BOT_USERNAME = "testbot"
    BOT_ID = 42

    settings.telegram_state.owner_user_id = str(OWNER_USER_ID)
    settings.telegram_state.owner_chat_id = str(OWNER_CHAT_ID)
    settings.telegram_state.approved_group_ids = []
    await save_settings(settings)

    file_bytes = b"telegram group file delivery\n"
    shared_path = temp_dir / "group-report.txt"
    shared_path.write_bytes(file_bytes)

    sent_messages: list[dict[str, Any]] = []
    sent_documents: list[dict[str, Any]] = []
    shared_download_url = ""

    def fake_telegram_send_message(token: str, chat_id: int, text: str, parse_mode: str | None = None) -> dict[str, object]:
        sent_messages.append({"token": token, "chat_id": chat_id, "text": text, "parse_mode": parse_mode})
        return {"ok": True, "result": {"message_id": len(sent_messages)}}

    def fake_telegram_send_document(
        token: str,
        chat_id: int,
        document_bytes: bytes,
        filename: str = "file.bin",
        caption: str | None = None,
        parse_mode: str | None = None,
        mime_type: str = "application/octet-stream",
    ) -> dict[str, object]:
        sent_documents.append(
            {
                "token": token,
                "chat_id": chat_id,
                "document_bytes": document_bytes,
                "filename": filename,
                "caption": caption,
                "parse_mode": parse_mode,
                "mime_type": mime_type,
            }
        )
        return {"ok": True, "result": {"message_id": 9001}}

    async def fake_generate_chat_response(**kwargs: object) -> tuple[dict[str, object], int]:
        nonlocal shared_download_url
        assert kwargs.get("source_room_id") == str(GROUP_CHAT_ID), kwargs
        assert kwargs.get("source_room_mode") == "supergroup", kwargs
        link_payload = await create_shared_file_link(
            shared_path,
            download_name="group-report.txt",
            ttl_seconds=3600,
        )
        shared_download_url = str(link_payload["download_url"])
        return {
            "text": f"Here is the group report:\n\n{shared_download_url}\n\nAll set.",
            "used_tokens": 0,
            "used_mcp_tools": [],
            "system_trace_messages": [],
        }, 10000

    message = {
        "from": {"id": OWNER_USER_ID, "is_bot": False, "first_name": "Olive"},
        "chat": {"id": GROUP_CHAT_ID, "type": "supergroup"},
        "text": f"@{BOT_USERNAME} please create the report file",
        "entities": [{"type": "mention", "offset": 0, "length": len(f"@{BOT_USERNAME}")}],
    }

    worker = telegram_worker.TelegramBridgeWorker()

    with (
        patch.object(telegram_worker, "telegram_send_message", side_effect=fake_telegram_send_message),
        patch.object(telegram_worker, "telegram_send_document", side_effect=fake_telegram_send_document),
        patch("app.integrations.telegram.worker.generate_chat_response", side_effect=fake_generate_chat_response),
        patch("app.integrations.telegram.worker.register_user_message_and_maybe_extract", new_callable=AsyncMock),
        patch("app.integrations.telegram.worker.register_completed_turn", new_callable=AsyncMock),
        patch("app.integrations.telegram.worker.add_daily_usage"),
        patch("app.integrations.telegram.worker.ensure_runtime_context_seed"),
    ):
        await worker._handle_message("dummy-token", message, BOT_USERNAME, BOT_ID)
        active_run = worker._active_runs.get(GROUP_CHAT_ID)
        assert active_run is not None, "Expected group message to start an active Telegram run"
        await asyncio.wait_for(active_run["task"], timeout=5.0)

    assert shared_download_url, "Mock model did not create a shared-file URL"
    assert sent_documents, "Expected Telegram document upload for shared-file response"
    assert len(sent_documents) == 1, f"Expected 1 uploaded document, got {sent_documents!r}"

    document = sent_documents[0]
    assert document["token"] == "dummy-token"
    assert document["chat_id"] == GROUP_CHAT_ID, f"Document should be sent to group chat id: {document!r}"
    assert document["document_bytes"] == file_bytes
    assert document["filename"] == "group-report.txt"
    assert document["mime_type"] == "text/plain"

    assert sent_messages, "Expected a text response alongside the document upload"
    response_texts = [str(entry["text"]) for entry in sent_messages]
    assert not any(shared_download_url in text for text in response_texts), (
        f"Shared URL should be stripped from Telegram text responses: {response_texts!r}"
    )
    assert any("Here is the group report" in text for text in response_texts), response_texts

    settings = await load_settings()
    assert settings.telegram_state.owner_chat_id == str(OWNER_CHAT_ID), (
        "Owner group message should not replace the private owner_chat_id"
    )

    print("PASS: Telegram owner group messages upload shared files to the group with sendDocument.")
    print(f"Temporary DB used: {db_path}")


if __name__ == "__main__":
    asyncio.run(main())
