"""Shared MCP slash command helpers for Gateway and chat integrations."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .config import McpConfig, Settings, load_settings, save_settings
from .mcps.base import McpConfigField
from .mcps.registry import get_all_mcps


class McpCommandResult(BaseModel):
    ok: bool = True
    text: str
    settings: Settings | None = None
    command_name: str = ""
    mcp_id: str = ""
    mcp_name: str = ""
    enabled: bool | None = None


class ParsedMcpCommand(BaseModel):
    command_name: str
    argument: str = ""


class McpListEntry(BaseModel):
    index: int
    mcp_id: str
    mcp_name: str
    enabled: bool
    missing_required_params: list[str] = Field(default_factory=list)


def parse_mcp_chat_command(text: str) -> ParsedMcpCommand | None:
    raw_text = str(text or "").strip()
    if not raw_text.startswith("/"):
        return None

    body = raw_text[1:].strip()
    if not body:
        return None

    first_token, _, remainder = body.partition(" ")
    command_name = first_token.strip().lower()
    if command_name not in {"mcp_list", "mcp_enable", "mcp_disable"}:
        return None

    return ParsedMcpCommand(command_name=command_name, argument=remainder.strip())


async def execute_mcp_command(command_name: str, argument: str = "") -> McpCommandResult:
    normalized_command = str(command_name or "").strip().lower()
    normalized_argument = str(argument or "").strip()

    if normalized_command == "mcp_list":
        settings = await load_settings()
        entries = _build_mcp_entries(settings)
        lines = ["Available MCPs:"]
        for entry in entries:
            status = "enabled" if entry.enabled else "disabled"
            line = f"{entry.index}. {entry.mcp_name} ({entry.mcp_id}) - {status}"
            if entry.enabled and entry.missing_required_params:
                line = f"{line} [needs config: {', '.join(entry.missing_required_params)}]"
            lines.append(line)
        lines.append("Use /mcp_enable <id> or /mcp_disable <id>.")
        return McpCommandResult(text="\n".join(lines), settings=settings, command_name=normalized_command)

    if normalized_command not in {"mcp_enable", "mcp_disable"}:
        return McpCommandResult(ok=False, text="Unknown MCP command.", command_name=normalized_command)

    settings = await load_settings()
    entries = _build_mcp_entries(settings)
    selected_entry = _select_mcp_entry(entries, normalized_argument)
    if selected_entry is None:
        return McpCommandResult(
            ok=False,
            text="Unknown MCP id. Use /mcp_list.",
            settings=settings,
            command_name=normalized_command,
        )

    desired_enabled = normalized_command == "mcp_enable"
    existing = settings.mcp_configs.get(selected_entry.mcp_id)
    params = dict(existing.params) if isinstance(existing, McpConfig) else {}
    settings.mcp_configs[selected_entry.mcp_id] = McpConfig(enabled=desired_enabled, params=params)
    persisted = await save_settings(settings)

    updated_entries = _build_mcp_entries(persisted)
    updated_entry = next((entry for entry in updated_entries if entry.mcp_id == selected_entry.mcp_id), selected_entry)
    action_text = "enabled" if desired_enabled else "disabled"
    response_text = f"{updated_entry.mcp_name} ({updated_entry.mcp_id}) successfully {action_text}."
    if desired_enabled and updated_entry.missing_required_params:
        response_text = (
            f"{response_text} Missing config: {', '.join(updated_entry.missing_required_params)}."
        )

    return McpCommandResult(
        text=response_text,
        settings=persisted,
        command_name=normalized_command,
        mcp_id=updated_entry.mcp_id,
        mcp_name=updated_entry.mcp_name,
        enabled=updated_entry.enabled,
    )


def _build_mcp_entries(settings: Settings) -> list[McpListEntry]:
    entries: list[McpListEntry] = []
    for index, (mcp_id, plugin) in enumerate(get_all_mcps().items(), start=1):
        config = settings.mcp_configs.get(mcp_id)
        enabled = bool(config.enabled) if isinstance(config, McpConfig) else bool(getattr(plugin, "default_enabled", False))
        params = dict(config.params) if isinstance(config, McpConfig) else {}
        missing_required = _missing_required_param_labels(plugin.config_fields, params)
        entries.append(
            McpListEntry(
                index=index,
                mcp_id=mcp_id,
                mcp_name=plugin.display_name,
                enabled=enabled,
                missing_required_params=missing_required,
            )
        )
    return entries


def _select_mcp_entry(entries: list[McpListEntry], argument: str) -> McpListEntry | None:
    normalized_argument = str(argument or "").strip()
    if not normalized_argument:
        return None

    if normalized_argument.isdigit():
        target_index = int(normalized_argument)
        return next((entry for entry in entries if entry.index == target_index), None)

    lowered_argument = normalized_argument.lower()
    return next((entry for entry in entries if entry.mcp_id.lower() == lowered_argument), None)


def _missing_required_param_labels(config_fields: list[McpConfigField], params: dict[str, str]) -> list[str]:
    missing: list[str] = []
    for field in config_fields:
        if not field.required:
            continue
        value = params.get(field.id, "")
        if isinstance(value, str) and value.strip():
            continue
        missing.append(field.label.strip() or field.id)
    return missing
