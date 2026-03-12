"""Verifies every-2-hours timed jobs normalize and schedule correctly."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import date, datetime, time, timezone
from pathlib import Path


async def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    temp_dir = Path(tempfile.mkdtemp(prefix="krill_timed_jobs_every_2_hours_"))
    db_path = temp_dir / "braindump.db"
    os.environ["KRILL_BRAINDUMP_PATH"] = str(db_path)

    from app.config import (  # pylint: disable=import-outside-toplevel
        _calculate_next_run_at,
        _normalize_interval,
        _server_timezone,
        ensure_settings_file,
        upsert_timed_job,
    )

    await ensure_settings_file()

    normalized = _normalize_interval("every_2_hours")
    if normalized != "every_2_hours":
        raise RuntimeError(f"Expected every_2_hours normalization, got {normalized!r}.")

    _, server_tz = _server_timezone()
    now_utc = datetime(2026, 3, 12, 8, 1, tzinfo=server_tz).astimezone(timezone.utc)
    next_run_at = _calculate_next_run_at(
        interval="every_2_hours",
        start_date_value=date(2026, 3, 12),
        time_value=time(8, 0),
        now_utc=now_utc,
    )
    local_next = datetime.fromisoformat(next_run_at).astimezone(server_tz)
    expected_next_run_at = datetime(2026, 3, 12, 10, 0, tzinfo=server_tz).astimezone(timezone.utc).isoformat()
    if next_run_at != expected_next_run_at:
        raise RuntimeError(f"Expected next run at {expected_next_run_at!r}, got {next_run_at!r}.")
    if local_next.hour != 10 or local_next.minute != 0:
        raise RuntimeError(f"Expected local next run at 10:00, got {local_next.isoformat()!r}.")

    job = await upsert_timed_job(
        {
            "title": "Every 2 Hours Test",
            "prompt": "run",
            "interval": "every_2_hours",
            "start_date": "2026-03-12",
            "time_of_day": "08:00",
            "timezone": "UTC",
            "timezone_offset_minutes": 0,
            "enabled": True,
            "channels": ["gateway"],
        }
    )
    if job.interval != "every_2_hours":
        raise RuntimeError(f"Expected persisted interval every_2_hours, got {job.interval!r}.")

    print("PASS: every_2_hours timed jobs normalize, schedule, and persist correctly.")
    print(f"DB: {db_path}")


if __name__ == "__main__":
    asyncio.run(main())
