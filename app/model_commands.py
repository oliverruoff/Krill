"""Shared provider/model slash command helpers for Gateway and chat integrations."""

from __future__ import annotations

from pydantic import BaseModel

from .config import Settings, load_settings, save_settings
from .providers import get_provider_options


class ModelCommandResult(BaseModel):
    ok: bool = True
    text: str
    settings: Settings | None = None
    command_name: str = "model"
    provider_id: str = ""
    model_id: str = ""


class ParsedModelCommand(BaseModel):
    command_name: str = "model"
    argument: str = ""


class ModelCommandEntry(BaseModel):
    provider_id: str
    provider_label: str
    model_id: str
    model_label: str


def parse_model_chat_command(text: str) -> ParsedModelCommand | None:
    raw_text = str(text or "").strip()
    if not raw_text.startswith("/"):
        return None

    body = raw_text[1:].strip()
    if not body:
        return None

    first_token, _, remainder = body.partition(" ")
    command_name = first_token.strip().lower()
    if command_name != "model":
        return None

    return ParsedModelCommand(argument=remainder.strip())


async def execute_model_command(argument: str = "") -> ModelCommandResult:
    normalized_argument = str(argument or "").strip()
    settings = await load_settings()
    entries = _build_model_entries(settings)
    if not entries:
        return ModelCommandResult(ok=False, text="No connected providers are configured.", settings=settings)

    if not normalized_argument:
        return ModelCommandResult(text=_format_model_list(settings, entries), settings=settings)

    provider_id, model_id = _parse_provider_model_selector(normalized_argument)
    if not provider_id or not model_id:
        return ModelCommandResult(
            ok=False,
            text="Use /model <provider>/<model> to switch.",
            settings=settings,
        )

    provider_entries = [entry for entry in entries if entry.provider_id == provider_id]
    if not provider_entries:
        return ModelCommandResult(
            ok=False,
            text=f"Provider '{provider_id}' is not connected. Use /model to list available models.",
            settings=settings,
            provider_id=provider_id,
            model_id=model_id,
        )

    selected_entry = next((entry for entry in provider_entries if entry.model_id == model_id), None)
    if selected_entry is None:
        return ModelCommandResult(
            ok=False,
            text=f"Model '{model_id}' is not available for provider '{provider_id}'. Use /model to list available models.",
            settings=settings,
            provider_id=provider_id,
            model_id=model_id,
        )

    provider_config = settings.provider_configs.get(provider_id)
    if provider_config is None:
        return ModelCommandResult(
            ok=False,
            text=f"Provider '{provider_id}' is not connected. Use /model to list available models.",
            settings=settings,
            provider_id=provider_id,
            model_id=model_id,
        )

    updated_provider_configs = dict(settings.provider_configs)
    updated_provider_configs[provider_id] = provider_config.model_copy(update={"model": model_id})
    updated_settings = settings.model_copy(
        update={
            "active_provider_id": provider_id,
            "active_model_id": model_id,
            "provider_configs": updated_provider_configs,
        }
    )
    persisted = await save_settings(updated_settings)
    return ModelCommandResult(
        text=f"Switched active model to {provider_id}/{model_id} ({selected_entry.model_label}).",
        settings=persisted,
        provider_id=provider_id,
        model_id=model_id,
    )


def _build_model_entries(settings: Settings) -> list[ModelCommandEntry]:
    connected_provider_ids = set(settings.provider_configs.keys())
    entries: list[ModelCommandEntry] = []
    for provider in get_provider_options():
        provider_id = str(provider.get("id", "")).strip()
        if not provider_id or provider_id not in connected_provider_ids:
            continue

        provider_label = str(provider.get("label", "")).strip() or provider_id
        models = provider.get("models")
        if not isinstance(models, list):
            continue

        for model in models:
            if not isinstance(model, dict):
                continue
            model_id = str(model.get("id", "")).strip()
            if not model_id:
                continue
            model_label = str(model.get("label", "")).strip() or model_id
            entries.append(
                ModelCommandEntry(
                    provider_id=provider_id,
                    provider_label=provider_label,
                    model_id=model_id,
                    model_label=model_label,
                )
            )
    return entries


def _format_model_list(settings: Settings, entries: list[ModelCommandEntry]) -> str:
    active_provider = settings.active_provider_id.strip()
    active_model = settings.active_model_id.strip()
    if not active_model and active_provider:
        provider_config = settings.provider_configs.get(active_provider)
        active_model = provider_config.model.strip() if provider_config is not None else ""

    active_label = f"{active_provider}/{active_model}" if active_provider and active_model else "none"
    lines = [f"Active model: {active_label}", "Available models:"]
    for entry in entries:
        lines.append(f"{entry.provider_id}/{entry.model_id} - {entry.model_label}")
    lines.append("Use /model <provider>/<model> to switch.")
    return "\n".join(lines)


def _parse_provider_model_selector(argument: str) -> tuple[str, str]:
    provider_id, separator, model_id = str(argument or "").strip().partition("/")
    if not separator:
        return "", ""
    return provider_id.strip(), model_id.strip()
