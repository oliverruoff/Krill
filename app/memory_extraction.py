"""Background memory extraction service for short-term memory suggestions."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from app.config import (
    add_short_term_memories,
    append_conversation_turn,
    get_recent_conversation_turns,
    load_settings,
    register_user_message_event,
)
from app.providers import get_provider
from app.providers.resilience import generate_with_retries


_EXTRACTION_LOCK = asyncio.Lock()
_EXTRACTION_QUEUE: asyncio.Queue[dict[str, object]] = asyncio.Queue()
_EXTRACTION_WORKER_TASK: asyncio.Task[None] | None = None
_EXTRACTION_STATUS: dict[str, object] = {
    "in_progress": False,
    "last_started_at": "",
    "last_finished_at": "",
    "last_added": 0,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_memory_extraction_status() -> dict[str, object]:
    raw_last_added = _EXTRACTION_STATUS.get("last_added", 0)
    if type(raw_last_added) is int:
        last_added = raw_last_added
    else:
        last_added = 0

    return {
        "in_progress": bool(_EXTRACTION_STATUS.get("in_progress", False)),
        "last_started_at": str(_EXTRACTION_STATUS.get("last_started_at", "")),
        "last_finished_at": str(_EXTRACTION_STATUS.get("last_finished_at", "")),
        "last_added": last_added,
        "queue_size": _EXTRACTION_QUEUE.qsize(),
    }


def _ensure_worker_running() -> None:
    global _EXTRACTION_WORKER_TASK
    if _EXTRACTION_WORKER_TASK is not None and not _EXTRACTION_WORKER_TASK.done():
        return
    _EXTRACTION_WORKER_TASK = asyncio.create_task(_extraction_worker_loop())


async def start_memory_extraction_worker() -> None:
    _ensure_worker_running()


async def stop_memory_extraction_worker() -> None:
    global _EXTRACTION_WORKER_TASK
    if _EXTRACTION_WORKER_TASK is None:
        return
    _EXTRACTION_WORKER_TASK.cancel()
    try:
        await _EXTRACTION_WORKER_TASK
    except asyncio.CancelledError:
        pass
    _EXTRACTION_WORKER_TASK = None


async def _extraction_worker_loop() -> None:
    while True:
        payload = await _EXTRACTION_QUEUE.get()
        try:
            await run_memory_extraction(
                trigger_count=_to_int(payload.get("trigger_count"), 0),
                interval=_to_int(payload.get("interval"), 10),
                source_channel=str(payload.get("source_channel", "")),
                source_chat_id=str(payload.get("source_chat_id", "")),
            )
        except Exception:
            # Background worker must never crash the app.
            pass
        finally:
            _EXTRACTION_QUEUE.task_done()


def _to_int(value: object, default: int) -> int:
    if type(value) is int:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return default


def _build_extraction_prompt() -> str:
    return (
        "Analyze only the provided user messages and extract memory candidates.\n"
        "Return JSON only with this exact schema:\n"
        '{"core_memories": ["..."], "normal_memories": ["..."]}\n\n'
        "Rules:\n"
        "- core_memories: stable preferences/identity/long-term constraints.\n"
        "- normal_memories: useful but less critical context.\n"
        "- Write every memory in third-person, self-contained form prefixed with 'The user ...'.\n"
        "- Never use first-person phrasing like 'I', 'my', 'me'.\n"
        "- Example good: 'The user's best friend is Peter.'\n"
        "- Example bad: 'My best friend is Peter.'\n"
        "- Do not invent facts.\n"
        "- Keep each memory short and concrete.\n"
        "- Empty arrays are allowed if nothing should be remembered."
    )


def _parse_json_payload(text: str) -> dict[str, Any]:
    raw = str(text).strip()
    if not raw:
        return {"core_memories": [], "normal_memories": []}

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        candidate = raw[start : end + 1]
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {"core_memories": [], "normal_memories": []}
    return {"core_memories": [], "normal_memories": []}


def _normalize_memory_list(raw_items: Any) -> list[str]:
    if not isinstance(raw_items, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = " ".join(str(item).split()).strip()
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(text)
    return result


async def register_user_message_and_maybe_extract(*, source_channel: str, source_chat_id: str) -> bool:
    count, interval, should_trigger = await register_user_message_event()
    if not should_trigger:
        return False

    _ensure_worker_running()
    _EXTRACTION_QUEUE.put_nowait(
        {
            "trigger_count": count,
            "interval": interval,
            "source_channel": source_channel,
            "source_chat_id": source_chat_id,
        }
    )
    return True


async def register_completed_turn(
    *,
    source_channel: str,
    source_chat_id: str,
    user_message: str,
    assistant_message: str,
) -> None:
    await append_conversation_turn(
        source_channel=source_channel,
        source_chat_id=source_chat_id,
        user_message=user_message,
        assistant_message=assistant_message,
    )


async def run_memory_extraction(*, trigger_count: int, interval: int, source_channel: str, source_chat_id: str) -> int:
    async with _EXTRACTION_LOCK:
        _EXTRACTION_STATUS["in_progress"] = True
        _EXTRACTION_STATUS["last_started_at"] = _now_iso()
        _EXTRACTION_STATUS["last_added"] = 0
        try:
            settings = await load_settings()
            provider_id = settings.active_provider_id
            provider_config = settings.provider_configs.get(provider_id)
            if not provider_id or provider_config is None:
                return 0

            provider = get_provider(provider_id)
            if provider is None:
                return 0

            turns = await get_recent_conversation_turns(interval)
            if not turns:
                return 0

            history: list[dict[str, str]] = []
            for turn in turns:
                user_message = str(turn.get("user_message", "")).strip()
                if user_message:
                    history.append({"role": "user", "content": user_message})

            if not history:
                return 0

            try:
                response_text, _ = await generate_with_retries(
                    provider=provider,
                    prompt=_build_extraction_prompt(),
                    system_prompt="You are a precise memory extraction engine. Return valid JSON only.",
                    model=provider_config.model,
                    api_key=provider_config.api_key,
                    history=history,
                )
            except Exception:
                return 0

            payload = _parse_json_payload(response_text)
            core = _normalize_memory_list(payload.get("core_memories"))
            normal = _normalize_memory_list(payload.get("normal_memories"))
            if not core and not normal:
                return 0

            added = await add_short_term_memories(
                core_memories=core,
                normal_memories=normal,
                source_channel=source_channel,
                source_chat_id=source_chat_id,
                source_request_id=f"auto-{trigger_count}",
            )
            _EXTRACTION_STATUS["last_added"] = added
            return added
        finally:
            _EXTRACTION_STATUS["in_progress"] = False
            _EXTRACTION_STATUS["last_finished_at"] = _now_iso()
