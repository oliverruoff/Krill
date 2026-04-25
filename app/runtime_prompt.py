"""Helpers for building the runtime system prompt injected into model calls."""

from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.config import McpConfig, Settings

if TYPE_CHECKING:
    from app.mcps.base import McpConfigField


def compose_runtime_system_prompt(
    settings: Settings,
    memory_block: str = "",
    source_channel: str = "",
    source_user_role: str = "",
    allowed_mcp_ids: list[str] | None = None,
) -> str:
    current_local_time = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M")
    invisible_context = (
        f"Current datetime (server local): {current_local_time}\n"
        "Use time context only when relevant; do not mention it unless needed."
    )

    if source_channel == "timed_job":
        invisible_context = (
            f"{invisible_context}\n\n"
            "You are currently executing a scheduled timed job.\n"
            "The user message below contains the job's instructions — execute them directly.\n"
            "Do NOT create, update, or schedule any new timed jobs unless the instructions "
            "explicitly ask you to manage other timed jobs."
        )

    capability_summary = _build_enabled_capability_summary(
        settings,
        source_user_role=source_user_role,
        allowed_mcp_ids=allowed_mcp_ids,
    )
    if capability_summary:
        invisible_context = (
            f"{invisible_context}\n\n"
            "Enabled tools and capabilities are available in this runtime. "
            "Use them whenever they are relevant instead of claiming no access.\n"
            f"{capability_summary}"
        )

    if memory_block.strip():
        invisible_context = f"{invisible_context}\n\nCompacted conversation memory:\n{memory_block.strip()}"

    return invisible_context


def _build_enabled_capability_summary(
    settings: Settings,
    *,
    source_user_role: str = "",
    allowed_mcp_ids: list[str] | None = None,
) -> str:
    from app.mcps.registry import get_all_mcps

    entries: list[str] = []
    role = str(source_user_role or "").strip().lower()
    allowed_ids = {
        str(item).strip()
        for item in (allowed_mcp_ids or [])
        if str(item).strip()
    }

    for mcp_id, plugin in get_all_mcps().items():
        if role == "assistant_usage" and mcp_id not in allowed_ids:
            continue

        raw_config = settings.mcp_configs.get(mcp_id)
        if role == "assistant_usage" and raw_config is None:
            continue

        if raw_config is None:
            config = McpConfig(enabled=bool(getattr(plugin, "default_enabled", False)), params={})
        else:
            config = raw_config

        if not config.enabled or _missing_required_params(plugin.config_fields, config):
            continue

        tool_specs = plugin.tool_specs()
        if hasattr(plugin, "tool_specs_for_config"):
            try:
                maybe_specs = getattr(plugin, "tool_specs_for_config")(config.params)
                if isinstance(maybe_specs, list):
                    tool_specs = maybe_specs
            except Exception:
                tool_specs = plugin.tool_specs()

        tool_labels = [tool.label.strip() for tool in tool_specs if tool.label.strip()]
        if not tool_labels:
            continue

        preview = ", ".join(tool_labels[:4])
        if len(tool_labels) > 4:
            preview = f"{preview}, +{len(tool_labels) - 4} more"
        entries.append(f"- {plugin.display_name} (`{mcp_id}`): {preview}")

    return "\n".join(entries)


def _missing_required_params(config_fields: list[Any], config: McpConfig) -> bool:
    for field in config_fields:
        if not field.required:
            continue

        value = config.params.get(field.id, "")
        if not isinstance(value, str) or not value.strip():
            return True

    return False
