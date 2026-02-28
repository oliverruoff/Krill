"""Timed jobs scheduler and dispatch helpers."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.chat_engine import generate_chat_response
from app.config import (
    ChatMessage,
    ChatSession,
    IntegrationConfig,
    Settings,
    TimedJob,
    get_timed_job,
    list_due_timed_jobs,
    load_settings,
    mark_timed_job_executed,
    save_settings,
)
from app.integrations.chat_runtime import build_model_history, ensure_runtime_context_seed
from app.memory_extraction import register_completed_turn, register_user_message_and_maybe_extract
from app.usage import add_daily_usage

from .integrations.telegram.client import telegram_send_message


TIMED_JOB_POLL_INTERVAL_SECONDS = 15
TELEGRAM_MAX_MESSAGE_LENGTH = 3500

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
    fallback = "Timed job"
    return fallback


def _chunk_telegram_text(text: str, max_len: int = TELEGRAM_MAX_MESSAGE_LENGTH) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, max_len)
        if split_at <= 0:
            split_at = remaining.rfind(" ", 0, max_len)
        if split_at <= 0:
            split_at = max_len
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].lstrip()
    return [chunk for chunk in chunks if chunk]


def _is_setup_ready(settings: Settings) -> bool:
    if not settings.setup_completed:
        return False
    provider_id = settings.active_provider_id.strip()
    if not provider_id:
        return False
    provider = settings.provider_configs.get(provider_id)
    if provider is None:
        return False
    if not provider.api_key.strip() or not provider.model.strip():
        return False
    return True


def _telegram_target(settings: Settings) -> tuple[str, int] | None:
    config = settings.integration_configs.get("telegram") or IntegrationConfig()
    if not config.enabled:
        return None
    token = str(config.params.get("bot_token", "")).strip()
    if not token:
        return None
    raw_chat_id = settings.telegram_state.owner_chat_id.strip()
    if not raw_chat_id:
        # Backward-compatible fallback: in private chats owner user id equals chat id.
        raw_chat_id = settings.telegram_state.owner_user_id.strip()
    if not raw_chat_id:
        return None
    try:
        chat_id = int(raw_chat_id)
    except ValueError:
        return None
    return token, chat_id


def get_timed_job_channel_options(settings: Settings) -> list[dict[str, object]]:
    telegram_target = _telegram_target(settings)
    telegram_description = "Sends job output to Telegram owner chat."
    if telegram_target is None:
        telegram_description = "Unavailable: enable Telegram, set bot token, and send one owner message first."
    return [
        {
            "id": "gateway",
            "label": "Gateway",
            "description": "Creates a hidden-input chat with assistant output in Gateway.",
            "available": True,
            "default": True,
        },
        {
            "id": "telegram",
            "label": "Telegram",
            "description": telegram_description,
            "available": telegram_target is not None,
            "default": False,
        },
    ]


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
    output_text = ""
    used_tokens: int | None = None
    used_tools: list[dict[str, str]] = []
    trace_messages: list[dict[str, str]] = []

    try:
        settings = await load_settings()
        if not _is_setup_ready(settings):
            output_text = "Timed job skipped: setup is not complete."
        else:
            prompt = job.prompt.strip()
            if not prompt:
                output_text = "Timed job skipped: prompt is empty."
            else:
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

                await register_user_message_and_maybe_extract(
                    source_channel="timed_job",
                    source_chat_id=job.id,
                )

                result, _ = await generate_chat_response(
                    settings=settings,
                    message=prompt,
                    history=model_history,
                    memory_block="",
                    source_channel="timed_job",
                    source_chat_id=job.id,
                )
                output_text = result["text"]
                used_tokens = result["used_tokens"]
                used_tools = [
                    {
                        "mcp_id": str(getattr(entry, "mcp_id", "") or ""),
                        "mcp_label": str(getattr(entry, "mcp_label", "") or ""),
                        "tool_id": str(getattr(entry, "tool_id", "") or ""),
                        "tool_label": str(getattr(entry, "tool_label", "") or ""),
                    }
                    for entry in result["used_mcp_tools"]
                ]
                trace_messages = [
                    {
                        "system_type": str(getattr(entry, "system_type", "orchestrator") or "orchestrator"),
                        "content": str(getattr(entry, "content", "") or ""),
                    }
                    for entry in result["system_trace_messages"]
                ]

        safe_output = output_text.strip() or "(No response text returned.)"
        channels = [channel for channel in job.channels if channel in {"gateway", "telegram"}]

        if "gateway" in channels:
            await _dispatch_gateway(
                job=job,
                assistant_text=safe_output,
                used_tokens=used_tokens,
                used_tools=used_tools,
                trace_messages=trace_messages,
                executed_at=executed_at,
            )

        if "telegram" in channels:
            await _dispatch_telegram(job=job, assistant_text=safe_output)

        await register_completed_turn(
            source_channel="timed_job",
            source_chat_id=job.id,
            user_message=job.prompt,
            assistant_message=safe_output,
        )
        if mark_as_executed:
            await mark_timed_job_executed(job.id, executed_at_utc=executed_at)
    except Exception as exc:
        if _is_transient_provider_error(exc):
            LOGGER.warning(
                "Timed job transient failure: %s",
                str(exc),
                extra={"timed_job_id": job.id},
            )
        else:
            LOGGER.exception("Timed job execution failed", extra={"timed_job_id": job.id})
        error_text = f"Timed job error: {exc}"
        channels = [channel for channel in job.channels if channel in {"gateway", "telegram"}]
        if "gateway" in channels:
            with contextlib.suppress(Exception):
                await _dispatch_gateway(
                    job=job,
                    assistant_text=error_text,
                    used_tokens=None,
                    used_tools=[],
                    trace_messages=[],
                    executed_at=executed_at,
                )
        if "telegram" in channels:
            with contextlib.suppress(Exception):
                await _dispatch_telegram(job=job, assistant_text=error_text)
        await register_completed_turn(
            source_channel="timed_job",
            source_chat_id=job.id,
            user_message=job.prompt,
            assistant_message=error_text,
        )


async def _dispatch_gateway(
    *,
    job: TimedJob,
    assistant_text: str,
    used_tokens: int | None,
    used_tools: list[dict[str, str]],
    trace_messages: list[dict[str, str]],
    executed_at: datetime,
) -> None:
    settings = await load_settings()
    timestamp = executed_at.isoformat()
    chat = ChatSession(
        id=str(uuid4()),
        title=_derive_chat_title(job),
        type="normal",
        messages=[],
        memory_block="",
        total_tokens_used=0,
        collapse_system_trace=True,
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


async def _dispatch_telegram(*, job: TimedJob, assistant_text: str) -> None:
    settings = await load_settings()
    telegram_target = _telegram_target(settings)
    if telegram_target is None:
        return
    token, chat_id = telegram_target
    title = _derive_chat_title(job)
    decorated = f"{title}\n\n{assistant_text}" if title else assistant_text
    for chunk in _chunk_telegram_text(decorated):
        await asyncio.to_thread(telegram_send_message, token, chat_id, chunk)


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
