"""Sequential tool-orchestration loop that plans, executes tools, and finalizes output."""

import asyncio
import json
from datetime import datetime
from typing import Any, Awaitable, Callable, Sequence, TypedDict, cast

from app.config import McpConfig, Settings
from app.mcps.base import MCPPlugin, McpConfigField
from app.mcps.registry import get_all_mcps
from app.providers.base import LLMProvider
from app.providers.resilience import generate_with_retries


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

    async def provider_generate(
        *,
        prompt_text: str,
        system_prompt_text: str,
        phase_label: str,
    ) -> tuple[str, int | None]:
        async def on_retry(attempt: int, max_attempts: int, delay_seconds: float, reason: str) -> None:
            await trace(
                "provider_retry",
                (
                    f"{phase_label}: retry {attempt + 1}/{max_attempts} in {delay_seconds:.1f}s"
                    f" after provider error: {reason or 'unknown error'}"
                ),
            )

        return await generate_with_retries(
            provider=provider,
            prompt=prompt_text,
            system_prompt=system_prompt_text,
            model=model,
            api_key=api_key,
            history=history,
            on_retry=on_retry,
        )

    if not enabled_tools:
        text, used_tokens = await provider_generate(
            prompt_text=prompt,
            system_prompt_text=system_prompt,
            phase_label="direct_response",
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
    current_local_time = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M")
    planner_context = system_prompt.strip()
    if len(planner_context) > 4000:
        planner_context = planner_context[:4000] + "\n...[truncated runtime context]"
    planner_system = (
        "You are selecting tools for a user request. Return JSON only without markdown and without extra prose.\n"
        "Use the runtime context below (identity/preferences/memory) when selecting tools and arguments.\n"
        f"Runtime context:\n{planner_context}"
    )
    await trace("tool_planner_system", planner_system)

    for step_index in range(1, normalized_recursion + 1):
        await trace("tool_step_status", f"Step {step_index}/{normalized_recursion}")

        planner_prompt = _build_recursive_planner_prompt(
            prompt,
            enabled_tools,
            interaction_log,
            step_index,
            normalized_recursion,
            current_local_time,
        )
        await trace("tool_planner_prompt", planner_prompt)

        planner_response, planner_tokens = await provider_generate(
            prompt_text=planner_prompt,
            system_prompt_text=planner_system,
            phase_label=f"planner_step_{step_index}",
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

        if not isinstance(tool_id, str) or not tool_id.strip():
            invalid_payload = {
                "step": step_index,
                "error": "planner_invalid_call_payload",
                "detail": "Missing or invalid tool_id in planner response.",
                "planner_payload": plan,
            }
            await trace("tool_error", json.dumps(invalid_payload, ensure_ascii=True))
            interaction_log.append(
                {
                    "step": step_index,
                    "tool_error": {
                        "type": "planner_invalid_call_payload",
                        "message": "Missing or invalid tool_id in planner response.",
                    },
                }
            )
            continue

        resolved_tool_id = tool_id.strip()
        resolved_mcp_id = mcp_id.strip() if isinstance(mcp_id, str) else ""
        tool_arguments = cast(dict[str, object], arguments) if isinstance(arguments, dict) else {}

        if not resolved_mcp_id:
            candidate_mcps = sorted(
                {
                    str(entry["mcp_id"])
                    for entry in enabled_tools
                    if str(entry.get("tool_id", "")) == resolved_tool_id
                }
            )
            if len(candidate_mcps) == 1:
                resolved_mcp_id = candidate_mcps[0]
            else:
                invalid_payload = {
                    "step": step_index,
                    "error": "planner_invalid_call_payload",
                    "detail": "Missing or ambiguous mcp_id in planner response.",
                    "tool_id": resolved_tool_id,
                    "candidate_mcps": candidate_mcps,
                    "planner_payload": plan,
                }
                await trace("tool_error", json.dumps(invalid_payload, ensure_ascii=True))
                interaction_log.append(
                    {
                        "step": step_index,
                        "tool_error": {
                            "type": "planner_invalid_call_payload",
                            "message": "Missing or ambiguous mcp_id in planner response.",
                            "tool_id": resolved_tool_id,
                            "candidate_mcps": candidate_mcps,
                        },
                    }
                )
                continue

        mcp_id = resolved_mcp_id
        tool_id = resolved_tool_id

        tool_entry = next((entry for entry in enabled_tools if entry["mcp_id"] == mcp_id and entry["tool_id"] == tool_id), None)
        if tool_entry is None:
            available_for_mcp = sorted(
                {
                    str(entry["tool_id"])
                    for entry in enabled_tools
                    if str(entry.get("mcp_id", "")) == mcp_id
                }
            )
            unavailable_payload = {
                "mcp_id": mcp_id,
                "tool_id": tool_id,
                "arguments": tool_arguments,
                "step": step_index,
                "error": "planner_selected_unavailable_tool",
                "available_tool_ids_for_mcp": available_for_mcp,
            }
            await trace("tool_error", json.dumps(unavailable_payload, ensure_ascii=True))
            interaction_log.append(
                {
                    "step": step_index,
                    "tool_call": {
                        "mcp_id": mcp_id,
                        "tool_id": tool_id,
                        "arguments": tool_arguments,
                        "step": step_index,
                    },
                    "tool_error": {
                        "type": "planner_selected_unavailable_tool",
                        "message": "Planner selected a tool that is not currently available.",
                        "available_tool_ids_for_mcp": available_for_mcp,
                    },
                }
            )
            continue

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
            "arguments": tool_arguments,
            "step": step_index,
        }

        reminder_text = _get_mcp_tool_call_reminder(plugin, tool_id, config.params)
        if reminder_text:
            await trace("mcp_tool_call_reminder", reminder_text)
            tool_arguments, reminder_tokens = await _apply_tool_call_reminder(
                provider=provider,
                model=model,
                api_key=api_key,
                history=history,
                user_message=prompt,
                tool_call_payload=tool_call_payload,
                tool_input_schema=cast(dict[str, object], tool_entry.get("input_schema", {})),
                reminder_text=reminder_text,
                current_local_time=current_local_time,
            )
            if isinstance(reminder_tokens, int):
                token_values.append(reminder_tokens)
            tool_call_payload["arguments"] = tool_arguments

        missing_required_arguments = _missing_required_arguments(
            cast(dict[str, object], tool_entry.get("input_schema", {})),
            tool_arguments,
        )
        if missing_required_arguments:
            missing_payload = {
                "mcp_id": mcp_id,
                "tool_id": tool_id,
                "arguments": tool_arguments,
                "step": step_index,
                "error": "missing_required_arguments",
                "missing_required_arguments": missing_required_arguments,
            }
            await trace("tool_error", json.dumps(missing_payload, ensure_ascii=True))
            interaction_log.append(
                {
                    "step": step_index,
                    "tool_call": tool_call_payload,
                    "tool_error": {
                        "type": "missing_required_arguments",
                        "message": f"Missing required arguments: {', '.join(missing_required_arguments)}",
                        "missing_required_arguments": missing_required_arguments,
                    },
                }
            )
            continue

        await trace("tool_call", json.dumps(tool_call_payload, ensure_ascii=True))

        try:
            tool_result = await asyncio.wait_for(
                plugin.call_tool(tool_id, tool_arguments, config.params),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                f"MCP hard error: {plugin.display_name} ({tool_id}) exceeded timeout of {timeout_seconds}s."
            ) from exc
        except Exception as exc:
            tool_error_payload = {
                "mcp_id": mcp_id,
                "tool_id": tool_id,
                "arguments": tool_arguments,
                "step": step_index,
                "error": "tool_execution_failed",
                "detail": str(exc),
            }
            await trace("tool_error", json.dumps(tool_error_payload, ensure_ascii=True))
            interaction_log.append(
                {
                    "step": step_index,
                    "tool_call": tool_call_payload,
                    "tool_error": {
                        "type": "tool_execution_failed",
                        "message": str(exc),
                    },
                }
            )
            continue

        await trace("tool_result", json.dumps(tool_result, ensure_ascii=True))
        interaction_log.append({
            "step": step_index,
            "tool_call": tool_call_payload,
            "tool_result": tool_result,
        })

    final_prompt = _build_final_prompt_with_interactions(prompt, interaction_log)
    await trace("final_prompt", final_prompt)
    final_response, final_tokens = await provider_generate(
        prompt_text=final_prompt,
        system_prompt_text=system_prompt,
        phase_label="final_response",
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
    all_mcps = get_all_mcps()

    for mcp_id, plugin in all_mcps.items():
        raw_config = settings.mcp_configs.get(mcp_id)
        if raw_config is None:
            config = McpConfig(enabled=bool(getattr(plugin, "default_enabled", False)), params={})
        else:
            config = raw_config

        if not config.enabled:
            continue

        if _missing_required_params(plugin.config_fields, config):
            continue

        tool_specs = plugin.tool_specs()
        if hasattr(plugin, "tool_specs_for_config"):
            try:
                maybe_specs = getattr(plugin, "tool_specs_for_config")(config.params)
                if isinstance(maybe_specs, list):
                    tool_specs = maybe_specs
            except Exception:
                tool_specs = plugin.tool_specs()

        for tool in tool_specs:
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
    current_local_time: str,
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
        f"Current datetime (server local): {current_local_time}\n"
        "When user asks relative dates (today/tomorrow/day after tomorrow), convert using this datetime and keep the correct year.\n"
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


def _get_mcp_tool_call_reminder(plugin: MCPPlugin, tool_id: str, params: dict[str, str]) -> str:
    reminder_factory = getattr(plugin, "tool_call_system_reminder", None)
    if not callable(reminder_factory):
        return ""
    try:
        reminder = reminder_factory(tool_id, params)
    except Exception:
        return ""
    if isinstance(reminder, str):
        return reminder.strip()
    return ""


async def _apply_tool_call_reminder(
    *,
    provider: LLMProvider,
    model: str,
    api_key: str,
    history: list[dict[str, str]],
    user_message: str,
    tool_call_payload: dict[str, object],
    tool_input_schema: dict[str, object],
    reminder_text: str,
    current_local_time: str,
) -> tuple[dict[str, object], int | None]:
    prompt = (
        "You selected an MCP tool call.\n"
        "Keep the same intent. Return JSON only in this shape: "
        '{"arguments":{...}}\n'
        f"Current datetime (server local): {current_local_time}\n"
        "If arguments contain relative dates, resolve them against this datetime and keep correct year/timezone.\n"
        "Do not change tool identity. Keep arguments valid for the selected tool schema.\n"
        "User message:\n"
        f"{user_message}\n"
        "Selected tool call:\n"
        f"{json.dumps(tool_call_payload, ensure_ascii=True)}\n"
        "Selected tool input schema:\n"
        f"{json.dumps(tool_input_schema, ensure_ascii=True)}"
    )

    response_text, used_tokens = await generate_with_retries(
        provider=provider,
        prompt=prompt,
        system_prompt=reminder_text,
        model=model,
        api_key=api_key,
        history=history,
    )

    parsed = _parse_planner_response(response_text)
    maybe_args = parsed.get("arguments")
    if isinstance(maybe_args, dict):
        return cast(dict[str, object], maybe_args), used_tokens if isinstance(used_tokens, int) else None

    try:
        payload = json.loads(response_text)
        if isinstance(payload, dict):
            raw_args = payload.get("arguments")
            if isinstance(raw_args, dict):
                return cast(dict[str, object], raw_args), used_tokens if isinstance(used_tokens, int) else None
    except Exception:
        pass

    existing_args = tool_call_payload.get("arguments")
    if isinstance(existing_args, dict):
        return cast(dict[str, object], existing_args), used_tokens if isinstance(used_tokens, int) else None

    return {}, used_tokens if isinstance(used_tokens, int) else None


def _missing_required_arguments(input_schema: dict[str, object], arguments: dict[str, object]) -> list[str]:
    required_raw = input_schema.get("required") if isinstance(input_schema, dict) else None
    if not isinstance(required_raw, list):
        return []

    missing: list[str] = []
    for item in required_raw:
        if not isinstance(item, str):
            continue
        if item not in arguments:
            missing.append(item)
            continue

        value = arguments.get(item)
        if value is None:
            missing.append(item)
            continue

        if isinstance(value, str) and not value.strip():
            missing.append(item)

    return missing
