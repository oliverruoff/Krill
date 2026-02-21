import asyncio
import json
from pathlib import Path

from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
BRAINDUMP_PATH = DATA_DIR / "braindump.json"


class ProviderConfig(BaseModel):
    api_key: str = ""
    model: str = ""


class Settings(BaseModel):
    bot_name: str = Field(default="MyBot", max_length=15)
    system_prompt: str = Field(default="You are a helpful assistant.", max_length=100)
    setup_completed: bool = False
    active_provider_id: str = ""
    provider_configs: dict[str, ProviderConfig] = Field(default_factory=dict)


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
    raw_json = json.loads(payload)
    raw_data = raw_json if isinstance(raw_json, dict) else {}
    normalized_data = _normalize_legacy_settings(raw_data)
    settings = Settings.model_validate(normalized_data)

    if raw_data != settings.model_dump():
        await save_settings(settings)

    return settings


async def save_settings(settings: Settings) -> Settings:
    await asyncio.to_thread(DATA_DIR.mkdir, parents=True, exist_ok=True)
    payload = settings.model_dump_json(indent=2)
    await _write_text(BRAINDUMP_PATH, payload)
    return settings


def _normalize_legacy_settings(raw_data: dict[str, object]) -> dict[str, object]:
    data = dict(raw_data)
    provider_configs = data.get("provider_configs")

    if not isinstance(provider_configs, dict):
        provider_configs = {}

    legacy_provider = data.get("llm_provider")
    legacy_key = data.get("api_key")

    if not provider_configs and isinstance(legacy_provider, str) and legacy_provider:
        provider_configs[legacy_provider] = {
            "api_key": legacy_key if isinstance(legacy_key, str) else "",
            "model": "",
        }

    data["provider_configs"] = provider_configs

    active_provider_id = data.get("active_provider_id")
    if not isinstance(active_provider_id, str):
        active_provider_id = ""

    if not active_provider_id and provider_configs:
        active_provider_id = next(iter(provider_configs.keys()))

    data["active_provider_id"] = active_provider_id

    setup_completed = data.get("setup_completed")
    if not isinstance(setup_completed, bool):
        setup_completed = bool(provider_configs)

    data["setup_completed"] = setup_completed

    return data
