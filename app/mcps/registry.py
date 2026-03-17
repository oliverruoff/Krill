"""Registry of MCP plugins that can be enabled and called by orchestration."""

from .base import MCPPlugin, McpConfigField, McpToolSpec
from .browser_control import BrowserControlMCP
from .brave_search import BraveSearchMCP
from .git_ops import GitOpsMCP
from .home_assistant import HomeAssistantMCP
from .local_files import LocalFilesMCP
from .memory_access import MemoryAccessMCP
from .google_services import GoogleServicesMCP
from .opencode import OpenCodeMCP
from .ssh_control import SSHControlMCP
from .scripts import ScriptsMCP
from .timed_jobs import TimedJobsMCP
from .whatsapp import WhatsAppMCP
from .text_to_speech import TextToSpeechMCP
from .youtube_summarizer import YouTubeSummarizerMCP


_MCPS: dict[str, MCPPlugin] = {
    "browser_control": BrowserControlMCP(),
    "brave_search": BraveSearchMCP(),
    "git_ops": GitOpsMCP(),
    "home_assistant": HomeAssistantMCP(),
    "local_files": LocalFilesMCP(),
    "memory_access": MemoryAccessMCP(),
    "google_services": GoogleServicesMCP(),
    "opencode": OpenCodeMCP(),
    "ssh_control": SSHControlMCP(),
    "scripts": ScriptsMCP(),
    "text_to_speech": TextToSpeechMCP(),
    "timed_jobs": TimedJobsMCP(),
    "whatsapp": WhatsAppMCP(),
    "youtube_summarizer": YouTubeSummarizerMCP(),
}


def get_mcp(mcp_id: str) -> MCPPlugin | None:
    return _MCPS.get(mcp_id)


def is_supported_mcp(mcp_id: str) -> bool:
    return mcp_id in _MCPS


def get_mcp_options() -> list[dict[str, object]]:
    options: list[dict[str, object]] = []
    for plugin in _MCPS.values():
        config_fields = [field.model_dump() for field in plugin.config_fields]
        for field_payload in config_fields:
            options_source = str(field_payload.get("options_source", "") or "").strip().lower()
            if options_source == "providers":
                field_payload["options"] = _build_provider_options()
                continue
            if options_source == "provider_models":
                field_payload["options"] = _build_provider_model_options()
                continue

        options.append(
            {
                "id": plugin.mcp_id,
                "label": plugin.display_name,
                "description": plugin.description,
                "default_enabled": bool(getattr(plugin, "default_enabled", False)),
                "config_fields": config_fields,
                "tools": [tool.model_dump() for tool in plugin.tool_specs()],
            }
        )

    return options


def get_mcp_config_fields(mcp_id: str) -> list[McpConfigField]:
    plugin = get_mcp(mcp_id)
    if plugin is None:
        return []
    return plugin.config_fields


def get_mcp_tool_specs(mcp_id: str) -> list[McpToolSpec]:
    plugin = get_mcp(mcp_id)
    if plugin is None:
        return []
    return plugin.tool_specs()


def get_all_mcps() -> dict[str, MCPPlugin]:
    return dict(_MCPS)


def _build_provider_options() -> list[dict[str, object]]:
    options: list[dict[str, object]] = []
    try:
        from app.providers.registry import get_provider_options

        providers = get_provider_options()
        for provider in providers:
            provider_id = str(provider.get("id", "") or "").strip().lower()
            if not provider_id:
                continue
            label = str(provider.get("label", "") or provider_id).strip() or provider_id
            options.append(
                {
                    "value": provider_id,
                    "label": label,
                    "disabled": False,
                }
            )
    except Exception:
        pass
    return options


def _build_provider_model_options() -> list[dict[str, object]]:
    options: list[dict[str, object]] = []
    try:
        from app.providers.registry import get_provider_options

        providers = get_provider_options()
        for provider in providers:
            provider_id = str(provider.get("id", "") or "").strip().lower()
            if not provider_id:
                continue
            provider_label = str(provider.get("label", "") or provider_id).strip() or provider_id
            models = provider.get("models", [])
            if not isinstance(models, list):
                continue
            for model in models:
                if not isinstance(model, dict):
                    continue
                model_id = str(model.get("id", "") or "").strip()
                if not model_id:
                    continue
                model_label = str(model.get("label", "") or model_id).strip() or model_id
                options.append(
                    {
                        "value": f"{provider_id}/{model_id}",
                        "label": f"{provider_label} - {model_label}",
                        "disabled": False,
                    }
                )
    except Exception:
        pass
    return options
