from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path


repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.environ["KRILL_BRAINDUMP_PATH"] = str(Path(tmp_dir) / "braindump.db")

        from app.config import (  # pylint: disable=import-outside-toplevel
            MemoryEntry,
            append_memory_entry,
            increment_daily_token_usage,
            load_settings,
            save_settings,
        )

        settings = await load_settings()
        settings.setup_completed = True
        await save_settings(settings)

        stale_settings = await load_settings()
        await append_memory_entry(
            "normal",
            MemoryEntry(content="Oli and Jenny will stay at the Sofitel in Beijing."),
        )

        stale_settings.daily_token_usage = await increment_daily_token_usage(123)
        persisted = await load_settings()
        memories = [entry.content for entry in persisted.normal_memories]
        if "Oli and Jenny will stay at the Sofitel in Beijing." not in memories:
            raise RuntimeError(f"Memory disappeared after token usage update: {memories!r}")

        if not any(entry.tokens >= 123 for entry in stale_settings.daily_token_usage):
            raise RuntimeError(f"Token usage increment was not returned: {stale_settings.daily_token_usage!r}")

    print("PASS: token usage updates preserve direct memory writes.")


if __name__ == "__main__":
    asyncio.run(main())
