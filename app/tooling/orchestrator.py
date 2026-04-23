"""Sequential tool-orchestration loop that plans, executes tools, and finalizes output."""

import asyncio
import html
import json
import logging
import re
import traceback
from datetime import datetime
from time import monotonic
from typing import Any, Awaitable, Callable, Sequence, TypedDict, cast

logger = logging.getLogger(__name__)

from app.config import McpConfig, SCRIPTS_DIR, Settings, is_script_title_enabled, list_scripts
from app.mcps.base import MCPPlugin, McpConfigField
from app.mcps.registry import get_all_mcps
from app.providers.base import LLMProvider
from app.providers.resilience import ProviderRetryMetadata, generate_with_retries
from .execution import (
    CancellationToken,
    ExecutionEvent,
    TaskIntent,
    build_event_message,
    classify_task_intent,
    execution_event,
    rank_tools_for_intent,
)
from .pipelines import PipelineSpec, get_pipeline_spec
from .runtime_context import get_runtime_context
from .validators import validate_tool_result


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
    execution_events: list[ExecutionEvent]


class PlannerParseResult(TypedDict):
    plan: dict[str, object]
    object_count: int
    selected_index: int
    recovery_mode: str


ExecutionEventCallback = Callable[[ExecutionEvent], Awaitable[None]]


