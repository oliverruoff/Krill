"""Registry of MCP plugins that can be enabled and called by orchestration."""

from .base import MCPPlugin, McpConfigField, McpToolSpec
from .brave_search import BraveSearchMCP
from .git_ops import GitOpsMCP
from .local_files import LocalFilesMCP


_MCPS: dict[str, MCPPlugin] = {
    "brave_search": BraveSearchMCP(),
    "git_ops": GitOpsMCP(),
    "local_files": LocalFilesMCP(),
}


def get_mcp(mcp_id: str) -> MCPPlugin | None:
    return _MCPS.get(mcp_id)


def is_supported_mcp(mcp_id: str) -> bool:
    return mcp_id in _MCPS


def get_mcp_options() -> list[dict[str, object]]:
    options: list[dict[str, object]] = []
    for plugin in _MCPS.values():
        options.append(
            {
                "id": plugin.mcp_id,
                "label": plugin.display_name,
                "description": plugin.description,
                "config_fields": [field.model_dump() for field in plugin.config_fields],
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
