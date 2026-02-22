import json
from typing import Any, Sequence, TypedDict, cast

from app.config import McpConfig, Settings
from app.mcps.base import MCPPlugin, McpConfigField
from app.mcps.registry import get_mcp
from app.providers.base import LLMProvider


class ToolUsageEntry(TypedDict):
    mcp_id: str
    mcp_label: str
    tool_id: str
    tool_label: str


class SystemTraceEntry(TypedDict):
    system_type: str
    content: str


class OrchestrationResult(TypedDict):
    text: str
    used_tokens: int | None
    used_mcp_tools: list[ToolUsageEntry]
    system_trace_messages: list[SystemTraceEntry]


async def generate_with_tools(
    provider: LLMProvider,
    settings: Settings,
    prompt: str,
    system_prompt: str,
    model: str,
    api_key: str,
    history: list[dict[str, str]],
) -> OrchestrationResult:
    system_trace_messages: list[SystemTraceEntry] = [
        {
            "system_type": "runtime_system_prompt",
            "content": system_prompt,
        }
    ]
    enabled_tools = _collect_enabled_tools(settings)

    if not enabled_tools:
        text, used_tokens = await provider.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            api_key=api_key,
            history=history,
        )
        system_trace_messages.append({"system_type": "final_prompt", "content": prompt})
        return {
            "text": text,
            "used_tokens": used_tokens,
            "used_mcp_tools": [],
            "system_trace_messages": system_trace_messages,
        }

    planner_prompt = _build_planner_prompt(prompt, enabled_tools)
    planner_system = (
        f"{system_prompt}\n\n"
        "You are selecting tools for a user request. "
        "Return JSON only without markdown and without extra prose."
    )
    system_trace_messages.append({"system_type": "tool_planner_system", "content": planner_system})
    system_trace_messages.append({"system_type": "tool_planner_prompt", "content": planner_prompt})

    planner_response, planner_tokens = await provider.generate(
        prompt=planner_prompt,
        system_prompt=planner_system,
        model=model,
        api_key=api_key,
        history=history,
    )
    system_trace_messages.append({"system_type": "tool_planner_result", "content": planner_response})

    plan = _parse_planner_response(planner_response)
    if plan.get("action") != "call_tool":
        text, final_tokens = await provider.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            api_key=api_key,
            history=history,
        )
        system_trace_messages.append({"system_type": "final_prompt", "content": prompt})
        return {
            "text": text,
            "used_tokens": _sum_tokens(planner_tokens, final_tokens),
            "used_mcp_tools": [],
            "system_trace_messages": system_trace_messages,
        }

    mcp_id = plan.get("mcp_id")
    tool_id = plan.get("tool_id")
    arguments = plan.get("arguments")

    if not isinstance(mcp_id, str) or not isinstance(tool_id, str) or not isinstance(arguments, dict):
        raise RuntimeError("MCP hard error: Tool planner returned invalid call payload.")

    tool_entry = next((entry for entry in enabled_tools if entry["mcp_id"] == mcp_id and entry["tool_id"] == tool_id), None)
    if tool_entry is None:
        raise RuntimeError("MCP hard error: Planner selected unavailable tool.")

    plugin = cast(MCPPlugin, tool_entry["plugin"])
    config = cast(McpConfig, tool_entry["config"])
    tool_usage: ToolUsageEntry = {
        "mcp_id": mcp_id,
        "mcp_label": str(tool_entry["mcp_label"]),
        "tool_id": tool_id,
        "tool_label": str(tool_entry["tool_label"]),
    }
    system_trace_messages.append(
        {
            "system_type": "tool_call",
            "content": json.dumps(
                {
                    "mcp_id": mcp_id,
                    "tool_id": tool_id,
                    "arguments": arguments,
                },
                ensure_ascii=True,
            ),
        }
    )

    try:
        tool_result = await plugin.call_tool(tool_id, arguments, config.params)
    except Exception as exc:
        raise RuntimeError(f"MCP hard error: {plugin.display_name} ({tool_id}) failed: {exc}") from exc

    system_trace_messages.append(
        {
            "system_type": "tool_result",
            "content": json.dumps(tool_result, ensure_ascii=True),
        }
    )

    final_prompt = _build_prompt_with_tool_result(prompt, mcp_id, tool_id, arguments, tool_result)
    system_trace_messages.append({"system_type": "final_prompt", "content": final_prompt})
    final_response, final_tokens = await provider.generate(
        prompt=final_prompt,
        system_prompt=system_prompt,
        model=model,
        api_key=api_key,
        history=history,
    )

    return {
        "text": final_response,
        "used_tokens": _sum_tokens(planner_tokens, final_tokens),
        "used_mcp_tools": [tool_usage],
        "system_trace_messages": system_trace_messages,
    }


