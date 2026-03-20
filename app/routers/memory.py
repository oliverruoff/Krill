"""Memory management routes: registration, short-term review, and compaction."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import MemoryEntry, load_settings, save_settings
from ..memory_extraction import (
    get_memory_extraction_status,
    register_completed_turn,
    register_user_message_and_maybe_extract,
)
from ..providers import get_provider
from ..providers.resilience import generate_with_retries
from ..config import list_short_term_memories, resolve_short_term_memories
from .helpers import _is_setup_complete

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class MemoryUserMessageRequest(BaseModel):
    source_channel: str = "gateway"
    source_chat_id: str = ""


class MemoryTurnCompleteRequest(BaseModel):
    source_channel: str = "gateway"
    source_chat_id: str = ""
    user_message: str = Field(min_length=1, max_length=10000)
    assistant_message: str = Field(default="", max_length=30000)


class ShortTermMemoryResolveItem(BaseModel):
    id: int
    action: Literal["accept", "decline"]
    memory_type: Literal["core", "normal"] = "normal"


class ShortTermMemoryResolveRequest(BaseModel):
    items: list[ShortTermMemoryResolveItem] = Field(default_factory=list)


class MemoryCompactionRequest(BaseModel):
    memory_type: Literal["core", "normal"]


class MemoryCompactionResponse(BaseModel):
    ok: bool = True
    memory_type: Literal["core", "normal"]
    used_tokens: int | None = None
    compacted_count: int = 0
    core_memories: list[dict[str, str]] = Field(default_factory=list)
    normal_memories: list[dict[str, str]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/api/memory/user-message")
async def register_memory_user_message(payload: MemoryUserMessageRequest) -> dict[str, object]:
    triggered = await register_user_message_and_maybe_extract(
        source_channel=payload.source_channel,
        source_chat_id=payload.source_chat_id,
    )
    return {"ok": True, "triggered": triggered}


@router.post("/api/memory/turn-complete")
async def register_memory_turn_complete(payload: MemoryTurnCompleteRequest) -> dict[str, object]:
    await register_completed_turn(
        source_channel=payload.source_channel,
        source_chat_id=payload.source_chat_id,
        user_message=payload.user_message,
        assistant_message=payload.assistant_message,
    )
    return {"ok": True}


@router.get("/api/memory/short-term")
async def get_short_term_memory() -> dict[str, object]:
    items = await list_short_term_memories(status="pending")
    status = get_memory_extraction_status()
    return {
        "ok": True,
        "count": len(items),
        "items": [item.model_dump() for item in items],
        "extraction": status,
    }


@router.post("/api/memory/short-term/resolve")
async def resolve_short_term_memory(payload: ShortTermMemoryResolveRequest) -> dict[str, object]:
    changed = await resolve_short_term_memories([item.model_dump() for item in payload.items])
    return {"ok": True, "changed": changed}


@router.post("/api/memory/compact", response_model=MemoryCompactionResponse)
async def compact_memories(payload: MemoryCompactionRequest) -> MemoryCompactionResponse:
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

    source_memories = settings.core_memories if payload.memory_type == "core" else settings.normal_memories
    compactable = [entry for entry in source_memories if entry.content.strip()]
    if not compactable:
        raise HTTPException(status_code=422, detail="No memories available to compact for this type.")

    source_lines, required_timestamps, _ = _build_memory_compaction_source(compactable)
    prompt = _build_memory_compaction_prompt(payload.memory_type, source_lines, required_timestamps)

    try:
        compacted_text, used_tokens = await generate_with_retries(
            provider=provider,
            prompt=prompt,
            system_prompt=_memory_compaction_system_prompt(),
            model=provider_config.model,
            api_key=provider_config.api_key,
            history=[],
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Memory compaction failed: {exc}") from exc

    compacted_memory = _normalize_compacted_memory_output(str(compacted_text), required_timestamps)
    if not compacted_memory:
        raise HTTPException(status_code=422, detail="Memory compaction failed: Provider returned empty compacted memory.")

    compacted_entry = MemoryEntry(content=compacted_memory, created_at=datetime.now(timezone.utc).isoformat())
    if payload.memory_type == "core":
        settings.core_memories = [compacted_entry]
    else:
        settings.normal_memories = [compacted_entry]

    persisted = await save_settings(settings)
    return MemoryCompactionResponse(
        memory_type=payload.memory_type,
        used_tokens=used_tokens,
        compacted_count=len(compactable),
        core_memories=[entry.model_dump() for entry in persisted.core_memories],
        normal_memories=[entry.model_dump() for entry in persisted.normal_memories],
    )


# ---------------------------------------------------------------------------
# Memory compaction helpers
# ---------------------------------------------------------------------------

def _memory_compaction_system_prompt() -> str:
    return (
        "You are a lossless memory compactor. Compress memory text aggressively while preserving every concrete fact. "
        "Never invent information. Remove duplicates only when the factual meaning is identical. "
        "Preserve timestamp provenance by retaining all timestamps exactly as provided."
    )


def _normalize_memory_compaction_text(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalize_memory_timestamp_precision(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "unknown"
    if raw.lower() == "unknown":
        return "unknown"

    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.isoformat(timespec="seconds")
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

    return raw


def _looks_like_memory_timestamp(value: str) -> bool:
    candidate = str(value or "").strip()
    if not candidate:
        return False
    if candidate.lower() == "unknown":
        return True
    try:
        normalized = _normalize_memory_timestamp_precision(candidate)
        datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        return True
    except ValueError:
        pass
    try:
        datetime.strptime(candidate, "%Y-%m-%d %H:%M:%S")
        return True
    except ValueError:
        return False


def _build_memory_compaction_source(memories: list[MemoryEntry]) -> tuple[list[str], list[str], dict[str, str]]:
    lines: list[str] = []
    required_timestamps: list[str] = []
    by_marker: dict[str, str] = {}

    for entry in memories:
        timestamp = _normalize_memory_timestamp_precision(entry.created_at)
        normalized_content = _normalize_memory_compaction_text(entry.content)
        if not normalized_content:
            continue
        marker = timestamp
        required_timestamps.append(marker)
        source_line = f"{marker}: {normalized_content}"
        lines.append(source_line)
        by_marker[marker] = source_line

    return lines, required_timestamps, by_marker


def _normalize_compacted_memory_output(raw_text: str, required_timestamps: list[str]) -> str:
    allowed = {value.strip() for value in required_timestamps if value.strip()}
    fallback_timestamp = required_timestamps[0].strip() if required_timestamps else "unknown"
    normalized_lines: list[str] = []

    for raw_line in str(raw_text or "").splitlines():
        line = str(raw_line).strip()
        if not line:
            continue
        line = line.lstrip("-•* ").strip()
        if not line:
            continue

        timestamp = ""
        memory_text = ""

        if line.startswith("[ts:") and "]" in line:
            end_idx = line.find("]")
            timestamp = line[4:end_idx].strip()
            memory_text = line[end_idx + 1 :].lstrip(" :").strip()
        elif ":" in line:
            candidate_ts, rest = line.split(":", 1)
            timestamp = candidate_ts.strip()
            memory_text = rest.strip()
        else:
            memory_text = line

        timestamp = _normalize_memory_timestamp_precision(timestamp)
        timestamp = timestamp if timestamp in allowed else timestamp.strip()
        if not _looks_like_memory_timestamp(timestamp):
            timestamp = fallback_timestamp
        if not memory_text:
            continue

        normalized_lines.append(f"{timestamp}: {_normalize_memory_compaction_text(memory_text)}")

    if normalized_lines:
        return "\n".join(normalized_lines)

    fallback_text = _normalize_memory_compaction_text(raw_text)
    if not fallback_text:
        return ""
    return f"{fallback_timestamp}: {fallback_text}"


def _build_memory_compaction_prompt(
    memory_type: Literal["core", "normal"],
    source_lines: list[str],
    required_timestamps: list[str],
) -> str:
    memory_label = "core" if memory_type == "core" else "normal"
    prompt_lines = [
        f"Compact the following {memory_label} memories into one dense memory entry.",
        "Goals:",
        "- Keep every concrete fact.",
        "- Remove duplicate statements.",
        "- Minimize token usage as much as possible.",
        "- Preserve timestamp provenance in every output row.",
        "Output rules:",
        "- Return plain text only (no markdown code fences).",
        "- One memory per line in this exact format: <timestamp>: <memory>",
        "- Timestamp must have second precision (no milliseconds or microseconds).",
        "- Every non-empty line must include exactly one ':' separator between timestamp and memory text.",
        "- Do not use bullets or numbering.",
        "- Use only these timestamps (copy exactly):",
        *[f"  - {timestamp}" for timestamp in required_timestamps],
        "- Keep wording compact and structured.",
        "Source memories:",
        *source_lines,
    ]
    return "\n".join(prompt_lines)
