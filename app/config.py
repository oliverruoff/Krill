import asyncio
import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_BRAINDUMP_PATH = BASE_DIR / "data" / "braindump.json"
BRAINDUMP_PATH = Path(os.getenv("KRILL_BRAINDUMP_PATH", str(DEFAULT_BRAINDUMP_PATH))).resolve()
DATA_DIR = BRAINDUMP_PATH.parent


class ProviderConfig(BaseModel):
    api_key: str = ""
    model: str = ""


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(default="", max_length=200000)
    timestamp: str = ""
    system_type: str = ""
    tool_usage: list[dict[str, str]] = Field(default_factory=list)
    request_id: str = ""
    status: str = ""


class ChatSession(BaseModel):
    id: str
    title: str = Field(default="New chat", max_length=120)
    type: Literal["normal"] = "normal"
    messages: list[ChatMessage] = Field(default_factory=list)
    memory_block: str = Field(default="", max_length=8000)
    total_tokens_used: int = Field(default=0, ge=0)
    collapse_system_trace: bool = True


class McpConfig(BaseModel):
    enabled: bool = False
    params: dict[str, str] = Field(default_factory=dict)


class Settings(BaseModel):
    bot_name: str = Field(default="MyBot", max_length=15)
    system_prompt: str = Field(default="Talk english. Be playful, friendly and use emojis! :).", max_length=200)
    setup_completed: bool = False
    active_provider_id: str = ""
    active_model_id: str = ""
    provider_configs: dict[str, ProviderConfig] = Field(default_factory=dict)
    chats: list[ChatSession] = Field(default_factory=list)
    mcp_configs: dict[str, McpConfig] = Field(default_factory=dict)


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
    normalized = _sync_active_selection(settings)
    payload = normalized.model_dump_json(indent=2)
    await _write_text(BRAINDUMP_PATH, payload)
    return normalized


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

    active_model_id = data.get("active_model_id")
    if not isinstance(active_model_id, str):
        active_model_id = ""
    data["active_model_id"] = active_model_id

    setup_completed = data.get("setup_completed")
    if not isinstance(setup_completed, bool):
        setup_completed = bool(provider_configs)

    data["setup_completed"] = setup_completed

    normalized_provider_configs: dict[str, dict[str, object]] = {}
    for provider_id, raw_provider_config in provider_configs.items():
        if not isinstance(provider_id, str) or not isinstance(raw_provider_config, dict):
            continue

        model = raw_provider_config.get("model")
        model_id = model.strip() if isinstance(model, str) else ""

        normalized_provider_configs[provider_id] = {
            "api_key": raw_provider_config.get("api_key", "") if isinstance(raw_provider_config.get("api_key"), str) else "",
            "model": model_id,
        }

    data["provider_configs"] = normalized_provider_configs

    chats = data.get("chats")
    normalized_chats: list[dict[str, object]] = []
    if isinstance(chats, list):
        for raw_chat in chats:
            if not isinstance(raw_chat, dict):
                continue

            chat_id = raw_chat.get("id")
            chat_title = raw_chat.get("title")
            raw_messages = raw_chat.get("messages")
            memory_block = raw_chat.get("memory_block")
            total_tokens_used = raw_chat.get("total_tokens_used")
            collapse_system_trace = raw_chat.get("collapse_system_trace")

            if not isinstance(chat_id, str) or not chat_id.strip():
                continue

            messages: list[dict[str, object]] = []
            if isinstance(raw_messages, list):
                for raw_message in raw_messages:
                    if not isinstance(raw_message, dict):
                        continue

                    role = raw_message.get("role")
                    content = raw_message.get("content")
                    timestamp = raw_message.get("timestamp")
                    system_type = raw_message.get("system_type")
                    raw_tool_usage = raw_message.get("tool_usage")
                    request_id = raw_message.get("request_id")
                    status = raw_message.get("status")

                    if role not in {"user", "assistant", "system"}:
                        continue

                    if not isinstance(content, str):
                        content = ""

                    if not isinstance(timestamp, str):
                        timestamp = ""

                    if not isinstance(system_type, str):
                        system_type = ""

                    if not isinstance(request_id, str):
                        request_id = ""

                    if not isinstance(status, str):
                        status = ""

                    tool_usage: list[dict[str, str]] = []
                    if isinstance(raw_tool_usage, list):
                        for tool_entry in raw_tool_usage:
                            if not isinstance(tool_entry, dict):
                                continue

                            mcp_id = tool_entry.get("mcp_id")
                            mcp_label = tool_entry.get("mcp_label")
                            tool_id = tool_entry.get("tool_id")
                            tool_label = tool_entry.get("tool_label")

                            if not isinstance(mcp_id, str) or not isinstance(tool_id, str):
                                continue

                            tool_usage.append(
                                {
                                    "mcp_id": mcp_id,
                                    "mcp_label": mcp_label if isinstance(mcp_label, str) else "",
                                    "tool_id": tool_id,
                                    "tool_label": tool_label if isinstance(tool_label, str) else "",
                                }
                            )

                    messages.append(
                        {
                            "role": role,
                            "content": content,
                            "timestamp": timestamp,
                            "system_type": system_type,
                            "tool_usage": tool_usage,
                            "request_id": request_id,
                            "status": status,
                        }
                    )

            total_tokens = total_tokens_used if isinstance(total_tokens_used, int) and total_tokens_used > 0 else 0

            normalized_chats.append(
                {
                    "id": chat_id.strip(),
                    "title": chat_title.strip() if isinstance(chat_title, str) and chat_title.strip() else "New chat",
                    "type": "normal",
                    "messages": messages,
                    "memory_block": memory_block if isinstance(memory_block, str) else "",
                    "total_tokens_used": total_tokens,
                    "collapse_system_trace": collapse_system_trace if isinstance(collapse_system_trace, bool) else True,
                }
            )

    data["chats"] = normalized_chats

    raw_mcp_configs = data.get("mcp_configs")
    normalized_mcp_configs: dict[str, dict[str, object]] = {}
    if isinstance(raw_mcp_configs, dict):
        for mcp_id, raw_config in raw_mcp_configs.items():
            if not isinstance(mcp_id, str) or not isinstance(raw_config, dict):
                continue

            enabled = raw_config.get("enabled")
            params = raw_config.get("params")
            normalized_params: dict[str, str] = {}

            if isinstance(params, dict):
                for key, value in params.items():
                    if not isinstance(key, str):
                        continue
                    normalized_params[key] = str(value) if value is not None else ""

            normalized_mcp_configs[mcp_id] = {
                "enabled": bool(enabled),
                "params": normalized_params,
            }

    data["mcp_configs"] = normalized_mcp_configs

    return data


def _sync_active_selection(settings: Settings) -> Settings:
    provider_configs = settings.provider_configs
    active_provider_id = settings.active_provider_id

    if active_provider_id and active_provider_id not in provider_configs:
        active_provider_id = ""

    if not active_provider_id and provider_configs:
        active_provider_id = next(iter(provider_configs.keys()))

    active_model_id = ""
    if active_provider_id:
        active_config = provider_configs.get(active_provider_id)
        if active_config is not None:
            active_model_id = active_config.model.strip()

    return settings.model_copy(
        update={
            "active_provider_id": active_provider_id,
            "active_model_id": active_model_id,
        }
    )