_MAX_PLANNER_INTERACTIONS = 8
_MAX_FINAL_INTERACTIONS = 12
_MAX_TOOL_RESULT_CHARS = 4000
_MAX_RECURSIVE_VALUE_DEPTH = 5
_MAX_RECURSIVE_LIST_ITEMS = 20
_MAX_RECURSIVE_DICT_ITEMS = 40
_MAX_RETRIES_PER_MCP_TOOL = 3
_BULKY_BINARY_FIELD_NAMES = {"content_base64"}
_MAX_SCRIPT_CATALOG_ENTRIES = 100
_MAX_SCRIPT_DESCRIPTION_CHARS = 300
_MAX_INVALID_PLANNER_RESPONSES = 3
_DOOM_LOOP_THRESHOLD = 3
_SCRIPT_CATALOG_NOISE_TOKENS = {
    "action",
    "arguments",
    "automation",
    "automatisierung",
    "bool",
    "call",
    "execute",
    "execute_script",
    "input",
    "input_json",
    "invoke",
    "job",
    "json",
    "keys",
    "mcp",
    "optional",
    "return",
    "returns",
    "run",
    "script",
    "scripts",
    "server",
    "start",
    "title",
    "tool",
    "tools",
    "use",
    "via",
    "workflow",
}


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
    on_execution_event: ExecutionEventCallback | None = None,
    cancellation_token: CancellationToken | None = None,
) -> OrchestrationResult:
    system_trace_messages: list[SystemTraceEntry] = []
    execution_events: list[ExecutionEvent] = []
    used_tools: list[ToolUsageEntry] = []
    token_values: list[int] = []
    started_at = monotonic()
    cancel_token = cancellation_token or CancellationToken()

    async def trace(system_type: str, content: str) -> None:
        entry: SystemTraceEntry = {"system_type": system_type, "content": content}
        system_trace_messages.append(entry)

    async def emit_event(payload: ExecutionEvent) -> None:
        if cancel_token.is_cancelled and payload.get("event_type") != "task_cancelled":
            return
        execution_events.append(payload)
        if on_execution_event is not None:
            await on_execution_event(payload)

    def check_cancelled() -> None:
        cancel_token.raise_if_cancelled()

    await trace("runtime_system_prompt", system_prompt)
    enabled_tools = _collect_enabled_tools(settings)
    task_intent = classify_task_intent(prompt, enabled_tools)
    enabled_tools = rank_tools_for_intent(enabled_tools, task_intent)
    pipeline = get_pipeline_spec(str(task_intent.get("pipeline_id", "")))
    await emit_event(
        execution_event(
            "task_started",
            message="Starting execution.",
            stage="planning",
        )
    )
    await emit_event(
        execution_event(
            "task_classified",
            message=build_event_message(
                "task_classified",
                {
                    "pipeline_id": pipeline["pipeline_id"],
                },
            ),
            stage="planning",
            pipeline_id=pipeline["pipeline_id"],
            categories=list(task_intent.get("categories", [])),
            detail=pipeline["summary"],
        )
    )
    scripts_catalog = await _collect_script_catalog(settings)
    logger.debug(
        "Starting orchestration: prompt_chars=%s enabled_tools=%s scripts=%s max_steps=%s timeout_seconds=%s",
        len(prompt),
        len(enabled_tools),
        len(scripts_catalog),
        max_tool_recursion,
        tool_timeout_seconds,
    )
    logger.debug("Scripts compete through planner selection only; no pre-routing is applied")

    async def provider_generate(
        *,
        prompt_text: str,
        system_prompt_text: str,
        phase_label: str,
    ) -> tuple[str, int | None]:
        async def on_retry(
            attempt: int,
            max_attempts: int,
            delay_seconds: float,
            reason: str,
            metadata: ProviderRetryMetadata,
        ) -> None:
            check_cancelled()
            await trace(
                "provider_retry",
                json.dumps(
                    {
                        "phase_label": phase_label,
                        "attempt": attempt + 1,
                        "max_attempts": max_attempts,
                        "delay_seconds": round(delay_seconds, 3),
                        "reason": reason or "unknown error",
                        **metadata,
                    },
                    ensure_ascii=True,
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
            cancellation_token=cancel_token,
        )

    if not enabled_tools:
        logger.info("No enabled tools available; using direct provider response")
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
            "execution_events": execution_events,
        }

    interaction_log: list[dict[str, object]] = []
    successful_tool_call_signatures: set[str] = set()
    tool_call_attempts_by_signature: dict[str, int] = {}
    tool_call_failures_by_signature: dict[str, int] = {}
    tool_failures_by_mcp_tool: dict[str, int] = {}
    tool_last_error_class_by_mcp_tool: dict[str, str] = {}
    consecutive_invalid_planner_responses = 0
    normalized_recursion = max(1, min(20, int(max_tool_recursion)))
    timeout_seconds = max(5, min(300, int(tool_timeout_seconds)))
    wall_clock_ceiling_seconds = min(normalized_recursion * timeout_seconds, 600)
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
        check_cancelled()
        await trace("tool_step_status", f"Step {step_index}/{normalized_recursion}")
        await emit_event(
            execution_event(
                "step_started",
                message=f"{pipeline['ordered_steps'][min(step_index - 1, len(pipeline['ordered_steps']) - 1)].capitalize()} via {pipeline['pipeline_id'].replace('_', ' ')}.",
                stage=_event_stage_for_step_label(pipeline["ordered_steps"], step_index),
                pipeline_id=pipeline["pipeline_id"],
                categories=list(task_intent.get("categories", [])),
                step_index=step_index,
            )
        )

        # Global wall-clock timeout: abort if we've been running too long.
        elapsed_seconds = monotonic() - started_at
        if elapsed_seconds >= wall_clock_ceiling_seconds:
            logger.warning(
                "Global wall-clock timeout reached at step=%s elapsed=%.1fs ceiling=%ss",
                step_index,
                elapsed_seconds,
                wall_clock_ceiling_seconds,
            )
            await trace(
                "tool_error",
                json.dumps(
                    {
                        "step": step_index,
                        "error": "global_wall_clock_timeout",
                        "elapsed_seconds": round(elapsed_seconds, 1),
                        "ceiling_seconds": wall_clock_ceiling_seconds,
                    },
                    ensure_ascii=True,
                ),
            )
            break

        # Compute which tools need full schema on step 2+: tools that
        # have failed or have never been successfully called yet.
        if step_index > 1:
            succeeded_keys = {
                f"{entry['mcp_id']}.{entry['tool_id']}"
                for entry in used_tools
            }
            failed_keys = set(tool_failures_by_mcp_tool.keys())
            all_keys = {
                f"{entry['mcp_id']}.{entry['tool_id']}"
                for entry in enabled_tools
            }
            failed_or_unused = (all_keys - succeeded_keys) | failed_keys
        else:
            failed_or_unused = None

        planner_prompt = _build_recursive_planner_prompt(
            prompt,
            enabled_tools,
            scripts_catalog,
            _planner_interaction_context(interaction_log),
            step_index,
            normalized_recursion,
            current_local_time,
            task_intent,
            pipeline,
            failed_or_unused_tool_keys=failed_or_unused,
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

        parse_result = _parse_planner_response(planner_response)
        plan = parse_result["plan"]
        logger.debug(
            "Planner step=%s returned action=%s payload=%s",
            step_index,
            str(plan.get("action", "")),
            _safe_json_dumps(_redact_sensitive_payload(plan)),
        )
        if parse_result["object_count"] > 1:
            logger.warning(
                "Planner multi-JSON recovery at step=%s objects=%s selected_index=%s mode=%s",
                step_index,
                parse_result["object_count"],
                parse_result["selected_index"],
                parse_result["recovery_mode"],
            )
            await trace(
                "tool_warning",
                json.dumps(
                    {
                        "step": step_index,
                        "warning": "planner_multi_json_detected",
                        "object_count": parse_result["object_count"],
                        "selected_index": parse_result["selected_index"],
                        "recovery_mode": parse_result["recovery_mode"],
                    },
                    ensure_ascii=True,
                ),
            )
            interaction_log.append(
                {
                    "step": step_index,
                    "planner_feedback": {
                        "type": "planner_multi_json_detected",
                        "message": (
                            "Previous planner output contained multiple JSON objects. "
                            "Return exactly one JSON object for the next step."
                        ),
                        "object_count": parse_result["object_count"],
                    },
                }
            )
        invalid_planner_reason = _invalid_planner_reason(plan)
        if invalid_planner_reason:
            consecutive_invalid_planner_responses += 1
            response_preview = planner_response.strip().replace("\n", " ")[:300]
            logger.warning(
                "Planner returned invalid response at step=%s reason=%s consecutive_invalid=%s preview=%r",
                step_index,
                invalid_planner_reason,
                consecutive_invalid_planner_responses,
                response_preview,
            )
            invalid_payload = {
                "step": step_index,
                "error": "planner_invalid_response",
                "detail": invalid_planner_reason,
                "raw_preview": response_preview,
                "consecutive_invalid": consecutive_invalid_planner_responses,
            }
            await trace("tool_error", json.dumps(invalid_payload, ensure_ascii=True))
            interaction_log.append(
                {
                    "step": step_index,
                    "planner_feedback": {
                        "type": "planner_invalid_response",
                        "message": (
                            "Previous planner output was invalid. Return JSON only and choose a real tool call, "
                            "a non-empty final answer, or a blocked response."
                        ),
                        "detail": invalid_planner_reason,
                    },
                }
            )
            if consecutive_invalid_planner_responses < _MAX_INVALID_PLANNER_RESPONSES and step_index < normalized_recursion:
                continue

            fallback_message = (
                "I could not produce a valid tool-selection plan after multiple attempts. "
                "Please retry or simplify the request."
            )
            logger.info(
                "Orchestration aborted after repeated invalid planner responses: steps=%s tools_used=%s duration_seconds=%.2f",
                step_index,
                len(used_tools),
                monotonic() - started_at,
            )
            return {
                "text": fallback_message,
                "used_tokens": _sum_tokens(*token_values),
                "used_mcp_tools": used_tools,
                "system_trace_messages": system_trace_messages,
                "execution_events": execution_events,
            }

        consecutive_invalid_planner_responses = 0
        action = plan.get("action")

        if action == "respond":
            final_answer = plan.get("final_answer")
            if isinstance(final_answer, str) and final_answer.strip():
                normalized_answer = final_answer.strip()

                # goal_status enforcement removed: if the planner provides a
                # non-empty final_answer the loop accepts it regardless of the
                # goal_status field. Forcing re-iterations on goal_status !=
                # "complete" caused redundant tool calls because the LLM
                # rarely set that field reliably.

                avoidance_pattern = _match_tool_avoidance_pattern(normalized_answer)
                if not used_tools and avoidance_pattern:
                    logger.debug(
                        "Tool avoidance detected at step=%s via pattern=%r",
                        step_index,
                        avoidance_pattern,
                    )
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

                logger.info(
                    "Orchestration completed via planner response: steps=%s tools_used=%s duration_seconds=%.2f",
                    step_index,
                    len(used_tools),
                    monotonic() - started_at,
                )
                await emit_event(
                    execution_event(
                        "task_completed",
                        message="Completed the task.",
                        stage="finalizing",
                        pipeline_id=pipeline["pipeline_id"],
                    )
                )
                return {
                    "text": normalized_answer,
                    "used_tokens": _sum_tokens(*token_values),
                    "used_mcp_tools": used_tools,
                    "system_trace_messages": system_trace_messages,
                    "execution_events": execution_events,
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
            logger.info(
                "Orchestration blocked at step=%s reason=%r required_input=%r duration_seconds=%.2f",
                step_index,
                blocking_reason,
                required_user_input,
                monotonic() - started_at,
            )
            await emit_event(
                execution_event(
                    "task_blocked",
                    message=blocked_message,
                    stage="blocked",
                    pipeline_id=pipeline["pipeline_id"],
                )
            )
            return {
                "text": blocked_message,
                "used_tokens": _sum_tokens(*token_values),
                "used_mcp_tools": used_tools,
                "system_trace_messages": system_trace_messages,
                "execution_events": execution_events,
            }

        if action != "call_tool":
            logger.debug("Planner returned unsupported action=%r at step=%s", action, step_index)
            break

        mcp_id = plan.get("mcp_id")
        tool_id = plan.get("tool_id")
        arguments = plan.get("arguments")

        if not isinstance(tool_id, str) or not tool_id.strip():
            logger.debug("Planner returned invalid tool payload at step=%s: %s", step_index, _safe_json_dumps(_redact_sensitive_payload(plan)))
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
                logger.debug(
                    "Resolved missing mcp_id for tool=%s to %s at step=%s",
                    resolved_tool_id,
                    resolved_mcp_id,
                    step_index,
                )
            else:
                logger.debug(
                    "Planner returned ambiguous mcp_id for tool=%s at step=%s candidates=%s",
                    resolved_tool_id,
                    step_index,
                    candidate_mcps,
                )
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
            logger.debug(
                "Planner selected unavailable tool at step=%s mcp=%s tool=%s available=%s",
                step_index,
                mcp_id,
                tool_id,
                available_for_mcp,
            )
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

        original_tool_arguments = dict(tool_arguments)
        tool_call_payload = {
            "mcp_id": mcp_id,
            "tool_id": tool_id,
            "arguments": _redact_sensitive_payload(tool_arguments),
            "step": step_index,
        }

        input_schema = cast(dict[str, object], tool_entry.get("input_schema", {}))
        reminder_text = await _get_mcp_tool_call_reminder(plugin, tool_id, config.params, arguments=tool_arguments)
        if reminder_text and _should_apply_tool_call_reminder(
            mcp_id=mcp_id,
            tool_id=tool_id,
            input_schema=input_schema,
            arguments=tool_arguments,
        ):
            logger.debug("Applying tool call reminder for mcp=%s tool=%s at step=%s", mcp_id, tool_id, step_index)
            await trace("mcp_tool_call_reminder", reminder_text)
            tool_arguments, reminder_tokens = await _apply_tool_call_reminder(
                provider=provider,
                model=model,
                api_key=api_key,
                history=history,
                user_message=prompt,
                tool_call_payload=tool_call_payload,
                tool_input_schema=input_schema,
                reminder_text=reminder_text,
                current_local_time=current_local_time,
                original_arguments=tool_arguments,
                mcp_id=mcp_id,
                tool_id=tool_id,
            )
            if isinstance(reminder_tokens, int):
                token_values.append(reminder_tokens)
            tool_call_payload["arguments"] = _redact_sensitive_payload(tool_arguments)

        tool_arguments = _align_tool_timeout_argument(
            arguments=tool_arguments,
            input_schema=input_schema,
            timeout_seconds=timeout_seconds,
        )
        tool_arguments = _repair_tool_arguments(
            mcp_id=mcp_id,
            tool_id=tool_id,
            input_schema=input_schema,
            original_arguments=original_tool_arguments,
            candidate_arguments=tool_arguments,
        )
        tool_call_payload["arguments"] = _redact_sensitive_payload(tool_arguments)

        tool_call_signature = _build_tool_call_signature(mcp_id, tool_id, tool_arguments)
        signature_attempts = tool_call_attempts_by_signature.get(tool_call_signature, 0)
        failure_attempts = tool_call_failures_by_signature.get(tool_call_signature, 0)
        tool_call_id = _build_tool_call_id(step_index, mcp_id, tool_id, signature_attempts + 1)
        tool_call_payload["call_id"] = tool_call_id

        missing_required_arguments = _missing_required_arguments(
            input_schema,
            tool_arguments,
        )
        if missing_required_arguments:
            logger.debug(
                "Missing required arguments for mcp=%s tool=%s at step=%s missing=%s",
                mcp_id,
                tool_id,
                step_index,
                missing_required_arguments,
            )
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

        argument_validation_errors = _validate_tool_arguments(
            input_schema,
            tool_arguments,
        )
        if argument_validation_errors:
            logger.debug(
                "Tool argument validation failed at step=%s mcp=%s tool=%s errors=%s",
                step_index,
                mcp_id,
                tool_id,
                argument_validation_errors,
            )
            validation_payload = {
                "mcp_id": mcp_id,
                "tool_id": tool_id,
                "call_id": tool_call_id,
                "arguments": _redact_sensitive_payload(tool_arguments),
                "step": step_index,
                "error": "tool_argument_validation_failed",
                "validation_errors": argument_validation_errors,
            }
            await trace("tool_error", json.dumps(validation_payload, ensure_ascii=True))
            interaction_log.append(
                {
                    "step": step_index,
                    "tool_call": tool_call_payload,
                    "tool_error": {
                        "type": "tool_argument_validation_failed",
                        "message": "Tool arguments did not satisfy the tool schema.",
                        "validation_errors": argument_validation_errors,
                    },
                    "planner_feedback": {
                        "type": "tool_argument_validation_failed",
                        "message": "Rewrite the same tool call so the arguments satisfy the schema.",
                        "validation_errors": argument_validation_errors,
                    },
                }
            )
            continue

        if failure_attempts >= _DOOM_LOOP_THRESHOLD:
            doom_payload = {
                "mcp_id": mcp_id,
                "tool_id": tool_id,
                "call_id": tool_call_id,
                "arguments": _redact_sensitive_payload(tool_arguments),
                "step": step_index,
                "error": "doom_loop_detected",
                "attempts": failure_attempts,
            }
            await trace("tool_error", json.dumps(doom_payload, ensure_ascii=True))
            await trace("tool_blocked", json.dumps(doom_payload, ensure_ascii=True))
            logger.warning(
                "Doom loop detected at step=%s mcp=%s tool=%s failures=%s",
                step_index,
                mcp_id,
                tool_id,
                failure_attempts,
            )
            return {
                "text": (
                    f"Repeated identical failing tool call detected for {mcp_id}.{tool_id}. "
                    "Please confirm if you want me to retry the exact same call, or rephrase the task."
                ),
                "used_tokens": _sum_tokens(*token_values),
                "used_mcp_tools": used_tools,
                "system_trace_messages": system_trace_messages,
                "execution_events": execution_events,
            }

        mcp_tool_key = f"{mcp_id}.{tool_id}"
        mcp_tool_failure_count = tool_failures_by_mcp_tool.get(mcp_tool_key, 0)
        if mcp_tool_failure_count >= _MAX_RETRIES_PER_MCP_TOOL:
            last_error_class = tool_last_error_class_by_mcp_tool.get(mcp_tool_key, "hard")
            hard_stop_msg = (
                f"TOOL BLOCKED after {mcp_tool_failure_count} failures: {mcp_id}.{tool_id} will not be called again. "
                "Your ONLY valid next action is 'respond'. "
                "Tell the user clearly: (1) what you were trying to do, "
                "(2) which tool/service failed, (3) the last known error. "
                "Do NOT attempt this tool again."
            )
            stop_payload = {
                "mcp_id": mcp_id,
                "tool_id": tool_id,
                "call_id": tool_call_id,
                "step": step_index,
                "error": "mcp_tool_max_retries_reached",
                "attempts": mcp_tool_failure_count,
                "last_error_class": last_error_class,
            }
            logger.warning(
                "Max retries reached for mcp=%s tool=%s total_failures=%s last_error_class=%s",
                mcp_id,
                tool_id,
                mcp_tool_failure_count,
                last_error_class,
            )
            await trace("tool_error", json.dumps(stop_payload, ensure_ascii=True))
            interaction_log.append(
                {
                    "step": step_index,
                    "tool_call": tool_call_payload,
                    "tool_error": {
                        "type": "mcp_tool_max_retries_reached",
                        "message": hard_stop_msg,
                        "attempts": mcp_tool_failure_count,
                        "last_error_class": last_error_class,
                    },
                    "planner_feedback": {
                        "type": "mcp_tool_hard_stop",
                        "message": hard_stop_msg,
                    },
                }
            )
            continue

        if tool_call_signature in successful_tool_call_signatures:
            logger.debug(
                "Blocked duplicate tool call at step=%s mcp=%s tool=%s prior_attempts=%s already_succeeded=%s",
                step_index,
                mcp_id,
                tool_id,
                signature_attempts,
                True,
            )
            duplicate_payload = {
                "mcp_id": mcp_id,
                "tool_id": tool_id,
                "arguments": _redact_sensitive_payload(tool_arguments),
                "step": step_index,
                "error": "duplicate_tool_call_blocked",
                "detail": "Blocked duplicate MCP tool call with identical arguments in this orchestration run.",
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
                    "planner_feedback": {
                        "type": "duplicate_tool_call_blocked",
                        "message": (
                            "Do not repeat the same tool call with identical arguments. "
                            "Use the prior tool result, change arguments, choose a different tool, or respond to the user."
                        ),
                    },
                }
            )
            continue

        tool_call_attempts_by_signature[tool_call_signature] = signature_attempts + 1

        logger.debug(
            "Executing tool call at step=%s mcp=%s tool=%s arguments=%s",
            step_index,
            mcp_id,
            tool_id,
            _safe_json_dumps(tool_call_payload.get("arguments")),
        )
        await trace(
            "tool_call_started",
            json.dumps(
                {
                    "call_id": tool_call_id,
                    "mcp_id": mcp_id,
                    "tool_id": tool_id,
                    "step": step_index,
                },
                ensure_ascii=True,
            ),
        )
        await trace("tool_call", json.dumps(tool_call_payload, ensure_ascii=True))
        await emit_event(
            execution_event(
                "tool_call_started",
                message=build_event_message(
                    "tool_call_started",
                    {
                        "mcp_id": mcp_id,
                        "mcp_label": tool_usage["mcp_label"],
                        "tool_id": tool_id,
                        "tool_label": tool_usage["tool_label"],
                    },
                ),
                stage=_stage_for_mcp_id(mcp_id),
                pipeline_id=pipeline["pipeline_id"],
                mcp_id=mcp_id,
                mcp_label=tool_usage["mcp_label"],
                tool_id=tool_id,
                tool_label=tool_usage["tool_label"],
                step_index=step_index,
                call_id=tool_call_id,
            )
        )

        try:
            check_cancelled()
            tool_result = await asyncio.wait_for(
                plugin.call_tool(tool_id, tool_arguments, config.params),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            logger.warning(
                "Tool execution timeout at step=%s mcp=%s tool=%s timeout_seconds=%s",
                step_index,
                mcp_id,
                tool_id,
                timeout_seconds,
            )
            # Count timeouts toward per-(mcp, tool) failure tracking so
            # consistently-timing-out tools eventually get blocked.
            timeout_mcp_tool_failures = tool_failures_by_mcp_tool.get(mcp_tool_key, 0) + 1
            tool_failures_by_mcp_tool[mcp_tool_key] = timeout_mcp_tool_failures
            tool_last_error_class_by_mcp_tool[mcp_tool_key] = "hard"
            timeout_retry_hint = _build_retry_hint("hard", mcp_id, tool_id, timeout_mcp_tool_failures)
            tool_error_payload = {
                "mcp_id": mcp_id,
                "tool_id": tool_id,
                "call_id": tool_call_id,
                "arguments": _redact_sensitive_payload(tool_arguments),
                "step": step_index,
                "error": "tool_execution_timeout",
                "error_class": "hard",
                "detail": f"{plugin.display_name} ({tool_id}) exceeded timeout of {timeout_seconds}s.",
                "mcp_tool_attempt": timeout_mcp_tool_failures,
            }
            tool_call_failures_by_signature[tool_call_signature] = failure_attempts + 1
            await emit_event(
                execution_event(
                    "fallback_started",
                    message="Tool timed out; trying a fallback route if available.",
                    stage="validating",
                    pipeline_id=pipeline["pipeline_id"],
                    mcp_id=mcp_id,
                    tool_id=tool_id,
                    step_index=step_index,
                    call_id=tool_call_id,
                )
            )
            await trace("tool_call_failed", json.dumps(tool_error_payload, ensure_ascii=True))
            await trace("tool_error", json.dumps(tool_error_payload, ensure_ascii=True))
            interaction_log.append(
                {
                    "step": step_index,
                    "tool_call": tool_call_payload,
                    "tool_error": {
                        "type": "tool_execution_timeout",
                        "message": f"{plugin.display_name} ({tool_id}) exceeded timeout of {timeout_seconds}s.",
                        "error_class": "hard",
                        "mcp_tool_attempt": timeout_mcp_tool_failures,
                        "retry_hint": timeout_retry_hint,
                    },
                }
            )
            continue
        except Exception as exc:
            exc_type = type(exc).__name__
            exc_message = str(exc).strip() or "(no message)"
            exc_detail = f"{exc_type}: {exc_message}"
            error_class = _classify_tool_error(exc_detail)
            logger.error(
                "Tool execution failed: mcp=%s tool=%s error_class=%s error=%s\n%s",
                mcp_id, tool_id, error_class, exc_detail, traceback.format_exc(),
            )
            # Update per-(mcp, tool) failure tracking
            updated_mcp_tool_failures = tool_failures_by_mcp_tool.get(mcp_tool_key, 0) + 1
            tool_failures_by_mcp_tool[mcp_tool_key] = updated_mcp_tool_failures
            tool_last_error_class_by_mcp_tool[mcp_tool_key] = error_class
            retry_hint = _build_retry_hint(error_class, mcp_id, tool_id, updated_mcp_tool_failures)
            tool_error_payload = {
                "mcp_id": mcp_id,
                "tool_id": tool_id,
                "call_id": tool_call_id,
                "arguments": _redact_sensitive_payload(tool_arguments),
                "step": step_index,
                "error": "tool_execution_failed",
                "error_class": error_class,
                "detail": exc_detail,
                "mcp_tool_attempt": updated_mcp_tool_failures,
            }
            tool_call_failures_by_signature[tool_call_signature] = failure_attempts + 1
            await emit_event(
                execution_event(
                    "fallback_started",
                    message="Tool failed; trying a fallback route if available.",
                    stage="validating",
                    pipeline_id=pipeline["pipeline_id"],
                    mcp_id=mcp_id,
                    tool_id=tool_id,
                    step_index=step_index,
                    call_id=tool_call_id,
                )
            )
            await trace("tool_call_failed", json.dumps(tool_error_payload, ensure_ascii=True))
            await trace("tool_error", json.dumps(tool_error_payload, ensure_ascii=True))
            interaction_log.append(
                {
                    "step": step_index,
                    "tool_call": tool_call_payload,
                    "tool_error": {
                        "type": "tool_execution_failed",
                        "message": exc_detail,
                        "error_class": error_class,
                        "mcp_tool_attempt": updated_mcp_tool_failures,
                        "retry_hint": retry_hint,
                    },
                }
            )
            continue

        successful_tool_call_signatures.add(tool_call_signature)
        tool_call_failures_by_signature.pop(tool_call_signature, None)
        used_tools.append(tool_usage)
        logger.debug(
            "Tool execution succeeded at step=%s mcp=%s tool=%s used_tools=%s",
            step_index,
            mcp_id,
            tool_id,
            len(used_tools),
        )

        redacted_tool_result = _redact_sensitive_payload(tool_result)
        compact_tool_result = _compact_payload_for_prompt(redacted_tool_result)
        validation = validate_tool_result(
            mcp_id=mcp_id,
            tool_id=tool_id,
            result=tool_result,
            intent=task_intent,
        )
        await trace(
            "tool_call_completed",
            json.dumps(
                {
                    "call_id": tool_call_id,
                    "mcp_id": mcp_id,
                    "tool_id": tool_id,
                    "step": step_index,
                },
                ensure_ascii=True,
            ),
        )
        await trace("tool_result", json.dumps(compact_tool_result, ensure_ascii=True))
        # Emit a UI event for the validation outcome but always keep the
        # tool result — failed validation is a hint, not a blocker. Forcing
        # a re-loop here caused redundant extra tool calls when the planner
        # could have simply acted on the result it already had.
        if validation["passed"]:
            await emit_event(
                execution_event(
                    "validation_passed",
                    message=f"Validated the result from {tool_usage['mcp_label']}.",
                    stage="validating",
                    pipeline_id=pipeline["pipeline_id"],
                    mcp_id=mcp_id,
                    tool_id=tool_id,
                    step_index=step_index,
                    call_id=tool_call_id,
                    reason=validation["validator"],
                    detail=validation["detail"],
                )
            )
        else:
            await emit_event(
                execution_event(
                    "validation_failed",
                    message="The result did not pass validation; the planner will decide next steps.",
                    stage="validating",
                    pipeline_id=pipeline["pipeline_id"],
                    mcp_id=mcp_id,
                    tool_id=tool_id,
                    step_index=step_index,
                    call_id=tool_call_id,
                    reason=validation["validator"],
                    detail=validation["detail"],
                )
            )
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

    logger.info(
        "Orchestration completed via final response: steps=%s tools_used=%s duration_seconds=%.2f",
        len(interaction_log),
        len(used_tools),
        monotonic() - started_at,
    )
    await emit_event(
        execution_event(
            "task_completed",
            message="Completed the task.",
            stage="finalizing",
            pipeline_id=pipeline["pipeline_id"],
        )
    )

    return {
        "text": final_response,
        "used_tokens": _sum_tokens(*token_values),
        "used_mcp_tools": used_tools,
        "system_trace_messages": system_trace_messages,
        "execution_events": execution_events,
    }


def _sum_tokens(*token_values: int | None) -> int | None:
    values = [value for value in token_values if isinstance(value, int)]
    if not values:
        return None
    return sum(values)


def _event_stage_for_step_label(step_labels: Sequence[str], step_index: int) -> str:
    if not step_labels:
        return "working"
    label = str(step_labels[min(max(step_index - 1, 0), len(step_labels) - 1)]).strip().lower()
    if label.startswith("fetch") or label.startswith("resolve"):
        return "fetching"
    if label.startswith("modify") or label.startswith("apply") or label.startswith("publish"):
        return "updating"
    if label.startswith("validate") or label.startswith("confirm") or label.startswith("verify"):
        return "validating"
    if label.startswith("final"):
        return "finalizing"
    if label.startswith("inspect") or label.startswith("route"):
        return "planning"
    return "working"


def _stage_for_mcp_id(mcp_id: str) -> str:
    normalized = str(mcp_id or "").strip().lower()
    if normalized in {"google_services", "brave_search", "browser_control", "youtube_summarizer"}:
        return "fetching"
    if normalized in {"git_ops", "shell_access", "opencode", "scripts"}:
        return "updating"
    if normalized in {"home_assistant", "whatsapp", "brain_access", "timed_jobs"}:
        return "applying"
    return "working"


def _collect_enabled_tools(settings: Settings) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    all_mcps = get_all_mcps()
    tool_counts_by_mcp: dict[str, int] = {}
    runtime_context = get_runtime_context()
    source_user_role = str(runtime_context.get("source_user_role", "")).strip().lower()
    allowed_mcp_ids = {
        str(item).strip()
        for item in runtime_context.get("allowed_mcp_ids", [])
        if str(item).strip()
    }

    for mcp_id, plugin in all_mcps.items():
        if source_user_role == "assistant_usage" and mcp_id not in allowed_mcp_ids:
            continue
        raw_config = settings.mcp_configs.get(mcp_id)
        if raw_config is None:
            config = McpConfig(enabled=bool(getattr(plugin, "default_enabled", False)), params={})
        else:
            config = raw_config

        if not config.enabled:
            logger.debug("Skipping MCP %s because it is disabled", mcp_id)
            continue

        missing_required = _missing_required_param_ids(plugin.config_fields, config)
        if missing_required:
            logger.debug("Skipping MCP %s because required params are missing: %s", mcp_id, missing_required)
            continue

        tool_specs = plugin.tool_specs()
        if hasattr(plugin, "tool_specs_for_config"):
            try:
                maybe_specs = getattr(plugin, "tool_specs_for_config")(config.params)
                if isinstance(maybe_specs, list):
                    tool_specs = maybe_specs
            except Exception:
                tool_specs = plugin.tool_specs()

        tool_counts_by_mcp[mcp_id] = len(tool_specs)
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

    logger.debug(
        "Collected %s enabled tools across %s MCPs: %s",
        len(entries),
        len(tool_counts_by_mcp),
        ", ".join(f"{mcp_id}={count}" for mcp_id, count in sorted(tool_counts_by_mcp.items())) or "none",
    )
    return entries


def _missing_required_params(config_fields: Sequence[McpConfigField], config: McpConfig) -> bool:
    return bool(_missing_required_param_ids(config_fields, config))


def _missing_required_param_ids(config_fields: Sequence[McpConfigField], config: McpConfig) -> list[str]:
    missing: list[str] = []
    for field in config_fields:
        if not field.required:
            continue

        value = config.params.get(field.id, "")
        if not isinstance(value, str) or not value.strip():
            missing.append(field.id)

    return missing


def _build_recursive_planner_prompt(
    user_message: str,
    tools: list[dict[str, object]],
    scripts_catalog: list[dict[str, str]],
    interaction_context: dict[str, object],
    step_index: int,
    max_steps: int,
    current_local_time: str,
    task_intent: TaskIntent,
    pipeline: PipelineSpec,
    failed_or_unused_tool_keys: set[str] | None = None,
) -> str:
    if step_index <= 1:
        # Step 1: full detail for every tool.
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
    else:
        # Steps 2+: full schema for tools that failed or haven't been called;
        # compact summary for tools that already succeeded.
        needs_schema = failed_or_unused_tool_keys or set()
        tool_payload = []
        for entry in tools:
            key = f"{entry['mcp_id']}.{entry['tool_id']}"
            if key in needs_schema:
                tool_payload.append(
                    {
                        "mcp_id": entry["mcp_id"],
                        "mcp_label": entry["mcp_label"],
                        "tool_id": entry["tool_id"],
                        "tool_label": entry["tool_label"],
                        "description": entry["tool_description"],
                        "input_schema": entry["input_schema"],
                    }
                )
            else:
                tool_payload.append(
                    {
                        "mcp_id": entry["mcp_id"],
                        "tool_id": entry["tool_id"],
                        "description": entry["tool_description"],
                    }
                )

    compact_separators = (",", ":")

    return (
        "You can recursively call tools.\n"
        f"Current step: {step_index} of {max_steps}.\n"
        "Return exactly one JSON object only. No prose, no markdown, no code fences.\n"
        "Tool selection is intent-based and language-agnostic: infer user intent semantically even when the user writes in any language or mixed languages.\n"
        "Your goal is to complete the user's original request end-to-end, not to stop at intermediate status updates.\n"
        "If user asks for live/external/private data (web, files, integrations, devices, Home Assistant, calendars, email), use a tool call first.\n"
        "Scripts catalog items are reference assets. To run one, call scripts.execute_script with its title.\n"
        "If user asks you to remember/memorize/not forget something for future chats, call brain_access.save_memory before responding.\n"
        "Do not claim you cannot access browsing/tools/devices when relevant tools are listed.\n"
        "Only ask the user for help if truly blocked by missing user-only input, explicit approval, or an external challenge that tools cannot resolve.\n"
        "If information can be fetched via enabled tools, fetch it yourself and continue.\n"
        f"Task categories: {json.dumps(task_intent.get('categories', []), ensure_ascii=True)}\n"
        f"Preferred pipeline: {json.dumps(pipeline, ensure_ascii=True)}\n"
        f"Completion criteria: {json.dumps(task_intent.get('completion_criteria', []), ensure_ascii=True)}\n"
        f"Validation focus: {json.dumps(task_intent.get('validation_focus', []), ensure_ascii=True)}\n"
        f"Preferred MCP order: {json.dumps(task_intent.get('preferred_mcp_ids', []), ensure_ascii=True)}\n"
        "\n"
        "=== TOOL USAGE RULES ===\n"
        "Before calling a tool, you MUST:\n"
        "1. Read the tool 'description' to understand what it does.\n"
        "2. Check the tool 'input_schema' for required and optional arguments, their names, and their types.\n"
        "3. Match argument names EXACTLY as listed in the schema (case-sensitive).\n"
        "4. For scripts, use 'description' in the scripts catalog to decide WHICH script to run; the exact input_json keys will be provided after you select the script.\n"
        "5. Never invent argument names that are not in the schema.\n"
        "6. If you already have enough tool results to answer, respond instead of calling another tool.\n"
        "\n"
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
        f"Available tools: {json.dumps(tool_payload, separators=compact_separators)}\n"
        f"Available scripts catalog: {json.dumps(scripts_catalog, ensure_ascii=True, separators=compact_separators)}\n"
        f"Completed tool interactions so far: {json.dumps(interaction_context, ensure_ascii=True, separators=compact_separators)}"
    )


async def _collect_script_catalog(settings: Settings) -> list[dict[str, str]]:
    scripts_config = settings.mcp_configs.get("scripts")
    if scripts_config is None:
        scripts_enabled = False
    else:
        scripts_enabled = bool(scripts_config.enabled)

    if not scripts_enabled:
        return []

    scripts_params = scripts_config.params if scripts_config is not None else {}

    try:
        scripts = await list_scripts()
    except Exception:
        return []

    entries: list[dict[str, str]] = []
    for script in sorted(scripts, key=lambda item: item.title.lower()):
        title = str(script.title).strip()
        description = str(script.description).strip()
        instructions = str(script.instructions).strip()
        file_name = str(script.file_name).strip()
        if not title or not description or not file_name:
            continue
        if not is_script_title_enabled(title, scripts_params):
            continue
        path = (SCRIPTS_DIR / file_name).resolve()
        if path.parent != SCRIPTS_DIR:
            continue
        compact_description = description[:_MAX_SCRIPT_DESCRIPTION_CHARS]
        semantic_terms = _sanitize_script_catalog_text(f"{description} {instructions}")
        entries.append(
            {
                "title": title,
                "description": compact_description,
                "semantic_terms": semantic_terms,
                "path": str(path),
            }
        )
        if len(entries) >= _MAX_SCRIPT_CATALOG_ENTRIES:
            break
    return entries


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


def _sanitize_script_catalog_text(text: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    filtered: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if len(token) <= 2 or token in _SCRIPT_CATALOG_NOISE_TOKENS:
            continue
        if token in seen:
            continue
        seen.add(token)
        filtered.append(token)
    return " ".join(filtered)


def _invalid_planner_reason(plan: dict[str, object]) -> str:
    action = str(plan.get("action", "")).strip()
    if not action:
        return "Planner response is missing an action."

    if action == "call_tool":
        tool_id = plan.get("tool_id")
        if not isinstance(tool_id, str) or not tool_id.strip():
            return "Planner tool call is missing a valid tool_id."
        return ""

    if action == "respond":
        final_answer = plan.get("final_answer")
        if not isinstance(final_answer, str) or not final_answer.strip():
            return "Planner respond action is missing a non-empty final_answer."
        return ""

    if action == "blocked":
        blocking_reason = plan.get("blocking_reason")
        required_user_input = plan.get("required_user_input")
        if isinstance(blocking_reason, str) and blocking_reason.strip():
            return ""
        if isinstance(required_user_input, str) and required_user_input.strip():
            return ""
        return "Planner blocked action is missing blocking details."

    return f"Planner returned unsupported action {action!r}."


def _parse_planner_response(response_text: str) -> PlannerParseResult:
    wrapped_tool_call = _extract_tool_call_wrapper(response_text)
    if wrapped_tool_call is not None:
        return {
            "plan": wrapped_tool_call,
            "object_count": 1,
            "selected_index": 0,
            "recovery_mode": "tool_call_wrapper",
        }

    xml_tool_call = _extract_xml_tool_call_wrapper(response_text)
    if xml_tool_call is not None:
        return {
            "plan": xml_tool_call,
            "object_count": 1,
            "selected_index": 0,
            "recovery_mode": "xml_tool_call_wrapper",
        }

    try:
        payload = json.loads(response_text)
        if isinstance(payload, dict):
            return {
                "plan": payload,
                "object_count": 1,
                "selected_index": 0,
                "recovery_mode": "full_json",
            }
        if isinstance(payload, list):
            dict_payloads = [item for item in payload if isinstance(item, dict)]
            if dict_payloads:
                selected_index, selected_payload, recovery_mode = _select_planner_payload(dict_payloads)
                return {
                    "plan": selected_payload,
                    "object_count": len(dict_payloads),
                    "selected_index": selected_index,
                    "recovery_mode": f"full_json_list_{recovery_mode}",
                }
    except Exception:
        pass

    parsed_objects = _extract_planner_json_objects(response_text)
    if parsed_objects:
        selected_index, selected_payload, recovery_mode = _select_planner_payload(parsed_objects)
        return {
            "plan": selected_payload,
            "object_count": len(parsed_objects),
            "selected_index": selected_index,
            "recovery_mode": recovery_mode,
        }

    start = response_text.find("{")
    end = response_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        stripped = response_text.strip()
        if stripped:
            return {
                "plan": {
                    "action": "respond",
                    "goal_status": "complete",
                    "final_answer": stripped,
                },
                "object_count": 0,
                "selected_index": -1,
                "recovery_mode": "plain_text_response",
            }
        return {
            "plan": {"action": "respond", "final_answer": ""},
            "object_count": 0,
            "selected_index": -1,
            "recovery_mode": "no_json_found",
        }

    candidate = response_text[start : end + 1]
    try:
        payload = json.loads(candidate)
        if isinstance(payload, dict):
            return {
                "plan": payload,
                "object_count": 1,
                "selected_index": 0,
                "recovery_mode": "trimmed_json",
            }
    except Exception:
        return {
            "plan": {"action": "respond", "final_answer": ""},
            "object_count": 0,
            "selected_index": -1,
            "recovery_mode": "invalid_json",
        }

    return {
        "plan": {"action": "respond", "final_answer": ""},
        "object_count": 0,
        "selected_index": -1,
        "recovery_mode": "invalid_json",
    }


def _extract_planner_json_objects(response_text: str) -> list[dict[str, object]]:
    decoder = json.JSONDecoder()
    objects: list[dict[str, object]] = []
    index = 0
    length = len(response_text)

    while index < length:
        next_brace = response_text.find("{", index)
        if next_brace == -1:
            break
        try:
            payload, end_index = decoder.raw_decode(response_text, next_brace)
        except json.JSONDecodeError:
            index = next_brace + 1
            continue
        if isinstance(payload, dict):
            objects.append(payload)
        index = max(end_index, next_brace + 1)

    return objects


def _extract_tool_call_wrapper(response_text: str) -> dict[str, object] | None:
    match = re.search(r"\[TOOL_CALL\](.*?)\[/TOOL_CALL\]", response_text, flags=re.DOTALL | re.IGNORECASE)
    if match is None:
        return None
    body = match.group(1).strip()
    if not body:
        return None

    tool_match = re.search(r'tool\s*=>\s*"([^"]+)"', body, flags=re.IGNORECASE)
    if tool_match is None:
        return None
    tool_name = tool_match.group(1).strip()
    if not tool_name:
        return None

    arguments: dict[str, object] = {}
    args_match = re.search(r"args\s*=>\s*\{(.*)\}\s*$", body, flags=re.DOTALL | re.IGNORECASE)
    if args_match is not None:
        arguments = _parse_tool_call_wrapper_arguments(args_match.group(1))

    mcp_id, tool_id = _split_wrapped_tool_name(tool_name)
    return {
        "action": "call_tool",
        "mcp_id": mcp_id,
        "tool_id": tool_id,
        "arguments": arguments,
    }


def _extract_xml_tool_call_wrapper(response_text: str) -> dict[str, object] | None:
    wrapper_match = re.search(r"<function_calls\b[^>]*>(.*?)</function_calls>", response_text, flags=re.DOTALL | re.IGNORECASE)
    if wrapper_match is None:
        return None

    invoke_match = re.search(
        r"<invoke\b[^>]*name=\"([^\"]+)\"[^>]*>(.*?)</invoke>",
        wrapper_match.group(1),
        flags=re.DOTALL | re.IGNORECASE,
    )
    if invoke_match is None:
        return None

    raw_tool_name = invoke_match.group(1).strip()
    if not raw_tool_name:
        return None

    arguments: dict[str, object] = {}
    for arg_match in re.finditer(
        r"<arg\b[^>]*name=\"([^\"]+)\"[^>]*>(.*?)</arg>",
        invoke_match.group(2),
        flags=re.DOTALL | re.IGNORECASE,
    ):
        raw_key = arg_match.group(1).strip()
        if not raw_key:
            continue
        raw_value = html.unescape(arg_match.group(2).strip())
        parsed_int = _safe_int(raw_value)
        lowered_value = raw_value.lower()
        if lowered_value == "true":
            value: object = True
        elif lowered_value == "false":
            value = False
        elif parsed_int is not None:
            value = parsed_int
        else:
            value = raw_value
        arguments[_normalize_tool_wrapper_token(raw_key)] = value

    normalized_tool_name = _normalize_tool_wrapper_tool_name(raw_tool_name)
    mcp_id, tool_id = _split_wrapped_tool_name(normalized_tool_name)
    return {
        "action": "call_tool",
        "mcp_id": mcp_id,
        "tool_id": tool_id,
        "arguments": arguments,
    }


def _split_wrapped_tool_name(tool_name: str) -> tuple[str, str]:
    normalized = tool_name.strip()
    if "." in normalized:
        mcp_id, tool_id = normalized.split(".", 1)
        return mcp_id.strip(), tool_id.strip()
    if normalized.startswith("gmail_") or normalized.startswith("calendar_") or normalized.startswith("drive_"):
        return "google_services", normalized
    return "", normalized


def _normalize_tool_wrapper_tool_name(tool_name: str) -> str:
    normalized = _normalize_tool_wrapper_token(tool_name)
    if not normalized:
        return ""
    if "." in normalized:
        mcp_id, tool_id = normalized.split(".", 1)
        return f"{mcp_id}.{tool_id}"
    return normalized


def _normalize_tool_wrapper_token(value: str) -> str:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(value or "").strip())
    normalized = re.sub(r"[^a-zA-Z0-9.]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_").lower()


def _parse_tool_call_wrapper_arguments(body: str) -> dict[str, object]:
    arguments: dict[str, object] = {}
    matches = re.findall(r'--([a-zA-Z0-9_-]+)\s+("[^"]*"|\S+)', body)
    for raw_key, raw_value in matches:
        key = raw_key.strip().replace("-", "_")
        if raw_value.startswith('"') and raw_value.endswith('"') and len(raw_value) >= 2:
            value: object = raw_value[1:-1]
        else:
            parsed_int = _safe_int(raw_value)
            value = parsed_int if parsed_int is not None else raw_value
        arguments[key] = value
    return arguments


def _select_planner_payload(parsed_objects: list[dict[str, object]]) -> tuple[int, dict[str, object], str]:
    for index, payload in enumerate(parsed_objects):
        if str(payload.get("action", "")).strip() == "call_tool":
            return index, payload, "first_call_tool"
    for index, payload in enumerate(parsed_objects):
        if str(payload.get("action", "")).strip() == "blocked":
            return index, payload, "first_blocked"
    for index, payload in enumerate(parsed_objects):
        if str(payload.get("action", "")).strip() == "respond":
            return index, payload, "first_respond"
    return 0, parsed_objects[0], "first_object"


async def _get_mcp_tool_call_reminder(
    plugin: MCPPlugin, tool_id: str, params: dict[str, str],
    arguments: dict[str, object] | None = None,
) -> str:
    # Prefer async variant that receives tool arguments (script-specific instructions).
    async_factory = getattr(plugin, "async_tool_call_system_reminder", None)
    if callable(async_factory) and arguments is not None:
        try:
            maybe_reminder = async_factory(tool_id, arguments, params)
            if asyncio.iscoroutine(maybe_reminder):
                reminder = await maybe_reminder
            else:
                reminder = maybe_reminder
            if isinstance(reminder, str) and reminder.strip():
                return reminder.strip()
        except Exception:
            pass  # fall through to sync variant

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
    original_arguments: dict[str, object] | None = None,
    mcp_id: str = "",
    tool_id: str = "",
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
    maybe_args = parsed["plan"].get("arguments")
    if isinstance(maybe_args, dict):
        repaired = _repair_tool_arguments(
            mcp_id=mcp_id,
            tool_id=tool_id,
            input_schema=tool_input_schema,
            original_arguments=original_arguments or {},
            candidate_arguments=cast(dict[str, object], maybe_args),
        )
        if _should_keep_rewritten_arguments(tool_input_schema, original_arguments or {}, repaired):
            return repaired, used_tokens if isinstance(used_tokens, int) else None

    try:
        payload = json.loads(response_text)
        if isinstance(payload, dict):
            raw_args = payload.get("arguments")
            if isinstance(raw_args, dict):
                repaired = _repair_tool_arguments(
                    mcp_id=mcp_id,
                    tool_id=tool_id,
                    input_schema=tool_input_schema,
                    original_arguments=original_arguments or {},
                    candidate_arguments=cast(dict[str, object], raw_args),
                )
                if _should_keep_rewritten_arguments(tool_input_schema, original_arguments or {}, repaired):
                    return repaired, used_tokens if isinstance(used_tokens, int) else None
    except Exception:
        pass

    # Fallback: return the original unredacted arguments so we never leak
    # "[REDACTED]" placeholder strings into actual tool calls.
    if isinstance(original_arguments, dict):
        return original_arguments, used_tokens if isinstance(used_tokens, int) else None

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


def _should_apply_tool_call_reminder(
    *,
    mcp_id: str,
    tool_id: str,
    input_schema: dict[str, object],
    arguments: dict[str, object],
) -> bool:
    # Only fire the reminder (extra LLM call) when arguments are genuinely
    # malformed — missing required fields or wrong types. The previous
    # unconditional whitelist for calendar/gmail/home_assistant caused a
    # redundant LLM round-trip on every call to those tools even when the
    # arguments were already correct.
    if _missing_required_arguments(input_schema, arguments):
        return True
    if _validate_tool_arguments(input_schema, arguments):
        return True
    return False


def _should_keep_rewritten_arguments(
    input_schema: dict[str, object],
    original_arguments: dict[str, object],
    candidate_arguments: dict[str, object],
) -> bool:
    original_missing = _missing_required_arguments(input_schema, original_arguments)
    candidate_missing = _missing_required_arguments(input_schema, candidate_arguments)
    if candidate_missing and len(candidate_missing) >= len(original_missing):
        return False

    original_errors = _validate_tool_arguments(input_schema, original_arguments)
    candidate_errors = _validate_tool_arguments(input_schema, candidate_arguments)
    if candidate_errors and len(candidate_errors) >= len(original_errors):
        return False

    required_keys = _required_argument_keys(input_schema)
    for key in required_keys:
        if key in original_arguments and key not in candidate_arguments:
            return False
    return True


def _repair_tool_arguments(
    *,
    mcp_id: str,
    tool_id: str,
    input_schema: dict[str, object],
    original_arguments: dict[str, object],
    candidate_arguments: dict[str, object],
) -> dict[str, object]:
    repaired = dict(candidate_arguments)
    properties = input_schema.get("properties") if isinstance(input_schema, dict) else None
    if not isinstance(properties, dict):
        properties = {}

    alias_map = {"q": "query", "search": "query"}
    for source_key, target_key in alias_map.items():
        if source_key in repaired and target_key not in repaired and target_key in properties:
            repaired[target_key] = repaired.pop(source_key)

    for key in _required_argument_keys(input_schema):
        if key not in repaired and key in original_arguments:
            repaired[key] = original_arguments[key]

    if mcp_id == "google_services" and tool_id == "gmail_get_message":
        if "message_id" in original_arguments and "message_id" not in repaired:
            repaired["message_id"] = original_arguments["message_id"]
        if "format" not in repaired and "format" in original_arguments:
            repaired["format"] = original_arguments["format"]

    if mcp_id == "scripts" and tool_id == "execute_script":
        if "title" in original_arguments:
            repaired["title"] = original_arguments["title"]
        original_input_json = original_arguments.get("input_json")
        candidate_input_json = repaired.get("input_json")
        if isinstance(original_input_json, dict):
            merged_input_json = dict(candidate_input_json) if isinstance(candidate_input_json, dict) else {}
            operation_value = original_input_json.get("operation")
            if operation_value not in (None, "") and "operation" not in merged_input_json:
                merged_input_json["operation"] = operation_value
            elif operation_value not in (None, "") and merged_input_json.get("operation") != operation_value:
                merged_input_json["operation"] = operation_value
            if merged_input_json:
                repaired["input_json"] = merged_input_json

    return repaired


def _required_argument_keys(input_schema: dict[str, object]) -> list[str]:
    required_raw = input_schema.get("required") if isinstance(input_schema, dict) else None
    if not isinstance(required_raw, list):
        return []
    return [item for item in required_raw if isinstance(item, str)]


def _build_tool_call_signature(mcp_id: str, tool_id: str, arguments: dict[str, object]) -> str:
    normalized_arguments = _normalize_tool_call_arguments(arguments)
    return f"{mcp_id}::{tool_id}::{normalized_arguments}"


def _normalize_tool_call_arguments(arguments: dict[str, object]) -> str:
    try:
        return json.dumps(arguments, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    except TypeError:
        return json.dumps(str(arguments), ensure_ascii=True)


def _build_tool_call_id(step_index: int, mcp_id: str, tool_id: str, attempt_number: int) -> str:
    safe_mcp_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", mcp_id).strip("_") or "mcp"
    safe_tool_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", tool_id).strip("_") or "tool"
    return f"step{step_index}-{safe_mcp_id}-{safe_tool_id}-a{attempt_number}"


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


def _validate_tool_arguments(input_schema: dict[str, object], arguments: dict[str, object]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    properties = input_schema.get("properties") if isinstance(input_schema, dict) else None
    if not isinstance(properties, dict):
        return errors

    for name, value in arguments.items():
        schema = properties.get(name)
        if not isinstance(schema, dict):
            continue
        errors.extend(_validate_schema_value(schema, value, path=name))
    return errors


def _validate_schema_value(schema: dict[str, object], value: object, *, path: str) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    expected_types = _schema_type_names(schema)
    if expected_types and not _matches_schema_types(expected_types, value):
        errors.append(
            {
                "field": path,
                "expected": "|".join(expected_types),
                "actual": _schema_value_type_name(value),
            }
        )
        return errors

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and enum_values and value not in enum_values:
        errors.append(
            {
                "field": path,
                "expected": "enum",
                "actual": _safe_json_dumps(value),
            }
        )
        return errors

    if isinstance(value, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for child_name, child_value in value.items():
                child_schema = properties.get(child_name)
                if isinstance(child_schema, dict):
                    errors.extend(_validate_schema_value(child_schema, child_value, path=f"{path}.{child_name}"))
        return errors

    if isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(_validate_schema_value(item_schema, item, path=f"{path}[{index}]"))
        return errors

    return errors


def _schema_type_names(schema: dict[str, object]) -> list[str]:
    raw_type = schema.get("type")
    if isinstance(raw_type, str):
        return [raw_type]
    if isinstance(raw_type, list):
        return [item for item in raw_type if isinstance(item, str)]
    return []


def _matches_schema_types(expected_types: list[str], value: object) -> bool:
    for expected in expected_types:
        if expected == "string" and isinstance(value, str):
            return True
        if expected == "boolean" and isinstance(value, bool):
            return True
        if expected == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if expected == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
        if expected == "object" and isinstance(value, dict):
            return True
        if expected == "array" and isinstance(value, list):
            return True
        if expected == "null" and value is None:
            return True
    return False


def _schema_value_type_name(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return type(value).__name__


def _looks_like_tool_avoidance_response(text: str) -> bool:
    return bool(_match_tool_avoidance_pattern(text))


def _match_tool_avoidance_pattern(text: str) -> str:
    normalized = (
        text.strip()
        .lower()
        .replace("’", "'")
        .replace("`", "'")
        .replace("ä", "a")
        .replace("ö", "o")
        .replace("ü", "u")
        .replace("ß", "ss")
    )
    if not normalized:
        return ""
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
        "no tools available",
        "tool is not available",
        "tools are not available",
        "browser tool is not available",
        "kein zugriff auf",
        "keinen zugriff auf",
        "habe keinen zugriff auf",
        "habe hier keinen zugriff",
        "kein browser-zugriff",
        "keinen browser-zugriff",
        "browser tool nicht verfugbar",
        "browser-tool nicht verfugbar",
        "tool nicht verfugbar",
        "tools nicht verfugbar",
        "keine tools verfugbar",
        "keine werkzeuge verfugbar",
        "nicht verfugbar",
    )
    for pattern in patterns:
        if pattern in normalized:
            logger.debug("Matched tool avoidance pattern=%r", pattern)
            return pattern
    return ""


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
    if isinstance(value, str):
        return _redact_sensitive_text(value)
    return value


def _is_sensitive_field_name(field_name: str) -> bool:
    lowered = field_name.strip().lower()
    return any(keyword in lowered for keyword in _SENSITIVE_FIELD_KEYWORDS)


def _redact_sensitive_text(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""

    redacted = text
    redacted = re.sub(
        r"(?i)\b(authorization)\b\s*[:=]\s*bearer\s+([^\s,;]+)",
        lambda match: f"{match.group(1)}: Bearer [REDACTED]",
        redacted,
    )
    redacted = re.sub(
        r"(?i)\b(api[_ -]?key|token|secret|password|private[_ -]?key|ssh[_ -]?private)\b\s*[:=]\s*([^\s,;]+)",
        lambda match: f"{match.group(1)}: [REDACTED]",
        redacted,
    )
    redacted = re.sub(r"\bsk-[A-Za-z0-9._-]{12,}\b", "[REDACTED]", redacted)
    return redacted


_PLANNER_RECENT_FULL_INTERACTIONS = 3


def _planner_interaction_context(interaction_log: list[dict[str, object]]) -> dict[str, object]:
    recent = interaction_log[-_MAX_PLANNER_INTERACTIONS:]
    if len(recent) <= _PLANNER_RECENT_FULL_INTERACTIONS:
        # Few enough interactions: send them all in full.
        return {
            "summary": _interaction_summary(interaction_log),
            "recent_interactions": recent,
        }

    # Keep the most recent interactions in full; slim older ones by
    # replacing verbose tool_result payloads with a brief summary.
    cutoff = len(recent) - _PLANNER_RECENT_FULL_INTERACTIONS
    slimmed: list[dict[str, object]] = []
    for idx, entry in enumerate(recent):
        if idx < cutoff and "tool_result" in entry:
            slim_entry = dict(entry)
            raw_result = entry["tool_result"]
            result_chars = len(_safe_json_dumps(raw_result))
            slim_entry["tool_result"] = {
                "slimmed": True,
                "original_chars": result_chars,
                "preview": _safe_json_dumps(raw_result)[:200],
            }
            slimmed.append(slim_entry)
        else:
            slimmed.append(entry)

    return {
        "summary": _interaction_summary(interaction_log),
        "recent_interactions": slimmed,
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
    compacted = _summarize_bulky_binary_fields(value)
    compacted = _limit_recursive_value(compacted, depth=0)
    serialized = _safe_json_dumps(compacted)
    if len(serialized) <= _MAX_TOOL_RESULT_CHARS:
        return compacted

    return {
        "truncated": True,
        "preview": serialized[:_MAX_TOOL_RESULT_CHARS],
        "original_chars": len(serialized),
    }


def _summarize_bulky_binary_fields(value: object) -> object:
    if isinstance(value, dict):
        summarized: dict[str, object] = {}
        for key, item in value.items():
            normalized_key = str(key)
            if normalized_key in _BULKY_BINARY_FIELD_NAMES and isinstance(item, str):
                summarized[normalized_key] = {
                    "omitted": True,
                    "reason": "binary_base64_removed_from_prompt",
                    "original_chars": len(item),
                }
                continue
            summarized[normalized_key] = _summarize_bulky_binary_fields(item)
        return summarized

    if isinstance(value, list):
        return [_summarize_bulky_binary_fields(item) for item in value]

    return value


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


_HARD_ERROR_SIGNALS = (
    "500",
    "502",
    "503",
    "504",
    "authentication failed",
    "auth failed",
    "unauthorized",
    "403",
    "unable to connect",
    "connection refused",
    "no valid connections",
    "timed out",
    "timeout",
    "internal server error",
    "server got itself in trouble",
    "network error",
    "name or service not known",
    "temporary failure in name resolution",
)


def _classify_tool_error(exc_detail: str) -> str:
    """Classify a tool exception as 'hard' (infrastructure/unavailable) or 'soft' (bad parameters).

    Hard errors indicate the external service is down or unreachable.
    Soft errors indicate the call was malformed and a different approach may succeed.
    """
    lowered = exc_detail.lower()
    if any(signal in lowered for signal in _HARD_ERROR_SIGNALS):
        return "hard"
    return "soft"


def _build_retry_hint(error_class: str, mcp_id: str, tool_id: str, attempt: int) -> str:
    """Return a human-readable instruction for the planner after a tool failure."""
    remaining = max(0, _MAX_RETRIES_PER_MCP_TOOL - attempt)
    if error_class == "hard":
        if remaining <= 0:
            return (
                f"HARD ERROR — {mcp_id}.{tool_id} is unavailable (attempt {attempt}/{_MAX_RETRIES_PER_MCP_TOOL}). "
                "No more retries will be allowed. "
                "Report to the user: what you tried, which service failed, and the exact error."
            )
        return (
            f"HARD ERROR — {mcp_id}.{tool_id} returned an infrastructure/service-unavailable error "
            f"(attempt {attempt}/{_MAX_RETRIES_PER_MCP_TOOL}, {remaining} remaining). "
            "Do NOT retry with the same approach. "
            "Consider whether an alternative tool can fulfil the request, otherwise report the failure to the user."
        )
    if remaining <= 0:
        return (
            f"SOFT ERROR — {mcp_id}.{tool_id} rejected the request due to invalid parameters "
            f"(attempt {attempt}/{_MAX_RETRIES_PER_MCP_TOOL}). "
            "No more retries will be allowed. "
            "Report to the user: what you tried, what parameters were used, and what the error was."
        )
    return (
        f"SOFT ERROR — {mcp_id}.{tool_id} rejected the request due to invalid parameters "
        f"(attempt {attempt}/{_MAX_RETRIES_PER_MCP_TOOL}, {remaining} remaining). "
        "Try a different approach: use corrected arguments, a different tool, "
        "or ask the user for clarification if the correct parameters are unknown."
    )
