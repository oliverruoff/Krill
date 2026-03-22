"""Helpers for snapshotting chats into hidden debug dumps."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import ChatMessage, ChatSession, DATA_DIR, Settings, save_settings
from app.shared_files import create_shared_file_link
from app.version import APP_VERSION

DEBUG_CHAT_PREFIX = "[HIDDEN] [DEBUG]"
DEBUG_DUMPS_DIR = (DATA_DIR / "debug_dumps").resolve()
DEBUG_DUMP_TTL_SECONDS = 24 * 60 * 60


def is_debug_command(text: str) -> bool:
    return str(text or "").strip().lower() == "/debug"


def build_debug_chat_title(source_title: str) -> str:
    clean_title = " ".join(str(source_title or "").split()).strip() or "Chat"
    return f"{DEBUG_CHAT_PREFIX} {clean_title}"[:120]


def build_debug_dump_payload(
    snapshot_chat: ChatSession,
    *,
    source_channel: str,
    settings: Settings,
    triggered_by: str,
) -> dict[str, object]:
    generated_at = datetime.now(timezone.utc).isoformat()
    latest_error_messages = [
        {
            "role": message.role,
            "timestamp": message.timestamp,
            "request_id": message.request_id,
            "status": message.status,
            "content": message.content,
        }
        for message in snapshot_chat.messages
        if message.status == "error"
    ]

    return {
        "kind": "chat_debug_dump",
        "app_version": APP_VERSION,
        "generated_at": generated_at,
        "triggered_by": triggered_by,
        "source_channel": source_channel,
        "settings_snapshot": {
            "bot_name": settings.bot_name,
            "user_full_name": settings.user_full_name,
            "user_call_name": settings.user_call_name,
            "system_prompt": settings.system_prompt,
            "active_provider_id": settings.active_provider_id,
            "active_model_id": settings.active_model_id,
            "tool_max_recursion": settings.tool_max_recursion,
            "tool_timeout_seconds": settings.tool_timeout_seconds,
            "core_memories": [
                memory.content
                for memory in settings.core_memories
                if memory.content.strip()
            ],
        },
        "chat": {
            "id": snapshot_chat.id,
            "title": snapshot_chat.title,
            "type": snapshot_chat.type,
            "memory_block": snapshot_chat.memory_block,
            "total_tokens_used": snapshot_chat.total_tokens_used,
            "collapse_system_trace": snapshot_chat.collapse_system_trace,
            "hidden_from_history": snapshot_chat.hidden_from_history,
            "message_count": len(snapshot_chat.messages),
            "messages": [_message_to_dump_dict(message) for message in snapshot_chat.messages],
        },
        "latest_error_messages": latest_error_messages,
    }


async def create_hidden_debug_chat(
    *,
    snapshot_chat: ChatSession,
    source_channel: str,
    settings: Settings,
    triggered_by: str,
) -> dict[str, object]:
    payload = build_debug_dump_payload(
        snapshot_chat,
        source_channel=source_channel,
        settings=settings,
        triggered_by=triggered_by,
    )
    file_info = await _write_debug_dump_file(payload, source_channel=source_channel, source_chat=snapshot_chat)
    chat_message = _build_debug_chat_message(payload, file_info)
    timestamp = str(payload.get("generated_at", datetime.now(timezone.utc).isoformat()))
    debug_chat = ChatSession(
        id=str(uuid4()),
        title=build_debug_chat_title(snapshot_chat.title),
        type="normal",
        messages=[
            ChatMessage(
                role="assistant",
                content=chat_message,
                timestamp=timestamp,
                status="done",
            )
        ],
        memory_block="",
        total_tokens_used=0,
        collapse_system_trace=False,
        hidden_from_history=True,
    )
    settings.chats.insert(0, debug_chat)
    await save_settings(settings)
    return {
        "debug_chat": debug_chat,
        "file_info": file_info,
        "payload": payload,
    }


def _message_to_dump_dict(message: ChatMessage) -> dict[str, object]:
    return {
        "role": message.role,
        "content": message.content,
        "timestamp": message.timestamp,
        "system_type": message.system_type,
        "tool_usage": [dict(entry) for entry in message.tool_usage],
        "request_id": message.request_id,
        "status": message.status,
    }


async def _write_debug_dump_file(
    payload: dict[str, object],
    *,
    source_channel: str,
    source_chat: ChatSession,
) -> dict[str, object]:
    timestamp = _compact_timestamp(str(payload.get("generated_at", "")))
    file_name = (
        f"debug-{_sanitize_file_component(source_channel)}-"
        f"{_sanitize_file_component(source_chat.title)}-{timestamp}.json"
    )
    file_path = DEBUG_DUMPS_DIR / file_name
    dump_text = json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True)

    await asyncio.to_thread(DEBUG_DUMPS_DIR.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(file_path.write_text, dump_text, "utf-8")

    shared = await create_shared_file_link(
        file_path,
        download_name=file_name,
        ttl_seconds=DEBUG_DUMP_TTL_SECONDS,
    )
    return {
        "path": str(file_path),
        "download_url": str(shared.get("download_url", "")),
        "filename": file_name,
        "expires_at": str(shared.get("expires_at", "")),
    }


def _build_debug_chat_message(payload: dict[str, object], file_info: dict[str, object]) -> str:
    download_url = str(file_info.get("download_url", "")).strip()
    file_path = str(file_info.get("path", "")).strip()
    generated_at = str(payload.get("generated_at", "")).strip()
    source_channel = str(payload.get("source_channel", "")).strip()
    chat_payload = payload.get("chat") if isinstance(payload.get("chat"), dict) else {}
    source_chat_id = str(chat_payload.get("id", "")).strip() if isinstance(chat_payload, dict) else ""
    source_title = str(chat_payload.get("title", "")).strip() if isinstance(chat_payload, dict) else ""

    lines = [
        "Debug dump created automatically via /debug.",
        f"Generated at: {generated_at}",
        f"Source channel: {source_channel}",
        f"Source chat id: {source_chat_id}",
        f"Source chat title: {source_title}",
        f"Stored file: {file_path}",
    ]
    if download_url:
        lines.append(f"Download URL: {download_url}")

    dump_json = json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True)
    lines.extend(["", "```json", dump_json, "```"])
    return "\n".join(lines)


def _sanitize_file_component(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "chat"
    sanitized = re.sub(r"[^a-z0-9._-]+", "-", text)
    sanitized = sanitized.strip("-._")
    return sanitized[:80] or "chat"


def _compact_timestamp(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    compact = re.sub(r"[^0-9A-Za-z]+", "", text)
    return compact[:32] or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
