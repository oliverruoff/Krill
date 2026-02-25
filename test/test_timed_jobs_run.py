"""Creates a fresh instance, creates a timed job, and runs it."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


async def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    e2e_script = repo_root / "test" / "e2e_docker_test.py"
    spec = importlib.util.spec_from_file_location("krill_e2e_docker_test", e2e_script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load helper script: {e2e_script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    DEFAULT_ENV_FILE = getattr(module, "DEFAULT_ENV_FILE", ".env_test")
    DEFAULT_MODEL = getattr(module, "DEFAULT_MODEL", "gemini-2.5-flash")
    extract_key = getattr(module, "_extract_gemini_key", None)
    if not callable(extract_key):
        raise RuntimeError("_extract_gemini_key helper is missing in e2e_docker_test.py")

    env_path = (repo_root / DEFAULT_ENV_FILE).resolve()
    api_key = str(extract_key(env_path))

    temp_dir = Path(tempfile.mkdtemp(prefix="krill_timed_jobs_test_"))
    db_path = temp_dir / "braindump.db"
    os.environ["KRILL_BRAINDUMP_PATH"] = str(db_path)

    from app.config import (  # pylint: disable=import-outside-toplevel
        ProviderConfig,
        ensure_settings_file,
        list_due_timed_jobs,
        list_timed_jobs,
        load_settings,
        save_settings,
        upsert_timed_job,
    )
    import app.timed_jobs as timed_jobs  # pylint: disable=import-outside-toplevel

    await ensure_settings_file()
    settings = await load_settings()
    settings.setup_completed = True
    settings.bot_name = "KrillTimed"
    settings.system_prompt = "Be concise and practical."
    settings.active_provider_id = "gemini"
    settings.active_model_id = DEFAULT_MODEL
    settings.provider_configs["gemini"] = ProviderConfig(api_key=api_key, model=DEFAULT_MODEL)
    settings.chats = []
    settings.active_chat_id = ""
    await save_settings(settings)

    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    minute_value = now.strftime("%H:%M")
    timed_job = await upsert_timed_job(
        {
            "title": "Timed Job Test",
            "prompt": "Reply exactly with: TIMED_JOB_OK",
            "interval": "once",
            "start_date": today,
            "time_of_day": minute_value,
            "timezone": "UTC",
            "timezone_offset_minutes": 0,
            "enabled": True,
            "channels": ["gateway"],
        }
    )

    due_jobs = await list_due_timed_jobs()
    if not any(entry.id == timed_job.id for entry in due_jobs):
        raise RuntimeError("Timed job should be due but was not returned by due-jobs query.")

    await timed_jobs.run_due_timed_jobs_once()

    updated_settings = await load_settings()
    if not updated_settings.chats:
        raise RuntimeError("Timed job did not create a gateway chat.")

    first_chat = updated_settings.chats[0]
    assistant_messages = [
        message for message in first_chat.messages if message.role == "assistant" and message.content.strip()
    ]
    if not assistant_messages:
        raise RuntimeError("Timed job did not create an assistant output message.")

    timed_jobs_list = await list_timed_jobs()
    saved_job = next((entry for entry in timed_jobs_list if entry.id == timed_job.id), None)
    if saved_job is None:
        raise RuntimeError("Timed job was not persisted.")
    if saved_job.enabled:
        raise RuntimeError("One-time job should be disabled after execution.")
    if not saved_job.last_run_at.strip():
        raise RuntimeError("Timed job should contain last_run_at after execution.")

    print("PASS: timed job created and executed successfully.")
    print(f"DB: {db_path}")
    print(f"Model: {DEFAULT_MODEL}")
    print(f"Assistant output preview: {assistant_messages[-1].content[:200]}")


if __name__ == "__main__":
    asyncio.run(main())
