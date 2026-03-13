"""Verifies empty timed-job output stays silent for integrations but preserves Gateway debug history."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


async def _run_scenario(*, channels: list[str], expect_gateway_debug_chat: bool) -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="krill_timed_jobs_suppressed_empty_output_"))
    db_path = temp_dir / "braindump.db"
    os.environ["KRILL_BRAINDUMP_PATH"] = str(db_path)

    from app.config import (  # pylint: disable=import-outside-toplevel
        IntegrationConfig,
        ProviderConfig,
        TelegramState,
        ensure_settings_file,
        list_timed_jobs,
        load_settings,
        save_settings,
        upsert_timed_job,
    )
    import app.timed_jobs as timed_jobs  # pylint: disable=import-outside-toplevel

    await ensure_settings_file()
    settings = await load_settings()
    settings.setup_completed = True
    settings.active_provider_id = "openai_codex_oauth"
    settings.provider_configs["openai_codex_oauth"] = ProviderConfig(
        api_key='{"access_token":"x","refresh_token":"y","account_id":"a","expires_at_unix":1}',
        model="gpt-5.3-codex",
    )
    settings.integration_configs["telegram"] = IntegrationConfig(enabled=True, params={"bot_token": "dummy-token"})
    settings.telegram_state = TelegramState(owner_user_id="123", owner_chat_id="123", last_update_id=0)
    settings.chats = []
    await save_settings(settings)

    now = datetime.now(timezone.utc)
    timed_job = await upsert_timed_job(
        {
            "title": "Suppressed Empty Output",
            "prompt": "Only notify me if there is something important.",
            "interval": "once",
            "start_date": now.date().isoformat(),
            "time_of_day": now.strftime("%H:%M"),
            "timezone": "UTC",
            "timezone_offset_minutes": 0,
            "enabled": True,
            "output_decision_enabled": True,
            "channels": channels,
        }
    )

    dispatch_payloads: list[str] = []
    completed_turns: list[str] = []

    async def fake_generate_chat_response(**_: object) -> tuple[dict[str, object], int | None]:
        raise RuntimeError("OpenAI OAuth provider returned an empty response.")

    async def fake_dispatch_all(**kwargs: object) -> None:
        dispatch_payloads.append(str(kwargs.get("safe_output", "")))

    async def fake_register_completed_turn(**kwargs: object) -> None:
        completed_turns.append(str(kwargs.get("assistant_message", "")))

    original_generate = timed_jobs.generate_chat_response
    original_dispatch_all = timed_jobs._dispatch_all
    original_register_completed_turn = timed_jobs.register_completed_turn
    timed_jobs.generate_chat_response = fake_generate_chat_response
    timed_jobs._dispatch_all = fake_dispatch_all
    timed_jobs.register_completed_turn = fake_register_completed_turn
    try:
        await timed_jobs.run_due_timed_jobs_once()
    finally:
        timed_jobs.generate_chat_response = original_generate
        timed_jobs._dispatch_all = original_dispatch_all
        timed_jobs.register_completed_turn = original_register_completed_turn

    if dispatch_payloads:
        raise RuntimeError(f"Expected no timed-job integration dispatches, got: {dispatch_payloads}")

    if completed_turns:
        raise RuntimeError(f"Expected no completed-turn memory entries, got: {completed_turns}")

    saved_jobs = await list_timed_jobs()
    saved_job = next((job for job in saved_jobs if job.id == timed_job.id), None)
    if saved_job is None:
        raise RuntimeError("Expected timed job to be persisted.")
    if saved_job.enabled:
        raise RuntimeError("One-time timed job should be marked executed after suppressed empty output.")
    if not saved_job.last_run_at.strip():
        raise RuntimeError("Timed job should record last_run_at after suppressed empty output.")

    refreshed_settings = await load_settings()
    if expect_gateway_debug_chat:
        if len(refreshed_settings.chats) != 1:
            raise RuntimeError(f"Expected one hidden Gateway debug chat, got {len(refreshed_settings.chats)}.")
        hidden_chat = refreshed_settings.chats[0]
        if not hidden_chat.title.startswith("[Hidden] "):
            raise RuntimeError(f"Expected hidden Gateway debug chat title, got {hidden_chat.title!r}.")
        if not any(message.system_type == timed_jobs.TIMED_JOB_HIDDEN_CHAT_SYSTEM_TYPE for message in hidden_chat.messages):
            raise RuntimeError("Expected hidden Gateway debug system message in suppressed chat.")
    elif refreshed_settings.chats:
        raise RuntimeError("Telegram-only suppressed empty output should not create any Gateway chat history entry.")


async def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    await _run_scenario(channels=["telegram"], expect_gateway_debug_chat=False)
    await _run_scenario(channels=["gateway", "telegram"], expect_gateway_debug_chat=True)

    print("PASS: empty timed-job output stays silent on Telegram and keeps hidden Gateway debug history when selected.")


if __name__ == "__main__":
    asyncio.run(main())
