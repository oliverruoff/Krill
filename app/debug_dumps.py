"""Helpers for snapshotting chats into hidden debug dumps."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.config import ChatMessage, ChatSession, DATA_DIR, Settings, save_settings
from app.shared_files import create_shared_file_link
from app.version import APP_VERSION

logger = logging.getLogger(__name__)

DEBUG_CHAT_PREFIX = "[HIDDEN] [DEBUG]"
DEBUG_DUMPS_DIR = (DATA_DIR / "debug_dumps").resolve()
DEBUG_DUMP_TTL_SECONDS = 24 * 60 * 60
_PUBLIC_BASE_URL_ENV = "KRILL_PUBLIC_BASE_URL"
_PUBLIC_PORT_ENV = "KRILL_PUBLIC_PORT"
_DEFAULT_PUBLIC_PORT = 8055

# Maximum serialized size (bytes) before message list is truncated in the dump file.
_DUMP_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
# Number of most-recent messages to keep when truncating.
_DUMP_TRUNCATE_KEEP_MESSAGES = 50
# Maximum number of debug dump files to retain on disk.
_DUMP_MAX_FILES = 10


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


def _prune_old_debug_dumps(keep_count: int = _DUMP_MAX_FILES) -> None:
    """Delete oldest debug dump files, keeping only the *keep_count* most recent.

    Runs synchronously so it can be dispatched via asyncio.to_thread.
    Failures are logged but never propagated — pruning must not break the dump flow.
    """
    if not DEBUG_DUMPS_DIR.is_dir():
        return
    try:
        dump_files = sorted(
            DEBUG_DUMPS_DIR.glob("debug-*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        to_delete = dump_files[keep_count:]
        for old_file in to_delete:
            try:
                old_file.unlink(missing_ok=True)
                logger.info("debug_dump: pruned old dump file %s", old_file.name)
            except Exception as exc:
                logger.warning("debug_dump: could not delete %s: %s", old_file.name, exc)
    except Exception as exc:
        logger.warning("debug_dump: pruning failed: %s", exc)


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

    # Apply size cap: if the full serialization exceeds _DUMP_MAX_BYTES, truncate
    # the messages list and add a warning note so the file stays manageable.
    dump_text = json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True)
    if len(dump_text.encode("utf-8")) > _DUMP_MAX_BYTES:
        chat_section = payload.get("chat")
        if isinstance(chat_section, dict):
            all_messages = list(chat_section.get("messages") or [])
            total_count = len(all_messages)
            kept = all_messages[-_DUMP_TRUNCATE_KEEP_MESSAGES:]
            truncated_count = total_count - len(kept)
            chat_section = dict(chat_section)
            chat_section["messages"] = kept
            chat_section["truncation_note"] = (
                f"Messages truncated: {truncated_count} oldest message(s) omitted "
                f"because the dump exceeded {_DUMP_MAX_BYTES // (1024 * 1024)} MB. "
                f"Kept last {len(kept)} of {total_count}."
            )
            payload = dict(payload)
            payload["chat"] = chat_section
            payload["truncated"] = True
            dump_text = json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True)
            logger.warning(
                "debug_dump: payload exceeded size cap; truncated %d message(s) for %s",
                truncated_count,
                file_name,
            )

    await asyncio.to_thread(DEBUG_DUMPS_DIR.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(file_path.write_text, dump_text, "utf-8")

    # Prune old dump files to keep disk usage bounded.
    await asyncio.to_thread(_prune_old_debug_dumps)

    shared = await create_shared_file_link(
        file_path,
        download_name=file_name,
        ttl_seconds=DEBUG_DUMP_TTL_SECONDS,
    )
    return {
        "path": str(file_path),
        "download_url": str(shared.get("download_url", "")),
        "download_url_absolute": build_absolute_debug_download_url(str(shared.get("download_url", ""))),
        "filename": file_name,
        "expires_at": str(shared.get("expires_at", "")),
        "size_bytes": len(dump_text.encode("utf-8")),
        "truncated": bool(payload.get("truncated", False)),
    }


def _build_debug_chat_message(payload: dict[str, object], file_info: dict[str, object]) -> str:
    download_url = str(file_info.get("download_url", "")).strip()
    download_url_absolute = str(file_info.get("download_url_absolute", "")).strip()
    file_path = str(file_info.get("path", "")).strip()
    generated_at = str(payload.get("generated_at", "")).strip()
    source_channel = str(payload.get("source_channel", "")).strip()
    chat_payload = payload.get("chat") if isinstance(payload.get("chat"), dict) else {}
    source_chat_id = str(chat_payload.get("id", "")).strip() if isinstance(chat_payload, dict) else ""
    source_title = str(chat_payload.get("title", "")).strip() if isinstance(chat_payload, dict) else ""
    message_count = chat_payload.get("message_count", "") if isinstance(chat_payload, dict) else ""
    _raw_size = file_info.get("size_bytes")
    size_bytes = int(_raw_size) if isinstance(_raw_size, int | float) else 0
    size_kb = round(size_bytes / 1024, 1) if size_bytes else None
    truncated = bool(file_info.get("truncated", False))

    lines = [
        "Debug dump created via /debug.",
        f"Generated at: {generated_at}",
        f"Source channel: {source_channel}",
        f"Source chat id: {source_chat_id}",
        f"Source chat title: {source_title}",
        f"Message count: {message_count}",
    ]
    if truncated:
        lines.append("Note: message list was truncated (dump exceeded size cap).")
    if size_kb is not None:
        lines.append(f"Dump file size: {size_kb} KB")
    lines.append(f"Stored file: {file_path}")
    if download_url_absolute:
        lines.append(f"Download URL: {download_url_absolute}")
    elif download_url:
        lines.append(f"Download URL: {download_url}")
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


def build_absolute_debug_download_url(download_url: str) -> str:
    path = str(download_url or "").strip()
    if not path.startswith("/"):
        return ""

    override = os.getenv(_PUBLIC_BASE_URL_ENV, "").strip().rstrip("/")
    if override:
        if override.startswith("http://") or override.startswith("https://"):
            return f"{override}{path}"
        return ""

    host = _detect_local_ip_address()
    if not host:
        return ""
    port = _public_port()
    return f"http://{host}:{port}{path}"


def _public_port() -> int:
    raw_value = os.getenv(_PUBLIC_PORT_ENV, "").strip()
    if raw_value:
        try:
            port = int(raw_value)
        except ValueError:
            return _DEFAULT_PUBLIC_PORT
        if 1 <= port <= 65535:
            return port
    return _DEFAULT_PUBLIC_PORT


def _detect_local_ip_address() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            address = str(sock.getsockname()[0]).strip()
            if _is_lan_ipv4_address(address):
                return address
    except OSError:
        pass

    try:
        hostname = socket.gethostname()
        candidates = socket.gethostbyname_ex(hostname)[2]
    except OSError:
        return ""

    for candidate in candidates:
        if _is_lan_ipv4_address(candidate):
            return candidate
    return ""


def _is_lan_ipv4_address(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return False
    return bool(address.version == 4 and address.is_private and not address.is_loopback)
