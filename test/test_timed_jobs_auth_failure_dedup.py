"""Verifies timed-job auth failures notify once and do not tight-loop retry."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _oauth_fixture_json() -> str:
    return json.dumps(
        {
            "access_token": "oauth-access-placeholder",
            "refresh_token": "oauth-refresh-placeholder",
            "account_id": "oauth-account-placeholder",
            "expires_at_unix": 1,
        }
    )


async def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    temp_dir = Path(tempfile.mkdtemp(prefix="krill_timed_jobs_auth_dedup_"))
    db_path = temp_dir / "braindump.db"
    os.environ["KRILL_BRAINDUMP_PATH"] = str(db_path)

    from app.config import (  # pylint: disable=import-outside-toplevel
        ProviderConfig,
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
        api_key=_oauth_fixture_json(),
        model="gpt-5.3-codex",
    )
    await save_settings(settings)

    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    minute_value = now.strftime("%H:%M")

    first_job = await upsert_timed_job(
        {
            "title": "Auth dedupe 1",
            "prompt": "run",
            "interval": "once",
            "start_date": today,
            "time_of_day": minute_value,
            "timezone": "UTC",
            "timezone_offset_minutes": 0,
            "enabled": True,
            "channels": ["gateway"],
        }
    )
    second_job = await upsert_timed_job(
        {
            "title": "Auth dedupe 2",
            "prompt": "run",
            "interval": "once",
            "start_date": today,
            "time_of_day": minute_value,
            "timezone": "UTC",
            "timezone_offset_minutes": 0,
            "enabled": True,
            "channels": ["gateway"],
        }
    )

    dispatch_payloads: list[str] = []

    async def fake_generate_chat_response(**_: object) -> tuple[dict[str, object], int | None]:
        raise RuntimeError("OpenAI OAuth refresh token was rejected. Reconnect your OpenAI account.")

    async def fake_dispatch_all(**kwargs: object) -> None:
        dispatch_payloads.append(str(kwargs.get("safe_output", "")))

    original_generate = timed_jobs.generate_chat_response
    original_dispatch_all = timed_jobs._dispatch_all
    timed_jobs._AUTH_ALERT_SENT_BY_PROVIDER.clear()
    timed_jobs.generate_chat_response = fake_generate_chat_response
    timed_jobs._dispatch_all = fake_dispatch_all
    try:
        await timed_jobs.run_due_timed_jobs_once()
    finally:
        timed_jobs.generate_chat_response = original_generate
        timed_jobs._dispatch_all = original_dispatch_all

    if len(dispatch_payloads) != 1:
        raise RuntimeError(f"Expected exactly one auth reconnect notification, got {len(dispatch_payloads)}.")

    if "Reconnect this provider in Setup" not in dispatch_payloads[0]:
        raise RuntimeError("Expected reconnect guidance in the auth failure notification.")

    saved_jobs = await list_timed_jobs()
    first_saved = next((job for job in saved_jobs if job.id == first_job.id), None)
    second_saved = next((job for job in saved_jobs if job.id == second_job.id), None)
    if first_saved is None or second_saved is None:
        raise RuntimeError("Expected both timed jobs to be persisted.")

    if first_saved.enabled or second_saved.enabled:
        raise RuntimeError("One-time timed jobs should be marked executed and disabled even after auth failure.")

    if not first_saved.last_run_at.strip() or not second_saved.last_run_at.strip():
        raise RuntimeError("Timed jobs should record last_run_at after auth failure execution.")

    print("PASS: timed-job auth failures send one reconnect notification and advance schedules.")
    print(f"DB: {db_path}")


if __name__ == "__main__":
    asyncio.run(main())
