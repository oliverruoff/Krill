"""Timed jobs scheduler and dispatch helpers."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

from app.chat_engine import generate_chat_response
from app.config import (
    ChatMessage,
    ChatSession,
    Settings,
    TimedJob,
    add_timed_job_auth_alert_provider_id,
    clear_timed_job_auth_alert_provider_id,
    get_timed_job_auth_alert_provider_ids,
    get_timed_job,
    list_due_timed_jobs,
    load_settings,
    mark_timed_job_executed,
    save_settings,
)
from app.integrations.chat_runtime import build_model_history, ensure_runtime_context_seed
from app.integrations.registry import get_runtime_integrations
from app.memory_extraction import register_completed_turn
from app.providers import get_provider
from app.providers.resilience import generate_with_retries
from app.usage import add_daily_usage


TIMED_JOB_POLL_INTERVAL_SECONDS = 15
TIMED_JOB_HIDDEN_CHAT_SYSTEM_TYPE = "timed_job_hidden_debug"
TIMED_JOB_OUTPUT_DECISION_TRACE_TYPE = "timed_job_output_decision"

_WORKER_TASK: asyncio.Task[None] | None = None
_STOP_EVENT = asyncio.Event()
_RUNNING_JOB_IDS: set[str] = set()
LOGGER = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _derive_chat_title(job: TimedJob) -> str:
    title = " ".join(job.title.split()).strip()
    if title:
        return title[:120]
    return "Timed job"


def _is_empty_provider_response_error(exc: Exception) -> bool:
    message = str(exc).strip().lower()
    if not message:
        return False
    return "empty response" in message


async def _dispatch_hidden_empty_output_debug(
    *,
    job: TimedJob,
    settings: Settings,
    executed_at: datetime,
) -> None:
    if "gateway" not in job.channels:
        return

    await _dispatch_gateway(
        job=job,
        assistant_text="(No response text returned.)",
        used_tokens=None,
        used_tools=[],
        trace_messages=[
            {
                "system_type": TIMED_JOB_OUTPUT_DECISION_TRACE_TYPE,
                "content": "Output suppressed: provider returned an empty response; no integration messages were sent.",
            }
        ],
        executed_at=executed_at,
        settings=settings,
        hidden_from_history=True,
    )


def _is_setup_ready(settings: Settings) -> bool:
    return bool(settings.setup_completed)


def _resolve_timed_job_provider_context(settings: Settings, job: TimedJob) -> tuple[str, str, str]:
    custom_provider_id = job.provider_id.strip().lower()
    provider_id = custom_provider_id or settings.active_provider_id.strip().lower()
    if not provider_id:
        raise RuntimeError("Timed job skipped: provider is not configured.")

    provider_config = settings.provider_configs.get(provider_id)
    if provider_config is None:
        raise RuntimeError(f"Timed job skipped: provider '{provider_id}' is not configured.")

    model_id = (job.model.strip() if custom_provider_id else "") or provider_config.model.strip()
    if not model_id:
        raise RuntimeError(f"Timed job skipped: model is not configured for provider '{provider_id}'.")

    api_key = provider_config.api_key.strip()
    if not api_key:
        raise RuntimeError(f"Timed job skipped: provider '{provider_id}' credentials are missing.")

    return provider_id, model_id, api_key


def get_timed_job_channel_options(settings: Settings) -> list[dict[str, object]]:
    """Return the list of available dispatch channels for the timed job UI.

    Gateway is a built-in channel. All registered integrations are queried
    for their optional timed job channel option.
    """
    options: list[dict[str, object]] = [
        {
            "id": "gateway",
            "label": "Gateway",
            "description": "Creates a hidden-input chat with assistant output in Gateway.",
            "available": True,
            "default": True,
        },
    ]
    for plugin in get_runtime_integrations():
        option = plugin.get_timed_job_channel_option(settings)
        if option is not None:
            options.append(option)
    return options


async def start_timed_jobs_worker() -> None:
    global _WORKER_TASK
    if _WORKER_TASK is not None and not _WORKER_TASK.done():
        return
    _STOP_EVENT.clear()
    _WORKER_TASK = asyncio.create_task(_timed_jobs_loop())


async def stop_timed_jobs_worker() -> None:
    global _WORKER_TASK
    _STOP_EVENT.set()
    if _WORKER_TASK is None:
        return
    _WORKER_TASK.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _WORKER_TASK
    _WORKER_TASK = None


async def _timed_jobs_loop() -> None:
    while not _STOP_EVENT.is_set():
        try:
            await run_due_timed_jobs_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(TIMED_JOB_POLL_INTERVAL_SECONDS)


async def run_due_timed_jobs_once() -> None:
    due_jobs = await list_due_timed_jobs(limit=20)
    if not due_jobs:
        return

    for job in due_jobs:
        if job.id in _RUNNING_JOB_IDS:
            continue
        _RUNNING_JOB_IDS.add(job.id)
        try:
            await _execute_timed_job(job, mark_as_executed=True)
        finally:
            _RUNNING_JOB_IDS.discard(job.id)


async def trigger_timed_job_now(timed_job_id: str) -> bool:
    job = await get_timed_job(timed_job_id)
    if job is None:
        return False
    if job.id in _RUNNING_JOB_IDS:
        return True
    _RUNNING_JOB_IDS.add(job.id)
    try:
        await _execute_timed_job(job, mark_as_executed=False)
    finally:
        _RUNNING_JOB_IDS.discard(job.id)
    return True


async def _execute_timed_job(job: TimedJob, *, mark_as_executed: bool) -> None:
    executed_at = datetime.now(timezone.utc)
    settings = Settings()
    output_text = ""
    used_tokens: int | None = None
    used_tools: list[dict[str, str]] = []
    trace_messages: list[dict[str, str]] = []
    provider_id = ""
    provider_model = ""
    provider_api_key = ""
    generated_assistant_output = False

    try:
        settings = await load_settings()
        if not _is_setup_ready(settings):
            output_text = "Timed job skipped: setup is not complete."
        else:
            prompt = job.prompt.strip()
            if not prompt:
                output_text = "Timed job skipped: prompt is empty."
            else:
                try:
                    provider_id, provider_model, provider_api_key = _resolve_timed_job_provider_context(settings, job)
                except RuntimeError as exc:
                    output_text = str(exc)
                    provider_id = ""

                if not output_text:
                    scratch_chat = ChatSession(
                        id=str(uuid4()),
                        title=_derive_chat_title(job),
                        type="normal",
                        messages=[],
                        memory_block="",
                        total_tokens_used=0,
                        collapse_system_trace=True,
                    )
                    ensure_runtime_context_seed(scratch_chat, settings)
                    model_history = build_model_history(scratch_chat)

                    result, _ = await generate_chat_response(
                        settings=settings,
                        message=prompt,
                        history=model_history,
                        memory_block="",
                        provider_id=provider_id,
                        model=provider_model,
                        api_key=provider_api_key,
                        source_channel="timed_job",
                        source_chat_id=job.id,
                    )
                    output_text = result["text"]
                    used_tokens = result["used_tokens"]
                    generated_assistant_output = True
                    used_tools = [
                        {
                            "mcp_id": str(entry.get("mcp_id", "") if isinstance(entry, dict) else ""),
                            "mcp_label": str(entry.get("mcp_label", "") if isinstance(entry, dict) else ""),
                            "tool_id": str(entry.get("tool_id", "") if isinstance(entry, dict) else ""),
                            "tool_label": str(entry.get("tool_label", "") if isinstance(entry, dict) else ""),
                        }
                        for entry in result["used_mcp_tools"]
                    ]
                    trace_messages = [
                        {
                            "system_type": str(
                                entry.get("system_type", "orchestrator") if isinstance(entry, dict) else "orchestrator"
                            ),
                            "content": str(entry.get("content", "") if isinstance(entry, dict) else ""),
                        }
                        for entry in result["system_trace_messages"]
                    ]

                    if provider_id:
                        await clear_timed_job_auth_alert_provider_id(provider_id)

        safe_output = output_text.strip() or "(No response text returned.)"
        should_dispatch = True
        if job.output_decision_enabled and generated_assistant_output:
            should_dispatch, decision_trace = await _should_dispatch_timed_job_output(
                job=job,
                assistant_output=safe_output,
                provider_id=provider_id,
                model=provider_model,
                api_key=provider_api_key,
            )
            trace_messages.append(decision_trace)

        if should_dispatch:
            await _dispatch_all(
                job=job,
                safe_output=safe_output,
                used_tokens=used_tokens,
                used_tools=used_tools,
                trace_messages=trace_messages,
                executed_at=executed_at,
            )
        else:
            await _dispatch_gateway(
                job=job,
                assistant_text=safe_output,
                used_tokens=used_tokens,
                used_tools=used_tools,
                trace_messages=trace_messages,
                executed_at=executed_at,
                settings=settings,
                hidden_from_history=True,
            )

        await register_completed_turn(
            source_channel="timed_job",
            source_chat_id=job.id,
            user_message=job.prompt,
            assistant_message=safe_output,
        )
        if mark_as_executed:
            await mark_timed_job_executed(job.id, executed_at_utc=executed_at)
    except Exception as exc:
        if job.output_decision_enabled and _is_empty_provider_response_error(exc):
            LOGGER.info(
                "Timed job produced no output; suppressing all channel dispatch",
                extra={"timed_job_id": job.id, "provider_id": provider_id},
            )
            with contextlib.suppress(Exception):
                await _dispatch_hidden_empty_output_debug(
                    job=job,
                    settings=settings,
                    executed_at=executed_at,
                )
            if mark_as_executed:
                with contextlib.suppress(Exception):
                    await mark_timed_job_executed(job.id, executed_at_utc=executed_at)
            return

        is_auth_failure = _is_auth_provider_error(exc)
        if is_auth_failure:
            LOGGER.warning(
                "Timed job provider auth failure: %s",
                str(exc),
                extra={"timed_job_id": job.id, "provider_id": provider_id},
            )
        elif _is_transient_provider_error(exc):
            LOGGER.warning(
                "Timed job transient failure: %s",
                str(exc),
                extra={"timed_job_id": job.id},
            )
        else:
            LOGGER.exception("Timed job execution failed", extra={"timed_job_id": job.id})
        notify_failure = True
        error_text = f"Timed job error: {exc}"
        if is_auth_failure:
            provider_label = provider_id or "current provider"
            active_provider_ids = await get_timed_job_auth_alert_provider_ids() if provider_id else []
            if provider_id and provider_id in active_provider_ids:
                notify_failure = False
                LOGGER.warning(
                    "Timed job auth failure notification suppressed; reconnect required",
                    extra={"timed_job_id": job.id, "provider_id": provider_id},
                )
            else:
                if provider_id:
                    await add_timed_job_auth_alert_provider_id(provider_id)
                error_text = (
                    f"Timed job paused: provider authentication expired for '{provider_label}'. "
                    "Reconnect this provider in Setup, then timed jobs will continue normally."
                )

        if notify_failure:
            with contextlib.suppress(Exception):
                await _dispatch_all(
                    job=job,
                    safe_output=error_text,
                    used_tokens=None,
                    used_tools=[],
                    trace_messages=[],
                    executed_at=executed_at,
                )
            await register_completed_turn(
                source_channel="timed_job",
                source_chat_id=job.id,
                user_message=job.prompt,
                assistant_message=error_text,
            )

        if mark_as_executed:
            with contextlib.suppress(Exception):
                await mark_timed_job_executed(job.id, executed_at_utc=executed_at)


async def _dispatch_all(
    *,
    job: TimedJob,
    safe_output: str,
    used_tokens: int | None,
    used_tools: list[dict[str, str]],
    trace_messages: list[dict[str, str]],
    executed_at: datetime,
    hidden_from_history: bool = False,
) -> None:
    """Fan out job results to all requested channels."""
    settings = await load_settings()

    if "gateway" in job.channels:
        await _dispatch_gateway(
            job=job,
            assistant_text=safe_output,
            used_tokens=used_tokens,
            used_tools=used_tools,
            trace_messages=trace_messages,
            executed_at=executed_at,
            settings=settings,
        )

    for plugin in get_runtime_integrations():
        if plugin.integration_id in job.channels:
            with contextlib.suppress(Exception):
                await plugin.dispatch_timed_job(job, safe_output, settings, hidden=hidden_from_history)


async def _dispatch_gateway(
    *,
    job: TimedJob,
    assistant_text: str,
    used_tokens: int | None,
    used_tools: list[dict[str, str]],
    trace_messages: list[dict[str, str]],
    executed_at: datetime,
    settings: Settings,
    hidden_from_history: bool = False,
) -> None:
    timestamp = executed_at.isoformat()
    chat_title = _derive_chat_title(job)
    if hidden_from_history:
        chat_title = f"[Hidden] {chat_title}"[:120]
    chat = ChatSession(
        id=str(uuid4()),
        title=chat_title,
        type="normal",
        messages=[],
        memory_block="",
        total_tokens_used=0,
        collapse_system_trace=True,
        hidden_from_history=hidden_from_history,
    )
    ensure_runtime_context_seed(chat, settings)

    for trace in trace_messages:
        content = str(trace.get("content", "")).strip()
        if not content:
            continue
        chat.messages.append(
            ChatMessage(
                role="system",
                content=content,
                timestamp=timestamp,
                system_type=str(trace.get("system_type", "orchestrator")),
                tool_usage=[],
                request_id="",
                status="",
            )
        )

    chat.messages.append(
        ChatMessage(
            role="assistant",
            content=assistant_text,
            timestamp=timestamp,
            tool_usage=[
                {
                    "mcp_id": str(entry.get("mcp_id", "")),
                    "mcp_label": str(entry.get("mcp_label", "")),
                    "tool_id": str(entry.get("tool_id", "")),
                    "tool_label": str(entry.get("tool_label", "")),
                }
                for entry in used_tools
            ],
            request_id="",
            status="done",
        )
    )

    if isinstance(used_tokens, int) and used_tokens > 0:
        chat.total_tokens_used = used_tokens
        add_daily_usage(settings, used_tokens)

    settings.chats.insert(0, chat)
    await save_settings(settings)


def _is_transient_provider_error(exc: Exception) -> bool:
    message = str(exc).strip().lower()
    if not message:
        return False
    return any(
        marker in message
        for marker in (
            "network timeout",
            "timed out",
            "timeout",
            "network error",
            "temporarily unavailable",
            "service unavailable",
            "too many requests",
            "rate limit",
            "unexpected error while contacting",
        )
    )


def _is_auth_provider_error(exc: Exception) -> bool:
    message = str(exc).strip().lower()
    if not message:
        return False
    return any(
        marker in message
        for marker in (
            "reconnect your openai account",
            "reconnect gemini oauth",
            "oauth token was rejected",
            "oauth refresh token was rejected",
            "credentials are invalid",
            "authentication",
            "unauthorized",
            "forbidden",
            "(401)",
            "(403)",
            " 401",
            " 403",
            "invalid api key",
            "api key is required",
        )
    )


async def get_timed_job_auth_alert_provider_ids_for_status() -> list[str]:
    """Return provider ids currently in auth-expired suppression state."""
    return await get_timed_job_auth_alert_provider_ids()


async def _should_dispatch_timed_job_output(
    *,
    job: TimedJob,
    assistant_output: str,
    provider_id: str,
    model: str,
    api_key: str,
) -> tuple[bool, dict[str, str]]:
    if not provider_id or not model or not api_key:
        return True, {
            "system_type": TIMED_JOB_OUTPUT_DECISION_TRACE_TYPE,
            "content": "Output decision fallback: provider context unavailable; dispatching output.",
        }

    provider = get_provider(provider_id)
    if provider is None:
        return True, {
            "system_type": TIMED_JOB_OUTPUT_DECISION_TRACE_TYPE,
            "content": "Output decision fallback: provider implementation unavailable; dispatching output.",
        }

    try:
        decision_text, _ = await generate_with_retries(
            provider=provider,
            prompt=_build_output_decision_prompt(job.prompt, assistant_output),
            system_prompt=(
                "You are a strict JSON classifier for timed-job notification policy. "
                "Return only JSON."
            ),
            model=model,
            api_key=api_key,
            history=[],
            max_attempts=2,
        )
        should_output, reason, confidence = _parse_output_decision(decision_text)
        decision_label = "dispatching" if should_output else "suppressing"
        return should_output, {
            "system_type": TIMED_JOB_OUTPUT_DECISION_TRACE_TYPE,
            "content": (
                f"Output decision: {decision_label} output "
                f"(confidence: {confidence}; reason: {reason})."
            ),
        }
    except Exception as exc:
        return True, {
            "system_type": TIMED_JOB_OUTPUT_DECISION_TRACE_TYPE,
            "content": f"Output decision fallback after error ({exc}); dispatching output.",
        }


def _build_output_decision_prompt(user_prompt: str, assistant_output: str) -> str:
    return (
        "Decide whether a timed-job run should notify the user now.\n\n"
        "User timed-job prompt:\n"
        f"{user_prompt.strip()}\n\n"
        "Generated result:\n"
        f"{assistant_output.strip()}\n\n"
        "Rules:\n"
        "1) If the prompt implies only notable/critical/changed conditions should notify, "
        "set should_output=false when result is routine, empty, or no-action.\n"
        "2) If in doubt, set should_output=true.\n"
        "3) If result indicates failure, auth issues, or operational risk, set should_output=true.\n\n"
        "Return JSON only with this shape:\n"
        "{\"should_output\": true|false, \"reason\": \"...\", \"confidence\": \"low|medium|high\"}"
    )


def _parse_output_decision(raw_text: str) -> tuple[bool, str, str]:
    text = str(raw_text or "").strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()

    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Output decision response was not a JSON object.")

    should_output = bool(parsed.get("should_output", True))
    reason = str(parsed.get("reason", "No reason provided.")).strip() or "No reason provided."
    confidence = str(parsed.get("confidence", "medium")).strip().lower()
    if confidence not in {"low", "medium", "high"}:
        confidence = "medium"
    return should_output, reason[:300], confidence
