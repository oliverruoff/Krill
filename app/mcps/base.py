"""Base MCP plugin types for config fields, tool specs, and plugin protocol."""

from typing import Literal, Protocol

from pydantic import BaseModel, Field


class McpConfigFieldOption(BaseModel):
    value: str
    label: str
    disabled: bool = False


class McpConfigField(BaseModel):
    id: str
    label: str
    type: Literal["text", "password", "select", "multiselect", "textarea"] = "text"
    required: bool = False
    placeholder: str = ""
    description: str = ""
    options: list[McpConfigFieldOption] = Field(default_factory=list)
    options_source: str = ""


class McpToolSpec(BaseModel):
    id: str
    label: str
    description: str
    input_schema: dict[str, object] = Field(default_factory=dict)


class McpToolCall(BaseModel):
    mcp_id: str
    tool_id: str
    arguments: dict[str, object] = Field(default_factory=dict)


class MCPPlugin(Protocol):
    mcp_id: str
    display_name: str
    description: str
    config_fields: list[McpConfigField]

    def tool_specs(self) -> list[McpToolSpec]:
        ...

    async def verify(self, params: dict[str, str]) -> tuple[bool, str]:
        ...

    async def call_tool(self, tool_id: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
        ...

    def tool_call_system_reminder(self, tool_id: str, params: dict[str, str]) -> str:
        ...
