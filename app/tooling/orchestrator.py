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


_MAX_PLANNER_INTERACTIONS = 8
_MAX_FINAL_INTERACTIONS = 12
_MAX_TOOL_RESULT_CHARS = 4000
_MAX_RECURSIVE_VALUE_DEPTH = 5
_MAX_RECURSIVE_LIST_ITEMS = 20
_MAX_RECURSIVE_DICT_ITEMS = 40
_MAX_RETRIES_PER_TOOL_SIGNATURE = 2


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
    successful_tool_call_signatures: set[str] = set()
    tool_call_attempts_by_signature: dict[str, int] = {}
    normalized_recursion = max(1, min(20, int(max_tool_recursion)))
    timeout_seconds = max(5, min(300, int(tool_timeout_seconds)))
    current_local_time = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M")
    planner_context = system_prompt.strip()
    if len(planner_context) > 4000:
        planner_context = planner_context[:4000] + "\n...[truncated runtime context]"
    planner_system = (
        "You are in the technical TOOL SELECTION phase. Your ONLY goal is to choose the correct tools and arguments.\n"
        "You must suppress your conversational persona (buddy, bro, etc.) and avoid all prose during this phase.\n\n"
        f"Runtime context (identity/memory/preferences):\n{planner_context}\n\n"
        "Return JSON only. No markdown. No conversational output. No prose."
    )

    await trace("tool_planner_system", planner_system)

    for step_index in range(1, normalized_recursion + 1):
        await trace("tool_step_status", f"Step {step_index}/{normalized_recursion}")

        planner_prompt = _build_recursive_planner_prompt(
            prompt,
            enabled_tools,
            _planner_interaction_context(interaction_log),
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
                normalized_answer = final_answer.strip()
                goal_status = _normalize_goal_status(plan.get("goal_status"))

                if goal_status != "complete" and step_index < normalized_recursion:
                    incomplete_payload = {
                        "step": step_index,
                        "error": "planner_marked_incomplete",
                        "detail": "Planner responded before objective completion; continuing tool loop.",
                        "goal_status": goal_status,
                        "final_answer": normalized_answer,
                    }
                    await trace("tool_error", json.dumps(incomplete_payload, ensure_ascii=True))
                    interaction_log.append(
                        {
                            "step": step_index,
                            "planner_feedback": {
                                "type": "planner_marked_incomplete",
                                "message": "Continue using tools until the task is complete or blocked.",
                                "goal_status": goal_status,
                            },
                        }
                    )
                    continue

                if not used_tools and _looks_like_tool_avoidance_response(normalized_answer):
                    skip_payload = {
                        "step": step_index,
                        "error": "planner_skipped_tools",
                        "detail": "Planner answered without tools despite enabled tools and likely external-data request.",
                        "final_answer": normalized_answer,
                    }
                    await trace("tool_error", json.dumps(skip_payload, ensure_ascii=True))
                    interaction_log.append(
                        {
                            "step": step_index,
                            "tool_error": {
                                "type": "planner_skipped_tools",
                                "message": "Use available tools instead of claiming unavailable access.",
                            },
                        }
                    )
                    continue

                return {
                    "text": normalized_answer,
                    "used_tokens": _sum_tokens(*token_values),
                    "used_mcp_tools": used_tools,
                    "system_trace_messages": system_trace_messages,
                }

            break

        if action == "blocked":
            blocking_reason = str(plan.get("blocking_reason", "")).strip()
            required_user_input = str(plan.get("required_user_input", "")).strip()
            blocked_payload = {
                "step": step_index,
                "blocking_reason": blocking_reason,
                "required_user_input": required_user_input,
            }
            await trace("tool_blocked", json.dumps(blocked_payload, ensure_ascii=True))
            blocked_message_parts: list[str] = []
            if blocking_reason:
                blocked_message_parts.append(blocking_reason)
            if required_user_input:
                blocked_message_parts.append(f"Needed from user: {required_user_input}")
            blocked_message = "\n\n".join(blocked_message_parts).strip() or (
                "I am blocked by a required external step and need user input to continue."
            )
            return {
                "text": blocked_message,
                "used_tokens": _sum_tokens(*token_values),
                "used_mcp_tools": used_tools,
                "system_trace_messages": system_trace_messages,
            }

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
            redacted_arguments = _redact_sensitive_payload(tool_arguments)
            unavailable_payload = {
                "mcp_id": mcp_id,
                "tool_id": tool_id,
                "arguments": redacted_arguments,
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
                        "arguments": redacted_arguments,
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

        tool_call_payload = {
            "mcp_id": mcp_id,
            "tool_id": tool_id,
            "arguments": _redact_sensitive_payload(tool_arguments),
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
            tool_call_payload["arguments"] = _redact_sensitive_payload(tool_arguments)

        tool_arguments = _align_tool_timeout_argument(
            arguments=tool_arguments,
            input_schema=cast(dict[str, object], tool_entry.get("input_schema", {})),
            timeout_seconds=timeout_seconds,
        )
        tool_call_payload["arguments"] = _redact_sensitive_payload(tool_arguments)

        missing_required_arguments = _missing_required_arguments(
            cast(dict[str, object], tool_entry.get("input_schema", {})),
            tool_arguments,
        )
        if missing_required_arguments:
            missing_payload = {
                "mcp_id": mcp_id,
                "tool_id": tool_id,
                "arguments": _redact_sensitive_payload(tool_arguments),
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

        tool_call_signature = _build_tool_call_signature(mcp_id, tool_id, tool_arguments)
        signature_attempts = tool_call_attempts_by_signature.get(tool_call_signature, 0)
        if tool_call_signature in successful_tool_call_signatures or signature_attempts >= _MAX_RETRIES_PER_TOOL_SIGNATURE:
            duplicate_payload = {
                "mcp_id": mcp_id,
                "tool_id": tool_id,
                "arguments": _redact_sensitive_payload(tool_arguments),
                "step": step_index,
                "error": "duplicate_tool_call_blocked",
                "detail": (
                    "Blocked duplicate MCP tool call with identical arguments in this orchestration run."
                    if tool_call_signature in successful_tool_call_signatures
                    else f"Blocked after {signature_attempts} failed attempt(s) with identical arguments."
                ),
            }
            await trace("tool_error", json.dumps(duplicate_payload, ensure_ascii=True))
            interaction_log.append(
                {
                    "step": step_index,
                    "tool_call": tool_call_payload,
                    "tool_error": {
                        "type": "duplicate_tool_call_blocked",
                        "message": "Duplicate MCP tool call with identical arguments was blocked in this run.",
                    },
                }
            )
            continue

        tool_call_attempts_by_signature[tool_call_signature] = signature_attempts + 1

        await trace("tool_call", json.dumps(tool_call_payload, ensure_ascii=True))

        try:
            tool_result = await asyncio.wait_for(
                plugin.call_tool(tool_id, tool_arguments, config.params),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            tool_error_payload = {
                "mcp_id": mcp_id,
                "tool_id": tool_id,
                "arguments": _redact_sensitive_payload(tool_arguments),
                "step": step_index,
                "error": "tool_execution_timeout",
                "detail": f"{plugin.display_name} ({tool_id}) exceeded timeout of {timeout_seconds}s.",
            }
            await trace("tool_error", json.dumps(tool_error_payload, ensure_ascii=True))
            interaction_log.append(
                {
                    "step": step_index,
                    "tool_call": tool_call_payload,
                    "tool_error": {
                        "type": "tool_execution_timeout",
                        "message": f"{plugin.display_name} ({tool_id}) exceeded timeout of {timeout_seconds}s.",
                    },
                }
            )
            continue
        except Exception as exc:
            tool_error_payload = {
                "mcp_id": mcp_id,
                "tool_id": tool_id,
                "arguments": _redact_sensitive_payload(tool_arguments),
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

        successful_tool_call_signatures.add(tool_call_signature)
        used_tools.append(tool_usage)

        redacted_tool_result = _redact_sensitive_payload(tool_result)
        compact_tool_result = _compact_payload_for_prompt(redacted_tool_result)
        await trace("tool_result", json.dumps(compact_tool_result, ensure_ascii=True))
        interaction_log.append({
            "step": step_index,
            "tool_call": tool_call_payload,
            "tool_result": compact_tool_result,
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
    interaction_context: dict[str, object],
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
        "Your goal is to complete the user's original request end-to-end, not to stop at intermediate status updates.\n"
        "If user asks for live/external/private data (web, files, integrations, devices, Home Assistant, calendars, email), use a tool call first.\n"
        "Do not claim you cannot access browsing/tools/devices when relevant tools are listed.\n"
        "Only ask the user for help if truly blocked by missing user-only input, explicit approval, or an external challenge that tools cannot resolve.\n"
        "If information can be fetched via enabled tools, fetch it yourself and continue.\n"
        "If you need another tool call, return: "
        '{"action":"call_tool","mcp_id":"...","tool_id":"...","arguments":{...}}\n'
        "Do not repeat the same mcp_id + tool_id + identical arguments in this request.\n"
        "If the objective is complete, return: "
        '{"action":"respond","goal_status":"complete","final_answer":"..."}\n'
        "If the objective is not complete yet, return another tool call instead of a status-only response.\n"
        "If hard-blocked, return: "
        '{"action":"blocked","blocking_reason":"...","required_user_input":"..."}\n'
        f"Current datetime (server local): {current_local_time}\n"
        "When user asks relative dates (today/tomorrow/day after tomorrow), convert using this datetime and keep the correct year.\n"
        f"User message: {user_message}\n"
        f"Available tools: {json.dumps(tool_payload)}\n"
        f"Completed tool interactions so far: {json.dumps(interaction_context, ensure_ascii=True)}"
    )


def _build_final_prompt_with_interactions(user_message: str, interaction_log: list[dict[str, object]]) -> str:
    summary = _interaction_summary(interaction_log)
    recent_interactions = interaction_log[-_MAX_FINAL_INTERACTIONS:]
    return (
        "Use the tool results below to answer the user accurately. "
        "If URLs are present, include relevant links (as hyperlinks) in your answer. Use markdown for formatting properly!\n\n"
        f"User message:\n{user_message}\n\n"
        f"Tool interaction summary:\n{json.dumps(summary, ensure_ascii=True)}\n\n"
        f"Recent tool interactions:\n{json.dumps(recent_interactions, ensure_ascii=True)}"
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


def _build_tool_call_signature(mcp_id: str, tool_id: str, arguments: dict[str, object]) -> str:
    normalized_arguments = _normalize_tool_call_arguments(arguments)
    return f"{mcp_id}::{tool_id}::{normalized_arguments}"


def _normalize_tool_call_arguments(arguments: dict[str, object]) -> str:
    try:
        return json.dumps(arguments, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    except TypeError:
        return json.dumps(str(arguments), ensure_ascii=True)


def _align_tool_timeout_argument(
    *,
    arguments: dict[str, object],
    input_schema: dict[str, object],
    timeout_seconds: int,
) -> dict[str, object]:
    properties = input_schema.get("properties") if isinstance(input_schema, dict) else None
    if not isinstance(properties, dict) or "timeout_ms" not in properties:
        return arguments

    effective_max_ms = max(1000, (max(5, int(timeout_seconds)) * 1000) - 1000)
    aligned_arguments = dict(arguments)

    raw_timeout = aligned_arguments.get("timeout_ms")
    if raw_timeout is None:
        aligned_arguments["timeout_ms"] = effective_max_ms
        return aligned_arguments

    parsed_timeout = _safe_int(raw_timeout)
    if parsed_timeout is None:
        return aligned_arguments

    aligned_arguments["timeout_ms"] = max(1000, min(parsed_timeout, effective_max_ms))
    return aligned_arguments


def _safe_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            return None
    return None


def _looks_like_tool_avoidance_response(text: str) -> bool:
    normalized = text.strip().lower().replace("’", "'").replace("`", "'")
    if not normalized:
        return False
    patterns = (
        "i don't have access",
        "i do not have access",
        "can't access",
        "cannot access",
        "unable to access",
        "can't browse",
        "cannot browse",
        "unable to browse",
        "no access to",
        "don't have browsing",
        "do not have browsing",
    )
    return any(pattern in normalized for pattern in patterns)


def _normalize_goal_status(raw_value: object) -> str:
    if not isinstance(raw_value, str):
        return ""
    normalized = raw_value.strip().lower()
    if normalized in {"complete", "incomplete", "blocked"}:
        return normalized
    return ""


_SENSITIVE_FIELD_KEYWORDS = (
    "password",
    "passwd",
    "private_key",
    "passphrase",
    "secret",
    "token",
    "api_key",
    "authorization",
)


def _redact_sensitive_payload(value: object) -> object:
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_field_name(key_text):
                redacted[key_text] = "[REDACTED]"
            else:
                redacted[key_text] = _redact_sensitive_payload(item)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive_payload(item) for item in value]
    return value


def _is_sensitive_field_name(field_name: str) -> bool:
    lowered = field_name.strip().lower()
    return any(keyword in lowered for keyword in _SENSITIVE_FIELD_KEYWORDS)


def _planner_interaction_context(interaction_log: list[dict[str, object]]) -> dict[str, object]:
    return {
        "summary": _interaction_summary(interaction_log),
        "recent_interactions": interaction_log[-_MAX_PLANNER_INTERACTIONS:],
    }


def _interaction_summary(interaction_log: list[dict[str, object]]) -> dict[str, int]:
    tool_calls = 0
    tool_results = 0
    tool_errors = 0
    planner_feedback = 0
    for entry in interaction_log:
        if "tool_call" in entry:
            tool_calls += 1
        if "tool_result" in entry:
            tool_results += 1
        if "tool_error" in entry:
            tool_errors += 1
        if "planner_feedback" in entry:
            planner_feedback += 1

    return {
        "entries": len(interaction_log),
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "tool_errors": tool_errors,
        "planner_feedback": planner_feedback,
    }


def _compact_payload_for_prompt(value: object) -> object:
    compacted = _limit_recursive_value(value, depth=0)
    serialized = _safe_json_dumps(compacted)
    if len(serialized) <= _MAX_TOOL_RESULT_CHARS:
        return compacted

    return {
        "truncated": True,
        "preview": serialized[:_MAX_TOOL_RESULT_CHARS],
        "original_chars": len(serialized),
    }


def _limit_recursive_value(value: object, *, depth: int) -> object:
    if depth >= _MAX_RECURSIVE_VALUE_DEPTH:
        return "[TRUNCATED_DEPTH]"

    if isinstance(value, dict):
        items = list(value.items())
        limited: dict[str, object] = {}
        for key, item in items[:_MAX_RECURSIVE_DICT_ITEMS]:
            limited[str(key)] = _limit_recursive_value(item, depth=depth + 1)
        if len(items) > _MAX_RECURSIVE_DICT_ITEMS:
            limited["_truncated_keys"] = len(items) - _MAX_RECURSIVE_DICT_ITEMS
        return limited

    if isinstance(value, list):
        limited_items = [_limit_recursive_value(item, depth=depth + 1) for item in value[:_MAX_RECURSIVE_LIST_ITEMS]]
        if len(value) > _MAX_RECURSIVE_LIST_ITEMS:
            limited_items.append({"_truncated_items": len(value) - _MAX_RECURSIVE_LIST_ITEMS})
        return limited_items

    if isinstance(value, str):
        if len(value) <= _MAX_TOOL_RESULT_CHARS:
            return value
        return value[:_MAX_TOOL_RESULT_CHARS] + "...[truncated]"

    return value


def _safe_json_dumps(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    except TypeError:
        return json.dumps(str(value), ensure_ascii=True)
