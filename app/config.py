import asyncio
from pathlib import Path

from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
BRAINDUMP_PATH = DATA_DIR / "braindump.json"


class Settings(BaseModel):
    bot_name: str = Field(default="MyBot", max_length=15)
    system_prompt: str = Field(default="You are a helpful assistant.", max_length=100)
    api_key: str = ""


async def _read_text(path: Path) -> str:
    return await asyncio.to_thread(path.read_text, encoding="utf-8")


async def _write_text(path: Path, content: str) -> None:
    await asyncio.to_thread(path.write_text, content, encoding="utf-8")


async def ensure_settings_file() -> None:
    await asyncio.to_thread(DATA_DIR.mkdir, parents=True, exist_ok=True)

    if not BRAINDUMP_PATH.exists():
        await save_settings(Settings())


async def load_settings() -> Settings:
    await ensure_settings_file()
    payload = await _read_text(BRAINDUMP_PATH)
    return Settings.model_validate_json(payload)


async def save_settings(settings: Settings) -> Settings:
    await asyncio.to_thread(DATA_DIR.mkdir, parents=True, exist_ok=True)
    payload = settings.model_dump_json(indent=2)
    await _write_text(BRAINDUMP_PATH, payload)
    return settings
