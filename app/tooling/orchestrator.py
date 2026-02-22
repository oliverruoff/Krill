"""Sequential tool-orchestration loop that plans, executes tools, and finalizes output."""

import asyncio
import json
from typing import Any, Awaitable, Callable, Sequence, TypedDict, cast

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


ToolStepCallback = Callable[[SystemTraceEntry], Awaitable[None]]


async def generate_with_tools(
    provider: LLMProvider,
    settings: Settings,
    prompt: str,
    system_prompt: str,
    model: str,
    api_key: str,
    history: list[dict[str, str]],
    max_tool_recursion: int,
    tool_timeout_seconds: int,
    on_tool_step: ToolStepCallback | None = None,
) -> OrchestrationResult:
    system_trace_messages: list[SystemTraceEntry] = []
    used_tools: list[ToolUsageEntry] = []
    token_values: list[int] = []

    async def trace(system_type: str, content: str) -> None:
        entry: SystemTraceEntry = {"system_type": system_type, "content": content}
        system_trace_messages.append(entry)
        if on_tool_step is not None:
            await on_tool_step(entry)

    await trace("runtime_system_prompt", system_prompt)
    enabled_tools = _collect_enabled_tools(settings)

    if not enabled_tools:
        text, used_tokens = await provider.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            api_key=api_key,
            history=history,
        )
        if isinstance(used_tokens, int):
            token_values.append(used_tokens)
        await trace("final_prompt", prompt)
        return {
            "text": text,
            "used_tokens": _sum_tokens(*token_values),
            "used_mcp_tools": [],
            "system_trace_messages": system_trace_messages,
        }

    interaction_log: list[dict[str, object]] = []
    normalized_recursion = max(1, min(20, int(max_tool_recursion)))
    timeout_seconds = max(5, min(300, int(tool_timeout_seconds)))

    for step_index in range(1, normalized_recursion + 1):
        await trace("tool_step_status", f"Step {step_index}/{normalized_recursion}")

        planner_prompt = _build_recursive_planner_prompt(prompt, enabled_tools, interaction_log, step_index, normalized_recursion)
        planner_system = (
            f"{system_prompt}\n\n"
            "You are selecting tools for a user request. "
            "Return JSON only without markdown and without extra prose."
        )

        await trace("tool_planner_system", planner_system)
        await trace("tool_planner_prompt", planner_prompt)

        planner_response, planner_tokens = await provider.generate(
            prompt=planner_prompt,
            system_prompt=planner_system,
            model=model,
            api_key=api_key,
            history=history,
        )
        if isinstance(planner_tokens, int):
            token_values.append(planner_tokens)
        await trace("tool_planner_result", planner_response)

        plan = _parse_planner_response(planner_response)
        action = plan.get("action")

        if action == "respond":
            final_answer = plan.get("final_answer")
            if isinstance(final_answer, str) and final_answer.strip():
                return {
                    "text": final_answer.strip(),
                    "used_tokens": _sum_tokens(*token_values),
                    "used_mcp_tools": used_tools,
                    "system_trace_messages": system_trace_messages,
                }

            break

        if action != "call_tool":
            break

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
        used_tools.append(tool_usage)

        tool_call_payload = {
            "mcp_id": mcp_id,
            "tool_id": tool_id,
            "arguments": arguments,
            "step": step_index,
        }
        await trace("tool_call", json.dumps(tool_call_payload, ensure_ascii=True))

        try:
            tool_result = await asyncio.wait_for(
                plugin.call_tool(tool_id, arguments, config.params),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                f"MCP hard error: {plugin.display_name} ({tool_id}) exceeded timeout of {timeout_seconds}s."
            ) from exc
        except Exception as exc:
            raise RuntimeError(f"MCP hard error: {plugin.display_name} ({tool_id}) failed: {exc}") from exc

        await trace("tool_result", json.dumps(tool_result, ensure_ascii=True))
        interaction_log.append({
            "step": step_index,
            "tool_call": tool_call_payload,
            "tool_result": tool_result,
        })

    final_prompt = _build_final_prompt_with_interactions(prompt, interaction_log)
    await trace("final_prompt", final_prompt)
    final_response, final_tokens = await provider.generate(
        prompt=final_prompt,
        system_prompt=system_prompt,
        model=model,
        api_key=api_key,
        history=history,
    )
    if isinstance(final_tokens, int):
        token_values.append(final_tokens)

    return {
        "text": final_response,
        "used_tokens": _sum_tokens(*token_values),
        "used_mcp_tools": used_tools,
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
        if not field.required:
            continue

        value = config.params.get(field.id, "")
        if not isinstance(value, str) or not value.strip():
            return True

    return False


def _build_recursive_planner_prompt(
    user_message: str,
    tools: list[dict[str, object]],
    interaction_log: list[dict[str, object]],
    step_index: int,
    max_steps: int,
) -> str:
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
        "You can recursively call tools.\n"
        f"Current step: {step_index} of {max_steps}.\n"
        "Return JSON only.\n"
        "If you need another tool call, return: "
        '{"action":"call_tool","mcp_id":"...","tool_id":"...","arguments":{...}}\n'
        "If you can answer now, return: "
        '{"action":"respond","final_answer":"..."}\n'
        f"User message: {user_message}\n"
        f"Available tools: {json.dumps(tool_payload)}\n"
        f"Completed tool interactions so far: {json.dumps(interaction_log, ensure_ascii=True)}"
    )


def _build_final_prompt_with_interactions(user_message: str, interaction_log: list[dict[str, object]]) -> str:
    return (
        "Use the tool results below to answer the user accurately. "
        "If URLs are present, include relevant links (as hyperlinks) in your answer. Use markdown for formatting properly!\n\n"
        f"User message:\n{user_message}\n\n"
        f"Tool interactions:\n{json.dumps(interaction_log, ensure_ascii=True)}"
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
        return {"action": "respond", "final_answer": ""}

    candidate = response_text[start : end + 1]
    try:
        payload = json.loads(candidate)
        if isinstance(payload, dict):
            return payload
    except Exception:
        return {"action": "respond", "final_answer": ""}

    return {"action": "respond", "final_answer": ""}
