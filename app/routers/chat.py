"""Chat routes: state management, gateway queue, SSE streaming, and compaction."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..chat_engine import generate_chat_response
from ..config import (
    ChatMessage,
    ChatSession,
    DailyTokenUsage,
    Settings,
    load_chat_state,
    load_settings,
    save_chat_state,
    update_chat_title,
)
from ..debug_dumps import create_hidden_debug_chat, is_debug_command
from ..integrations.chat_runtime import ensure_runtime_context_seed
from ..tooling.execution import ExecutionEvent, cancel_registered_executions
from ..memory_extraction import register_completed_turn, register_user_message_and_maybe_extract
from ..providers import get_provider
from ..providers.resilience import generate_with_retries
from ..providers.vision import analyze_image
from ..usage import add_daily_usage
from .helpers import _is_setup_complete

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ChatTurn(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1, max_length=5000)


class ChatRequest(BaseModel):
    message: str = Field(default="", max_length=5000)
    history: list[ChatTurn] = Field(default_factory=list)
    memory_block: str = Field(default="", max_length=8000)
    provider_id: str = ""
    model: str = ""
    api_key: str = ""
    bot_name: str = Field(default="", max_length=30)
    system_prompt: str = Field(default="", max_length=1000)
    source_channel: str = "gateway"
    source_chat_id: str = ""
    source_request_id: str = ""
    image: dict[str, str] | None = None


class ChatEnqueueRequest(BaseModel):
    chat_id: str = Field(min_length=1)
    message: str = Field(default="", max_length=5000)
    client_enqueue_id: str = Field(default="", max_length=120)
    provider_id: str = ""
    model: str = ""
    api_key: str = ""
    bot_name: str = Field(default="", max_length=30)
    system_prompt: str = Field(default="", max_length=1000)
    image: dict[str, str] | None = None


class ChatStopRequest(BaseModel):
    chat_id: str = Field(min_length=1)


class ChatDebugRequest(BaseModel):
    chat_id: str = Field(min_length=1)
    chat: ChatSession


class CompactChatRequest(BaseModel):
    history: list[ChatTurn] = Field(default_factory=list)
    target_token_limit: int = Field(default=0, ge=0)
    memory_block: str = Field(default="", max_length=8000)


class CompactChatResponse(BaseModel):
    memory_block: str
    history: list[ChatTurn]
    used_tokens: int | None = None


class ChatStateResponse(BaseModel):
    chats: list[dict[str, object]]
    active_chat_id: str
    daily_token_usage: list[dict[str, object]]


class ChatStateWriteRequest(BaseModel):
    chats: list[ChatSession] = Field(default_factory=list)
    active_chat_id: str = ""
    daily_token_usage: list[DailyTokenUsage] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Gateway queue global state
# ---------------------------------------------------------------------------

_gateway_chat_lock = asyncio.Lock()
_gateway_chat_queues: dict[str, list[dict[str, Any]]] = {}
_gateway_chat_tasks: dict[str, asyncio.Task[None]] = {}
_gateway_chat_active_request_ids: dict[str, str] = {}
_gateway_chat_user_cancelled_request_ids: set[str] = set()
_gateway_chat_client_enqueue_ids: dict[str, dict[str, tuple[str, float]]] = {}
_GATEWAY_CHAT_CLIENT_ENQUEUE_TTL_SECONDS = 600.0


def _derive_chat_title(first_message: str, max_len: int = 24) -> str:
    normalized = " ".join(str(first_message or "").split()).strip()
    if not normalized:
        return "New chat"
    if len(normalized) <= max_len:
        return normalized
    return f"{normalized[:max_len].rstrip()}..."


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/api/chat/state", response_model=ChatStateResponse)
async def get_chat_state() -> ChatStateResponse:
    settings = await load_chat_state()
    return ChatStateResponse(
        chats=[chat.model_dump() for chat in settings.chats],
        active_chat_id=settings.active_chat_id,
        daily_token_usage=[entry.model_dump() for entry in settings.daily_token_usage],
    )


@router.post("/api/chat/state", response_model=ChatStateResponse)
async def update_chat_state(payload: ChatStateWriteRequest) -> ChatStateResponse:
    persisted = await save_chat_state(payload.chats, payload.active_chat_id, payload.daily_token_usage)
    return ChatStateResponse(
        chats=[chat.model_dump() for chat in persisted.chats],
        active_chat_id=persisted.active_chat_id,
        daily_token_usage=[entry.model_dump() for entry in persisted.daily_token_usage],
    )


@router.post("/api/chat/enqueue")
async def enqueue_chat(payload: ChatEnqueueRequest) -> dict[str, object]:
    settings = await load_settings()
    chat_id = payload.chat_id.strip()
    target_chat = next((chat for chat in settings.chats if chat.id == chat_id), None)
    if target_chat is None:
        raise HTTPException(status_code=404, detail="Chat not found.")

    message_text = payload.message.strip()
    image_payload = _normalize_enqueued_image(payload.image)
    if is_debug_command(message_text) and image_payload is None:
        result = await create_hidden_debug_chat(
            snapshot_chat=target_chat.model_copy(deep=True),
            source_channel="gateway",
            settings=settings,
            triggered_by="gateway_enqueue_command",
        )
        raw_file_info = result.get("file_info") if isinstance(result, dict) else None
        file_info = raw_file_info if isinstance(raw_file_info, dict) else {}
        debug_chat = result["debug_chat"] if isinstance(result, dict) else None
        return {
            "ok": True,
            "debug_command": True,
            "detail": "Debug dump created.",
            "debug_chat_id": debug_chat.id if isinstance(debug_chat, ChatSession) else "",
            "download_url": str(file_info.get("download_url", "")),
        }

    if not _is_setup_complete(settings):
        raise HTTPException(status_code=422, detail="Setup is not complete.")

    if not message_text and image_payload is None:
        raise HTTPException(status_code=422, detail="Either message text or one image is required.")

    user_content = message_text
    if image_payload is not None:
        if user_content:
            user_content = f"{user_content}\n\n[Image attached]"
        else:
            user_content = "[Image attached]"

    existing_user_messages = [message for message in target_chat.messages if message.role == "user" and message.content.strip()]
    if not existing_user_messages and target_chat.title.strip().lower() == "new chat":
        target_chat.title = _derive_chat_title(user_content)

    client_enqueue_id = payload.client_enqueue_id.strip()
    if client_enqueue_id:
        async with _gateway_chat_lock:
            _prune_gateway_client_enqueue_ids(chat_id)
            existing = _gateway_chat_client_enqueue_ids.get(chat_id, {}).get(client_enqueue_id)
            if existing is not None:
                return {"ok": True, "request_id": existing[0], "duplicate": True}

    request_id = str(uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    if client_enqueue_id:
        async with _gateway_chat_lock:
            _prune_gateway_client_enqueue_ids(chat_id)
            chat_entries = _gateway_chat_client_enqueue_ids.setdefault(chat_id, {})
            existing = chat_entries.get(client_enqueue_id)
            if existing is not None:
                return {"ok": True, "request_id": existing[0], "duplicate": True}
            chat_entries[client_enqueue_id] = (request_id, time.time())
    ensure_runtime_context_seed(target_chat, settings)
    target_chat.messages.append(ChatMessage(role="user", content=user_content, timestamp=now_iso))
    target_chat.messages.append(
        ChatMessage(role="assistant", content="", timestamp=now_iso, request_id=request_id, status="queued")
    )

    try:
        await save_chat_state(settings.chats, settings.active_chat_id, settings.daily_token_usage, preserve_active_chat_id=True)
    except Exception:
        if client_enqueue_id:
            async with _gateway_chat_lock:
                entries = _gateway_chat_client_enqueue_ids.get(chat_id)
                if entries is not None and entries.get(client_enqueue_id, ("", 0.0))[0] == request_id:
                    entries.pop(client_enqueue_id, None)
                    if not entries:
                        _gateway_chat_client_enqueue_ids.pop(chat_id, None)
        raise

    try:
        await register_user_message_and_maybe_extract(source_channel="gateway", source_chat_id=chat_id)
    except Exception:
        pass

    await _enqueue_gateway_chat_job(
        {
            "chat_id": chat_id,
            "request_id": request_id,
            "message": message_text,
            "image": image_payload,
            "provider_id": payload.provider_id.strip(),
            "model": payload.model.strip(),
            "api_key": payload.api_key,
            "bot_name": payload.bot_name,
            "system_prompt": payload.system_prompt,
        }
    )
    return {"ok": True, "request_id": request_id}


@router.post("/api/chat/debug")
async def debug_chat(payload: ChatDebugRequest) -> dict[str, object]:
    chat_id = payload.chat_id.strip()
    if payload.chat.id != chat_id:
        raise HTTPException(status_code=422, detail="Chat payload does not match chat_id.")

    settings = await load_settings()
    result = await create_hidden_debug_chat(
        snapshot_chat=payload.chat,
        source_channel="gateway",
        settings=settings,
        triggered_by="gateway_command",
    )
    raw_file_info = result.get("file_info") if isinstance(result, dict) else None
    file_info = raw_file_info if isinstance(raw_file_info, dict) else {}
    debug_chat = result["debug_chat"] if isinstance(result, dict) else None
    return {
        "ok": True,
        "detail": "Debug dump created.",
        "debug_chat_id": debug_chat.id if isinstance(debug_chat, ChatSession) else "",
        "debug_chat_title": debug_chat.title if isinstance(debug_chat, ChatSession) else "",
        "download_url": str(file_info.get("download_url", "")),
        "file_path": str(file_info.get("path", "")),
    }


@router.post("/api/chat/stop")
async def stop_chat(payload: ChatStopRequest) -> dict[str, object]:
    chat_id = payload.chat_id.strip()
    cancelled = await _stop_gateway_chat(chat_id)
    return {"ok": True, "cancelled": cancelled}


@router.post("/api/chat/stream")
async def chat_stream(payload: ChatRequest) -> StreamingResponse:
    settings = await load_settings()
    if not _is_setup_complete(settings):
        raise HTTPException(status_code=422, detail="Setup is not complete.")
    try:
        await register_user_message_and_maybe_extract(
            source_channel=payload.source_channel,
            source_chat_id=payload.source_chat_id,
        )
    except Exception:
        # Memory extraction triggering must not block chat.
        pass

    # Resolve image attachment: analyse it first and inject result into message.
    image_payload = _normalize_enqueued_image(payload.image)
    stream_message = payload.message.strip()
    image_analysis_tokens: int = 0

    if image_payload is not None:
        image_mime = str(image_payload.get("mime_type", "")).strip()
        image_bytes_raw = image_payload.get("content_bytes")
        if not image_mime.startswith("image/") or not isinstance(image_bytes_raw, (bytes, bytearray)):
            async def _bad_image_stream():
                yield _sse("error", {"detail": "Invalid image payload."})
            return StreamingResponse(_bad_image_stream(), media_type="text/event-stream")
        try:
            resolved_provider_id = payload.provider_id or settings.active_provider_id
            resolved_provider_config = settings.provider_configs.get(resolved_provider_id)
            resolved_model = payload.model or (resolved_provider_config.model if resolved_provider_config else "")
            resolved_api_key = payload.api_key or (resolved_provider_config.api_key if resolved_provider_config else "")
            image_analysis_text, _img_tokens = await analyze_image(
                provider_id=resolved_provider_id,
                model=resolved_model,
                api_key=resolved_api_key,
                image_bytes=bytes(image_bytes_raw),
                mime_type=image_mime,
                prompt=_image_analysis_prompt(stream_message),
            )
            image_analysis_tokens = _img_tokens if isinstance(_img_tokens, int) else 0
            analysis_block = image_analysis_text.strip()
            if stream_message:
                stream_message = f"{stream_message}\n\nImage analysis:\n{analysis_block}"
            else:
                stream_message = (
                    "The user sent an image without text. Use this image analysis to respond helpfully:\n"
                    f"{analysis_block}"
                )
        except Exception as exc:
            async def _img_err_stream():
                yield _sse("error", {"detail": f"Image analysis failed: {exc}"})
            return StreamingResponse(_img_err_stream(), media_type="text/event-stream")

    if not stream_message:
        async def _empty_stream():
            yield _sse("error", {"detail": "Either message text or one image is required."})
        return StreamingResponse(_empty_stream(), media_type="text/event-stream")

    history = [turn.model_dump() for turn in payload.history]

    async def event_stream():
        try:
            queue: asyncio.Queue[str | None] = asyncio.Queue()
            orchestration_holder: dict[str, object] = {}

            async def _emit_tool_step(step: object) -> None:
                if not isinstance(step, dict):
                    return
                event_type = str(step.get("event_type", "")).strip()
                message = str(step.get("message", "")).strip()
                if not event_type or not message:
                    return
                event_payload = {str(key): value for key, value in step.items()}
                event_payload["content"] = message
                event_payload["system_type"] = f"execution_{event_type}"
                await queue.put(_sse("progress", event_payload))

            async def run_orchestration() -> None:
                try:
                    orchestration_holder["result"] = await generate_chat_response(
                        settings=settings,
                        message=stream_message,
                        history=history,
                        memory_block=payload.memory_block,
                        provider_id=payload.provider_id,
                        model=payload.model,
                        api_key=payload.api_key,
                        bot_name=payload.bot_name,
                        system_prompt=payload.system_prompt,
                        source_channel=payload.source_channel,
                        source_chat_id=payload.source_chat_id,
                        source_request_id=payload.source_request_id,
                        on_execution_event=_emit_tool_step,
                    )
                except Exception as exc:
                    orchestration_holder["error"] = exc
                finally:
                    await queue.put(None)

            orchestration_task = asyncio.create_task(run_orchestration())

            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item

            await orchestration_task

            if "error" in orchestration_holder:
                yield _sse("error", {"detail": str(orchestration_holder["error"])})
                return

            orchestration_payload = orchestration_holder.get("result")
            if not (isinstance(orchestration_payload, tuple) and len(orchestration_payload) == 2):
                yield _sse("error", {"detail": "Missing orchestration result."})
                return

            orchestration, token_limit = orchestration_payload
            if not isinstance(orchestration, dict):
                yield _sse("error", {"detail": "Invalid orchestration payload."})
                return

            text = str(orchestration.get("text", ""))
            used_tokens = orchestration.get("used_tokens")
            used_mcp_tools = orchestration.get("used_mcp_tools", [])
            system_trace_messages = orchestration.get("system_trace_messages", [])
            execution_events = orchestration.get("execution_events", [])

            used_value = (used_tokens if isinstance(used_tokens, int) else 0) + image_analysis_tokens
            used_percent = round((used_value / token_limit) * 100, 2) if token_limit else 0
            yield _sse(
                "meta",
                {
                    "used_tokens": used_value,
                    "token_limit": token_limit,
                    "used_percent": used_percent,
                    "used_mcp_tools": used_mcp_tools,
                    "system_trace_messages": system_trace_messages,
                    "execution_events": execution_events,
                },
            )

            for chunk in _chunk_text(str(text)):
                yield _sse("token", {"text": chunk})
                await asyncio.sleep(0.01)

            yield _sse("done", {"ok": True})
        except Exception as exc:
            logger.exception("Unhandled chat stream error")
            yield _sse("error", {"detail": f"Chat stream failed: {exc}"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/api/chat/compact", response_model=CompactChatResponse)
async def compact_chat(payload: CompactChatRequest) -> CompactChatResponse:
    settings = await load_settings()
    if not _is_setup_complete(settings):
        raise HTTPException(status_code=422, detail="Setup is not complete.")

    active_provider_id = settings.active_provider_id
    provider_config = settings.provider_configs.get(active_provider_id)
    if provider_config is None:
        raise HTTPException(status_code=422, detail="Active provider is not configured.")

    provider = get_provider(active_provider_id)
    if provider is None:
        raise HTTPException(status_code=422, detail="Active provider is unavailable.")

    incoming_history = [turn.model_dump() for turn in payload.history]
    if not incoming_history and not payload.memory_block.strip():
        return CompactChatResponse(memory_block="", history=[])

    try:
        compacted_text, used_tokens = await generate_with_retries(
            provider=provider,
            prompt=_build_compaction_prompt(payload.memory_block, payload.target_token_limit),
            system_prompt=_compaction_system_prompt(),
            model=provider_config.model,
            api_key=provider_config.api_key,
            history=incoming_history,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Compaction failed: {exc}") from exc

    memory_block = compacted_text.strip()
    if not memory_block:
        raise HTTPException(status_code=422, detail="Compaction failed: Provider returned empty compact memory.")

    return CompactChatResponse(memory_block=memory_block, history=[], used_tokens=used_tokens)


# ---------------------------------------------------------------------------
# Gateway queue internals
# ---------------------------------------------------------------------------

def _prune_gateway_client_enqueue_ids(chat_id: str) -> None:
    entries = _gateway_chat_client_enqueue_ids.get(chat_id)
    if not entries:
        _gateway_chat_client_enqueue_ids.pop(chat_id, None)
        return
    cutoff = time.time() - _GATEWAY_CHAT_CLIENT_ENQUEUE_TTL_SECONDS
    stale_keys = [client_id for client_id, (_, created_at) in entries.items() if created_at < cutoff]
    for client_id in stale_keys:
        entries.pop(client_id, None)
    if not entries:
        _gateway_chat_client_enqueue_ids.pop(chat_id, None)


async def _enqueue_gateway_chat_job(job: dict[str, Any]) -> None:
    chat_id = str(job.get("chat_id", "")).strip()
    if not chat_id:
        return
    async with _gateway_chat_lock:
        queue = _gateway_chat_queues.setdefault(chat_id, [])
        queue.append(job)
        task = _gateway_chat_tasks.get(chat_id)
        if task is None or task.done():
            _gateway_chat_tasks[chat_id] = asyncio.create_task(_process_gateway_chat_queue(chat_id))


async def _process_gateway_chat_queue(chat_id: str) -> None:
    try:
        while True:
            async with _gateway_chat_lock:
                queue = _gateway_chat_queues.get(chat_id, [])
                if not queue:
                    _gateway_chat_queues.pop(chat_id, None)
                    _gateway_chat_tasks.pop(chat_id, None)
                    _gateway_chat_active_request_ids.pop(chat_id, None)
                    return
                job = queue.pop(0)
                _gateway_chat_active_request_ids[chat_id] = str(job.get("request_id", "")).strip()
            await _process_gateway_chat_job(chat_id, job)
            async with _gateway_chat_lock:
                _gateway_chat_active_request_ids.pop(chat_id, None)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Gateway chat queue worker failed", extra={"chat_id": chat_id})
    finally:
        async with _gateway_chat_lock:
            if _gateway_chat_tasks.get(chat_id) is asyncio.current_task():
                _gateway_chat_tasks.pop(chat_id, None)
            _gateway_chat_active_request_ids.pop(chat_id, None)


async def _generate_and_save_chat_title(
    chat_id: str,
    first_user_message: str,
    provider_id: str,
    model: str,
    api_key: str,
) -> None:
    """Ask the LLM for a short chat title and persist it. Fire-and-forget background task."""
    try:
        provider = get_provider(provider_id)
        if provider is None:
            return
        prompt = (
            "Write a short 3-5 word title for a chat that starts with this message. "
            "Reply with only the title, no quotes, no punctuation at the end:\n\n"
            f"{first_user_message[:300]}"
        )
        text, _ = await generate_with_retries(
            provider=provider,
            prompt=prompt,
            system_prompt="",
            model=model,
            api_key=api_key,
            history=[],
        )
        title = text.strip().strip("\"'").strip()
        if not title:
            return
        if len(title) > 60:
            title = title[:60].rsplit(" ", 1)[0].strip()
        await update_chat_title(chat_id, title)
    except Exception:
        pass  # Silently ignore — the truncated first-message title stays as fallback


async def _process_gateway_chat_job(chat_id: str, job: dict[str, Any]) -> None:
    request_id = str(job.get("request_id", "")).strip()
    message = str(job.get("message", "")).strip()
    image_payload = job.get("image") if isinstance(job.get("image"), dict) else None
    has_image = image_payload is not None
    if not request_id or (not message and not has_image):
        return

    settings = await load_settings()
    chat = _find_chat_by_id(settings, chat_id)
    if chat is None:
        return
    ensure_runtime_context_seed(chat, settings)

    assistant = _find_assistant_message_by_request_id(chat, request_id)
    if assistant is None:
        return

    assistant.status = "processing"
    assistant.timestamp = datetime.now(timezone.utc).isoformat()
    await save_chat_state(settings.chats, settings.active_chat_id, settings.daily_token_usage, preserve_active_chat_id=True)

    resolved_provider_id = str(job.get("provider_id", "")).strip() or settings.active_provider_id
    resolved_provider_config = settings.provider_configs.get(resolved_provider_id)
    resolved_model = str(job.get("model", "")).strip() or (resolved_provider_config.model if resolved_provider_config else "")
    resolved_api_key = str(job.get("api_key", "")).strip() or (resolved_provider_config.api_key if resolved_provider_config else "")

    history = _build_gateway_history(chat.messages)
    image_analysis_text = ""
    image_analysis_tokens: int | None = None
    if has_image:
        image_mime = str(image_payload.get("mime_type", "")).strip()
        image_bytes = image_payload.get("content_bytes")
        if not image_mime.startswith("image/") or not isinstance(image_bytes, (bytes, bytearray)):
            await _mark_gateway_request_error(chat_id, request_id, "Hard error: Invalid image payload.")
            return
        try:
            image_analysis_text, image_analysis_tokens = await analyze_image(
                provider_id=resolved_provider_id,
                model=resolved_model,
                api_key=resolved_api_key,
                image_bytes=bytes(image_bytes),
                mime_type=image_mime,
                prompt=_image_analysis_prompt(message),
            )
        except Exception as exc:
            await _mark_gateway_request_error(chat_id, request_id, f"Image analysis failed: {exc}")
            return

        settings_with_analysis = await load_settings()
        chat_with_analysis = _find_chat_by_id(settings_with_analysis, chat_id)
        if chat_with_analysis is None:
            return
        analysis_message = ChatMessage(
            role="assistant",
            content=f"Image analysis: {image_analysis_text.strip()}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            request_id=request_id,
            status="done",
        )
        chat_with_analysis.messages.append(analysis_message)
        await save_chat_state(
            settings_with_analysis.chats,
            settings_with_analysis.active_chat_id,
            settings_with_analysis.daily_token_usage,
            preserve_active_chat_id=True,
        )

        settings = settings_with_analysis
        chat = chat_with_analysis
        history = _build_gateway_history(chat.messages)

    model_message = message.strip()
    if has_image:
        analysis_block = image_analysis_text.strip()
        if model_message:
            model_message = f"{model_message}\n\nImage analysis:\n{analysis_block}"
        else:
            model_message = (
                "The user sent an image without text. Use this image analysis to respond helpfully:\n"
                f"{analysis_block}"
            )

    async def _on_execution_event(event: ExecutionEvent) -> None:
        await _persist_gateway_execution_update(chat_id=chat_id, request_id=request_id, event=event)

    try:
        result, _ = await generate_chat_response(
            settings=settings,
            message=model_message,
            history=history,
            memory_block=chat.memory_block,
            provider_id=str(job.get("provider_id", "")),
            model=str(job.get("model", "")),
            api_key=str(job.get("api_key", "")),
            bot_name=str(job.get("bot_name", "")),
            system_prompt=str(job.get("system_prompt", "")),
            source_channel="gateway",
            source_chat_id=chat_id,
            source_request_id=request_id,
            on_execution_event=_on_execution_event,
        )
    except asyncio.CancelledError:
        user_cancelled = request_id in _gateway_chat_user_cancelled_request_ids
        _gateway_chat_user_cancelled_request_ids.discard(request_id)
        detail = (
            "Execution interrupted by user."
            if user_cancelled
            else "Execution interrupted (server restart/reload or background cancellation)."
        )
        await _mark_gateway_requests_interrupted(chat_id, request_ids=[request_id], detail=detail)
        raise
    except Exception as exc:
        await _mark_gateway_request_error(chat_id, request_id, f"Hard error: {exc}")
        return

    settings = await load_settings()
    chat = _find_chat_by_id(settings, chat_id)
    if chat is None:
        return
    assistant = _find_assistant_message_by_request_id(chat, request_id)
    if assistant is None:
        return

    final_timestamp = datetime.now(timezone.utc).isoformat()
    trace_messages = result.get("system_trace_messages", []) if isinstance(result, dict) else []
    if isinstance(trace_messages, list):
        for entry in trace_messages:
            if not isinstance(entry, dict):
                continue
            content = str(entry.get("content", "")).strip()
            if not content:
                continue
            system_type = str(entry.get("system_type", "")).strip() or "orchestrator"
            _append_gateway_system_message(
                chat,
                content=content,
                timestamp=final_timestamp,
                system_type=system_type,
                request_id=request_id,
            )

    assistant.content = str(result.get("text", "")).strip() if isinstance(result, dict) else ""
    assistant.timestamp = final_timestamp
    assistant.status = "done"
    raw_tool_usage = result.get("used_mcp_tools", []) if isinstance(result, dict) else []
    assistant.tool_usage = [
        {
            "mcp_id": str(item.get("mcp_id", "")),
            "mcp_label": str(item.get("mcp_label", "")),
            "tool_id": str(item.get("tool_id", "")),
            "tool_label": str(item.get("tool_label", "")),
        }
        for item in raw_tool_usage
        if isinstance(item, dict)
    ]

    used_tokens = result.get("used_tokens") if isinstance(result, dict) else None
    if isinstance(image_analysis_tokens, int) and image_analysis_tokens > 0:
        used_tokens = (used_tokens if isinstance(used_tokens, int) else 0) + image_analysis_tokens
    if isinstance(used_tokens, int) and used_tokens > 0:
        chat.total_tokens_used = max(0, chat.total_tokens_used) + used_tokens
        add_daily_usage(settings, used_tokens)

    await save_chat_state(settings.chats, settings.active_chat_id, settings.daily_token_usage, preserve_active_chat_id=True)

    # After the first user message, generate a fitting chat title in the background.
    user_messages = [m for m in chat.messages if m.role == "user" and m.content.strip()]
    if len(user_messages) == 1:
        asyncio.create_task(_generate_and_save_chat_title(
            chat_id=chat_id,
            first_user_message=message,
            provider_id=resolved_provider_id,
            model=resolved_model,
            api_key=resolved_api_key,
        ))

    try:
        await register_completed_turn(
            source_channel="gateway",
            source_chat_id=chat_id,
            user_message=message or "[Image attached]",
            assistant_message=assistant.content,
        )
    except Exception:
        pass


async def _stop_gateway_chat(chat_id: str) -> int:
    queued_request_ids: list[str] = []
    active_request_id = ""

    async with _gateway_chat_lock:
        queue = _gateway_chat_queues.get(chat_id, [])
        for entry in queue:
            request_id = str(entry.get("request_id", "")).strip()
            if request_id:
                queued_request_ids.append(request_id)
        _gateway_chat_queues[chat_id] = []
        active_request_id = _gateway_chat_active_request_ids.get(chat_id, "").strip()
        task = _gateway_chat_tasks.pop(chat_id, None)
        _gateway_chat_active_request_ids.pop(chat_id, None)
        if task is not None:
            task.cancel()

    request_ids = [request_id for request_id in queued_request_ids if request_id]
    if active_request_id and active_request_id not in request_ids:
        request_ids.append(active_request_id)
    _gateway_chat_user_cancelled_request_ids.update(request_ids)
    await cancel_registered_executions(
        request_ids=request_ids,
        conversation_key=f"gateway:{chat_id}",
        reason="Execution interrupted by user.",
    )
    return await _mark_gateway_requests_interrupted(chat_id, request_ids=request_ids, detail="Execution interrupted by user.")


async def _mark_gateway_request_error(chat_id: str, request_id: str, detail: str) -> None:
    settings = await load_settings()
    chat = _find_chat_by_id(settings, chat_id)
    if chat is None:
        return
    message = _find_assistant_message_by_request_id(chat, request_id)
    if message is None:
        return
    message.status = "error"
    message.timestamp = datetime.now(timezone.utc).isoformat()
    existing = message.content.strip()
    message.content = f"{existing}\n\n{detail}".strip() if existing else detail
    await save_chat_state(settings.chats, settings.active_chat_id, settings.daily_token_usage, preserve_active_chat_id=True)


async def _mark_gateway_requests_interrupted(chat_id: str, request_ids: list[str], detail: str) -> int:
    settings = await load_settings()
    chat = _find_chat_by_id(settings, chat_id)
    if chat is None:
        return 0

    target_ids = {request_id.strip() for request_id in request_ids if request_id.strip()}
    changed = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    for message in chat.messages:
        if message.role != "assistant":
            continue
        if message.status not in {"queued", "processing"}:
            continue
        if target_ids and message.request_id not in target_ids:
            continue
        existing = message.content.strip()
        message.content = f"{existing}\n\n{detail}".strip() if existing else detail
        message.status = "error"
        message.timestamp = now_iso
        changed += 1

    if changed > 0:
        await save_chat_state(settings.chats, settings.active_chat_id, settings.daily_token_usage, preserve_active_chat_id=True)
    return changed


async def shutdown_gateway() -> None:
    """Cancel all pending gateway chat tasks. Called from the app shutdown event."""
    async with _gateway_chat_lock:
        tasks = list(_gateway_chat_tasks.values())
        _gateway_chat_tasks.clear()
        _gateway_chat_queues.clear()
        _gateway_chat_active_request_ids.clear()
        _gateway_chat_user_cancelled_request_ids.clear()
        _gateway_chat_client_enqueue_ids.clear()
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def _find_chat_by_id(settings: Settings, chat_id: str) -> Any:
    for chat in settings.chats:
        if chat.id == chat_id:
            return chat
    return None


def _find_assistant_message_by_request_id(chat: Any, request_id: str) -> Any:
    for message in chat.messages:
        if message.role == "assistant" and message.request_id == request_id:
            return message
    return None


def _append_gateway_system_message(
    chat: Any,
    *,
    content: str,
    timestamp: str,
    system_type: str,
    request_id: str,
) -> bool:
    normalized_content = content.strip()
    normalized_system_type = system_type.strip() or "orchestrator"
    normalized_request_id = request_id.strip()
    if not normalized_content:
        return False
    duplicate = any(
        message.role == "system"
        and message.request_id == normalized_request_id
        and message.system_type == normalized_system_type
        and message.content == normalized_content
        for message in chat.messages
    )
    if duplicate:
        return False
    chat.messages.append(
        ChatMessage(
            role="system",
            content=normalized_content,
            timestamp=timestamp,
            system_type=normalized_system_type,
            request_id=normalized_request_id,
        )
    )
    return True


async def _persist_gateway_execution_update(
    *,
    chat_id: str,
    request_id: str,
    event: ExecutionEvent,
) -> None:
    event_type = str(event.get("event_type", "")).strip()
    message = str(event.get("message", "")).strip()
    if not event_type or not message:
        return
    settings = await load_settings()
    chat = _find_chat_by_id(settings, chat_id)
    if chat is None:
        return
    appended = _append_gateway_system_message(
        chat,
        content=message,
        timestamp=datetime.now(timezone.utc).isoformat(),
        system_type=f"execution_{event_type}",
        request_id=request_id,
    )
    if not appended:
        return
    await save_chat_state(settings.chats, settings.active_chat_id, settings.daily_token_usage, preserve_active_chat_id=True)


def _build_gateway_history(messages: list[ChatMessage]) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for turn in messages:
        if turn.role not in {"user", "assistant", "system"}:
            continue
        content = turn.content.strip()
        if not content:
            continue
        if turn.role == "system" and turn.system_type != "runtime_context_seed":
            continue
        history.append({"role": turn.role, "content": content})
    return history


def _image_analysis_prompt(user_message: str) -> str:
    user_text = user_message.strip()
    if user_text:
        return (
            "Analyze this image for the current chat request. "
            "Provide a concise factual summary, visible text (OCR), and details relevant to the user request. "
            "Do not invent details.\n\n"
            f"User request: {user_text}"
        )
    return (
        "Analyze this image for chat context. Provide a concise factual summary, visible text (OCR), "
        "and relevant notable details. Do not invent details."
    )


def _normalize_enqueued_image(raw: dict[str, str] | None) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    mime_type = str(raw.get("mime_type", "")).strip().lower()
    content_base64 = str(raw.get("content_base64", "")).strip()
    file_name = str(raw.get("file_name", "")).strip()
    if not mime_type and not content_base64:
        return None
    if not mime_type.startswith("image/"):
        raise HTTPException(status_code=422, detail="Only image attachments are supported.")
    if not content_base64:
        raise HTTPException(status_code=422, detail="Image content is missing.")
    try:
        image_bytes = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Image payload is not valid base64.") from exc
    if not image_bytes:
        raise HTTPException(status_code=422, detail="Image payload is empty.")
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="Image exceeds 10MB limit.")
    return {
        "mime_type": mime_type,
        "content_bytes": image_bytes,
        "file_name": file_name,
    }


# ---------------------------------------------------------------------------
# SSE and compaction helpers
# ---------------------------------------------------------------------------

def _sse(event_name: str, payload: dict[str, object]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload, default=str)}\n\n"


def _chunk_text(text: str) -> list[str]:
    tokens = text.split(" ")
    if len(tokens) <= 1:
        return [text]
    return [f"{token} " for token in tokens[:-1]] + [tokens[-1]]


def _compaction_system_prompt() -> str:
    return (
        "You compress chat history into a durable memory block. "
        "Keep only facts that matter for future turns: user preferences, goals, constraints, "
        "decisions, unresolved items, and concrete context. "
        "Do not invent facts. Keep compact wording and avoid filler."
    )


def _build_compaction_prompt(existing_memory: str, target_token_limit: int) -> str:
    lines = [
        "Create an updated compact memory block from the conversation history.",
        "Return plain text only.",
        "Use sections exactly in this order:",
        "1) User profile and preferences",
        "2) Confirmed facts and decisions",
        "3) Open tasks and pending questions",
        "4) Important style constraints",
        "Keep it concise and dense.",
    ]

    if target_token_limit > 0:
        lines.append(
            f"This memory will support a model with {target_token_limit} token context, so keep memory lean."
        )

    if existing_memory.strip():
        lines.append("Merge and refresh this previous memory block, keeping only still-relevant points:")
        lines.append(existing_memory.strip())

    return "\n".join(lines)