def _sum_tokens(*token_values: int | None) -> int | None:
    values = [value for value in token_values if isinstance(value, int)]
    if not values:
        return None
    return sum(values)


def _collect_enabled_tools(settings: Settings) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    for mcp_id, config in settings.mcp_configs.items():
        if not config.enabled:
            continue

        plugin = get_mcp(mcp_id)
        if plugin is None:
            continue

        if _missing_required_params(plugin.config_fields, config):
            continue

        for tool in plugin.tool_specs():
            entries.append(
                {
                    "mcp_id": mcp_id,
                    "mcp_label": plugin.display_name,
                    "tool_id": tool.id,
                    "tool_label": tool.label,
                    "tool_description": tool.description,
                    "input_schema": tool.input_schema,
                    "plugin": plugin,
                    "config": config,
                }
            )

    return entries


def _missing_required_params(config_fields: Sequence[McpConfigField], config: McpConfig) -> bool:
    for field in config_fields:
        required = getattr(field, "required", False)
        field_id = getattr(field, "id", "")
        if not required or not isinstance(field_id, str):
            continue

        value = config.params.get(field_id, "")
        if not isinstance(value, str) or not value.strip():
            return True

    return False


def _build_planner_prompt(user_message: str, tools: list[dict[str, object]]) -> str:
    tool_payload = [
        {
            "mcp_id": entry["mcp_id"],
            "mcp_label": entry["mcp_label"],
            "tool_id": entry["tool_id"],
            "tool_label": entry["tool_label"],
            "description": entry["tool_description"],
            "input_schema": entry["input_schema"],
        }
        for entry in tools
    ]

    return (
        "Decide whether tool usage is required for the user request.\n"
        "If no tool is needed, return exactly: {\"action\":\"no_tool\"}.\n"
        "If a tool is needed, return JSON with this exact shape: "
        "{\"action\":\"call_tool\",\"mcp_id\":\"...\",\"tool_id\":\"...\",\"arguments\":{...}}.\n"
        "Choose exactly one tool call or no_tool.\n"
        f"Available tools: {json.dumps(tool_payload)}\n"
        f"User message: {user_message}"
    )


def _parse_planner_response(response_text: str) -> dict[str, object]:
    try:
        payload = json.loads(response_text)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass

    start = response_text.find("{")
    end = response_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {"action": "no_tool"}

    candidate = response_text[start : end + 1]
    try:
        payload = json.loads(candidate)
        if isinstance(payload, dict):
            return payload
    except Exception:
        return {"action": "no_tool"}

    return {"action": "no_tool"}


def _build_prompt_with_tool_result(
    user_message: str,
    mcp_id: str,
    tool_id: str,
    arguments: dict[str, object],
    result: dict[str, object],
) -> str:
    return (
        "Use the tool result below to answer the user accurately. "
        "If URLs are present, include relevant links (as hyperlinks) in your answer. Use markdown for formatting properly!\n\n"
        f"User message:\n{user_message}\n\n"
        f"Tool call:\n{json.dumps({'mcp_id': mcp_id, 'tool_id': tool_id, 'arguments': arguments}, ensure_ascii=True)}\n\n"
        f"Tool result:\n{json.dumps(result, ensure_ascii=True)}"
    )
