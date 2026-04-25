"""Brain Access MCP plugin for memories, chats, settings, and braindump inspection."""

from datetime import datetime, timezone
import json
import logging
from typing import Any

from app.config import (
    MemoryEntry,
    Settings,
    load_settings,
    read_braindump_table,
    save_settings,
    view_braindump,
)
from app.providers import get_provider
from app.providers.resilience import generate_with_retries

from .base import MCPPlugin, McpConfigField, McpToolSpec


LOGGER = logging.getLogger(__name__)


class BrainAccessMCP(MCPPlugin):
    mcp_id = "brain_access"
    display_name = "Brain Access"
    description = (
        "Use this for memory-grounded recall, memory writes, chat and config reads, braindump inspection, "
        "and assistant behavior updates."
    )
    default_enabled = True
    config_fields: list[McpConfigField] = []

    def tool_specs(self) -> list[McpToolSpec]:
        return [
            McpToolSpec(
                id="lookup_memories",
                label="Lookup Memories",
                description=(
                    "Loads all stored core and normal memories, evaluates whether they answer the current "
                    "user question, and returns a grounded answer with evidence or an explicit cannot-answer result."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "minLength": 1},
                    },
                    "required": ["question"],
                },
            ),
            McpToolSpec(
                id="save_memory",
                label="Save Memory",
                description=(
                    "Stores a new memory for future conversations. Use this when the user asks to remember "
                    "something (for example: remember, don't forget, memorize, keep this in mind), regardless of language. "
                    "If the user explicitly asks for a core or normal memory, pass that value as memory_type."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "memory_text": {"type": "string", "minLength": 1},
                        "memory_type": {
                            "type": "string",
                            "enum": ["core", "normal"],
                            "description": (
                                "Optional memory type. Set to core or normal whenever the user explicitly asks "
                                "for that memory type in any language. If omitted, the tool semantically parses "
                                "the request, then classifies the memory."
                            ),
                        },
                    },
                    "required": ["memory_text"],
                },
            ),
            McpToolSpec(
                id="read_all_configs",
                label="Read All Configs",
                description="Returns the full application settings snapshot with sensitive values masked.",
                input_schema={"type": "object", "properties": {}},
            ),
            McpToolSpec(
                id="inspect_braindump",
                label="Inspect Braindump",
                description="Returns all braindump tables, schema details, row counts, and masked rows.",
                input_schema={"type": "object", "properties": {}},
            ),
            McpToolSpec(
                id="read_braindump_table",
                label="Read Braindump Table",
                description="Reads one braindump table with pagination and masked sensitive values.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "table_name": {"type": "string", "minLength": 1},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                        "offset": {"type": "integer", "minimum": 0},
                    },
                    "required": ["table_name"],
                },
            ),
            McpToolSpec(
                id="list_chats",
                label="List Chats",
                description="Returns all stored chats as lightweight summaries.",
                input_schema={"type": "object", "properties": {}},
            ),
            McpToolSpec(
                id="read_chat",
                label="Read Chat",
                description="Returns one stored chat, including messages, with optional pagination.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "chat_id": {"type": "string", "minLength": 1},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                        "offset": {"type": "integer", "minimum": 0},
                    },
                    "required": ["chat_id"],
                },
            ),
            McpToolSpec(
                id="search_chats",
                label="Search Chats",
                description="Searches stored chat titles and messages for a text query.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "minLength": 1},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                    },
                    "required": ["query"],
                },
            ),
            McpToolSpec(
                id="read_assistant_behavior",
                label="Read Assistant Behavior",
                description="Returns the current assistant behavior/system prompt.",
                input_schema={"type": "object", "properties": {}},
            ),
            McpToolSpec(
                id="update_assistant_behavior",
                label="Update Assistant Behavior",
                description="Updates the assistant behavior/system prompt stored in settings.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "behavior": {"type": "string", "minLength": 1},
                    },
                    "required": ["behavior"],
                },
            ),
        ]

    async def verify(self, params: dict[str, str]) -> tuple[bool, str]:
        return True, "Brain Access MCP is ready without setup."

    async def call_tool(self, tool_id: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
        del params
        if tool_id == "lookup_memories":
            return await _lookup_memories(arguments)
        if tool_id == "save_memory":
            return await _save_memory(arguments)
        if tool_id == "read_all_configs":
            return await _read_all_configs()
        if tool_id == "inspect_braindump":
            return await _inspect_braindump()
        if tool_id == "read_braindump_table":
            return await _read_braindump_table(arguments)
        if tool_id == "list_chats":
            return await _list_chats()
        if tool_id == "read_chat":
            return await _read_chat(arguments)
        if tool_id == "search_chats":
            return await _search_chats(arguments)
        if tool_id == "read_assistant_behavior":
            return await _read_assistant_behavior()
        if tool_id == "update_assistant_behavior":
            return await _update_assistant_behavior(arguments)
        raise RuntimeError(f"Unsupported Brain Access tool: {tool_id}")

    def tool_call_system_reminder(self, tool_id: str, params: dict[str, str]) -> str:
        del params
        if tool_id == "save_memory":
            return (
                "Memory-save intent is language-agnostic; trigger save_memory based on semantic intent, not specific keywords. "
                "When saving memory: provide the memory text. If the user semantically asks for core or normal memory "
                "in any language, pass memory_type exactly as requested. If the user does not specify a type, omit "
                "memory_type and the system will parse/classify it."
            )
        if tool_id == "update_assistant_behavior":
            return (
                "Use update_assistant_behavior only when the user explicitly asks to change the assistant's behavior, tone, "
                "or standing instructions for future conversations."
            )
        return ""


async def _read_all_configs() -> dict[str, object]:
    settings = await load_settings()
    return {
        "ok": True,
        "configs": _mask_sensitive_in_structure(settings.model_dump()),
    }


async def _inspect_braindump() -> dict[str, object]:
    return await view_braindump(show_secrets=False)


async def _read_braindump_table(arguments: dict[str, object]) -> dict[str, object]:
    table_name = arguments.get("table_name")
    if not isinstance(table_name, str) or not table_name.strip():
        raise RuntimeError("Read Braindump Table requires a non-empty 'table_name'.")
    limit = _coerce_int(arguments.get("limit"), default=100, minimum=1, maximum=500)
    offset = _coerce_int(arguments.get("offset"), default=0, minimum=0, maximum=1000000)
    try:
        return await read_braindump_table(table_name=table_name.strip(), limit=limit, offset=offset, show_secrets=False)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc


async def _list_chats() -> dict[str, object]:
    settings = await load_settings()
    chats = [_chat_summary(chat.model_dump()) for chat in settings.chats]
    return {
        "ok": True,
        "chat_count": len(chats),
        "active_chat_id": settings.active_chat_id,
        "chats": chats,
    }


async def _read_chat(arguments: dict[str, object]) -> dict[str, object]:
    chat_id = arguments.get("chat_id")
    if not isinstance(chat_id, str) or not chat_id.strip():
        raise RuntimeError("Read Chat requires a non-empty 'chat_id'.")

    limit = _coerce_int(arguments.get("limit"), default=200, minimum=1, maximum=500)
    offset = _coerce_int(arguments.get("offset"), default=0, minimum=0, maximum=1000000)
    settings = await load_settings()
    chat = next((item for item in settings.chats if item.id == chat_id.strip()), None)
    if chat is None:
        raise RuntimeError(f"Unknown chat_id: {chat_id.strip()}")

    total_messages = len(chat.messages)
    sliced_messages = chat.messages[offset : offset + limit]
    return {
        "ok": True,
        "chat": {
            "id": chat.id,
            "title": chat.title,
            "type": chat.type,
            "memory_block": chat.memory_block,
            "total_tokens_used": chat.total_tokens_used,
            "collapse_system_trace": chat.collapse_system_trace,
            "hidden_from_history": chat.hidden_from_history,
            "message_count": total_messages,
            "returned_messages": len(sliced_messages),
            "offset": offset,
            "limit": limit,
            "messages": [message.model_dump() for message in sliced_messages],
        },
    }


async def _search_chats(arguments: dict[str, object]) -> dict[str, object]:
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        raise RuntimeError("Search Chats requires a non-empty 'query'.")

    normalized_query = query.strip().lower()
    limit = _coerce_int(arguments.get("limit"), default=20, minimum=1, maximum=100)
    settings = await load_settings()
    matches: list[dict[str, object]] = []

    for chat in settings.chats:
        title_match = normalized_query in chat.title.lower()
        snippet = ""
        message_role = ""
        message_timestamp = ""
        for message in chat.messages:
            if normalized_query in message.content.lower():
                snippet = _build_snippet(message.content, query.strip())
                message_role = message.role
                message_timestamp = message.timestamp
                break
        if not title_match and not snippet:
            continue
        matches.append(
            {
                "chat_id": chat.id,
                "title": chat.title,
                "matched_title": title_match,
                "matched_message_role": message_role,
                "matched_message_timestamp": message_timestamp,
                "snippet": snippet,
            }
        )
        if len(matches) >= limit:
            break

    return {
        "ok": True,
        "query": query.strip(),
        "match_count": len(matches),
        "matches": matches,
    }


async def _read_assistant_behavior() -> dict[str, object]:
    settings = await load_settings()
    return {
        "ok": True,
        "behavior": settings.system_prompt,
        "max_length": _behavior_max_length(),
    }


async def _update_assistant_behavior(arguments: dict[str, object]) -> dict[str, object]:
    behavior = arguments.get("behavior")
    if not isinstance(behavior, str) or not behavior.strip():
        raise RuntimeError("Update Assistant Behavior requires a non-empty 'behavior'.")

    normalized_behavior = behavior.strip()
    max_length = _behavior_max_length()
    if len(normalized_behavior) > max_length:
        raise RuntimeError(f"Behavior must be {max_length} characters or fewer.")

    settings = await load_settings()
    previous_behavior = settings.system_prompt
    settings.system_prompt = normalized_behavior
    persisted = await save_settings(settings)
    return {
        "ok": True,
        "status": "updated",
        "previous_behavior": previous_behavior,
        "behavior": persisted.system_prompt,
    }


async def _lookup_memories(arguments: dict[str, object]) -> dict[str, object]:
    question = arguments.get("question")
    if not isinstance(question, str) or not question.strip():
        raise RuntimeError("Brain Access tool requires a non-empty 'question'.")
    question_text = question.strip()

    settings = await load_settings()
    provider_id = settings.active_provider_id.strip()
    if not provider_id:
        raise RuntimeError("Active provider is not configured.")

    provider_config = settings.provider_configs.get(provider_id)
    if provider_config is None:
        raise RuntimeError("Active provider config is missing.")

    model_id = provider_config.model.strip()
    api_key = provider_config.api_key
    if not model_id:
        raise RuntimeError("Active provider model is missing.")
    if not api_key.strip():
        raise RuntimeError("Active provider API key is missing.")

    provider = get_provider(provider_id)
    if provider is None:
        raise RuntimeError("Active provider is unavailable.")

    core_memories = [m.content.strip() for m in settings.core_memories if isinstance(m.content, str) and m.content.strip()]
    normal_memories = [m.content.strip() for m in settings.normal_memories if isinstance(m.content, str) and m.content.strip()]

    memory_payload = {
        "core_memories": core_memories,
        "normal_memories": normal_memories,
    }
    prompt = _build_lookup_prompt(question_text, memory_payload)
    system_prompt = (
        "You are a memory-grounding verifier. "
        "Only use the provided memories as evidence. "
        "Return JSON only with no markdown."
    )

    response_text, used_tokens = await generate_with_retries(
        provider=provider,
        prompt=prompt,
        system_prompt=system_prompt,
        model=model_id,
        api_key=api_key,
        history=[],
    )

    parsed = _parse_json_object(response_text)
    can_answer = bool(parsed.get("can_answer"))
    raw_answer = parsed.get("answer")
    answer = raw_answer if isinstance(raw_answer, str) else ""
    evidence = _normalize_string_list(parsed.get("evidence"))

    if not can_answer:
        answer = "I cannot answer this from stored memories."
        evidence = []

    return {
        "question": question_text,
        "can_answer": can_answer,
        "answer": _clean_text(answer),
        "evidence": evidence,
        "memory_counts": {
            "core": len(core_memories),
            "normal": len(normal_memories),
            "total": len(core_memories) + len(normal_memories),
        },
        "used_tokens": used_tokens,
    }


async def _save_memory(arguments: dict[str, object]) -> dict[str, object]:
    raw_memory_text = arguments.get("memory_text")
    if not isinstance(raw_memory_text, str) or not raw_memory_text.strip():
        raw_memory_text = arguments.get("text")
    if not isinstance(raw_memory_text, str) or not raw_memory_text.strip():
        raw_memory_text = arguments.get("content")
    if not isinstance(raw_memory_text, str) or not raw_memory_text.strip():
        raw_memory_text = arguments.get("memory")
    if not isinstance(raw_memory_text, str) or not raw_memory_text.strip():
        raise RuntimeError("Save Memory requires a non-empty 'memory_text'.")

    explicit_type = _coerce_memory_type(arguments.get("memory_type"))
    semantic_parse = await _parse_memory_save_request_via_llm(raw_memory_text)
    semantic_text = _clean_text(semantic_parse.get("memory_text"))
    semantic_type = _coerce_memory_type(semantic_parse.get("requested_memory_type"))
    requested_type = explicit_type or semantic_type or _infer_requested_memory_type_from_text(raw_memory_text)
    memory_text = semantic_text or _clean_text(_strip_memory_intent_prefix(raw_memory_text))
    if not memory_text:
        raise RuntimeError("Save Memory requires a non-empty 'memory_text'.")

    inferred_type = "normal"
    inference_reason = "Defaulted to normal memory."
    confidence = "default"
    if requested_type:
        target_type = requested_type
        inferred_type = target_type
        confidence = "explicit"
        if explicit_type:
            inference_reason = "Memory type provided explicitly by tool arguments."
        elif semantic_type:
            inference_reason = _clean_text(semantic_parse.get("reason")) or "Memory type inferred semantically from explicit user request."
        else:
            inference_reason = "Memory type inferred from fallback explicit wording in memory_text."
    else:
        inferred_type, confidence, inference_reason = await _infer_memory_type_via_llm(memory_text)
        target_type = inferred_type

    settings = await load_settings()
    existing_map = _existing_memory_lookup(settings)
    key = memory_text.lower()
    existing_type = existing_map.get(key)
    if existing_type:
        return {
            "ok": True,
            "status": "duplicate_skipped",
            "memory_text": memory_text,
            "memory_type": existing_type,
            "reason": "Memory already exists.",
            "decision": {
                "inferred_type": inferred_type,
                "confidence": confidence,
                "inference_reason": inference_reason,
            },
            "memory_counts": {
                "core": len(settings.core_memories),
                "normal": len(settings.normal_memories),
                "total": len(settings.core_memories) + len(settings.normal_memories),
            },
        }

    entry = MemoryEntry(content=memory_text, created_at=datetime.now(timezone.utc).isoformat())
    if target_type == "core":
        settings.core_memories.append(entry)
    else:
        settings.normal_memories.append(entry)

    persisted = await save_settings(settings)
    return {
        "ok": True,
        "status": "saved",
        "memory_text": memory_text,
        "memory_type": target_type,
        "decision": {
            "inferred_type": inferred_type,
            "confidence": confidence,
            "inference_reason": inference_reason,
        },
        "memory_counts": {
            "core": len(persisted.core_memories),
            "normal": len(persisted.normal_memories),
            "total": len(persisted.core_memories) + len(persisted.normal_memories),
        },
    }


def _chat_summary(chat: dict[str, object]) -> dict[str, object]:
    messages = chat.get("messages")
    message_count = len(messages) if isinstance(messages, list) else 0
    latest_timestamp = ""
    if isinstance(messages, list):
        for message in reversed(messages):
            if not isinstance(message, dict):
                continue
            timestamp = str(message.get("timestamp", "") or "").strip()
            if timestamp:
                latest_timestamp = timestamp
                break
    return {
        "id": str(chat.get("id", "") or ""),
        "title": str(chat.get("title", "") or ""),
        "type": str(chat.get("type", "") or ""),
        "message_count": message_count,
        "total_tokens_used": int(chat.get("total_tokens_used", 0) or 0),
        "collapse_system_trace": bool(chat.get("collapse_system_trace", False)),
        "hidden_from_history": bool(chat.get("hidden_from_history", False)),
        "latest_timestamp": latest_timestamp,
    }


def _mask_sensitive_in_structure(value: object, parent_key: str = "") -> object:
    if isinstance(value, dict):
        masked: dict[str, object] = {}
        for key, nested_value in value.items():
            normalized_key = str(key)
            if _is_sensitive_key(normalized_key):
                masked[normalized_key] = _mask_value(nested_value)
            else:
                masked[normalized_key] = _mask_sensitive_in_structure(nested_value, normalized_key)
        return masked
    if isinstance(value, list):
        return [_mask_sensitive_in_structure(item, parent_key) for item in value]
    if _is_sensitive_key(parent_key):
        return _mask_value(value)
    return value


def _is_sensitive_key(key: str) -> bool:
    lowered = str(key or "").strip().lower()
    return any(token in lowered for token in ("api_key", "token", "secret", "password", "private_key", "ssh_private"))


def _build_snippet(content: str, query: str, radius: int = 80) -> str:
    if not content.strip():
        return ""
    lowered_content = content.lower()
    lowered_query = query.lower()
    index = lowered_content.find(lowered_query)
    if index == -1:
        return _clean_text(content)[: radius * 2]
    start = max(0, index - radius)
    end = min(len(content), index + len(query) + radius)
    snippet = content[start:end].strip()
    if start > 0:
        snippet = f"...{snippet}"
    if end < len(content):
        snippet = f"{snippet}..."
    return _clean_text(snippet)


def _coerce_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float) and value.is_integer():
        parsed = int(value)
    elif isinstance(value, str) and value.strip():
        try:
            parsed = int(value.strip())
        except ValueError:
            return default
    else:
        return default
    return max(minimum, min(parsed, maximum))


def _behavior_max_length() -> int:
    field_info = Settings.model_fields.get("system_prompt")
    if field_info is None:
        return 400
    for metadata in field_info.metadata:
        max_length = getattr(metadata, "max_length", None)
        if isinstance(max_length, int) and max_length > 0:
            return max_length
    return 400


def _mask_value(value: object) -> object:
    if value is None:
        return None
    text = str(value)
    if not text:
        return ""
    if len(text) <= 4:
        return "****"
    return f"{text[:2]}***{text[-2:]}"


def _build_lookup_prompt(question: str, memories: dict[str, list[str]]) -> str:
    return (
        "You are given a user question and stored memories.\n"
        "Determine whether the question can be answered from these memories.\n"
        "Do not invent facts or infer beyond explicit memory content.\n"
        "If the memories are insufficient, set can_answer to false.\n"
        "Return JSON only with this schema:\n"
        '{"can_answer": true|false, "answer": "...", "evidence": ["exact memory line", "..."]}\n\n'
        f"User question:\n{question}\n\n"
        f"Memories:\n{json.dumps(memories, ensure_ascii=True)}"
    )


def _parse_json_object(raw_text: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw_text)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass

    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {"can_answer": False, "answer": "", "evidence": []}

    candidate = raw_text[start : end + 1]
    try:
        payload = json.loads(candidate)
        if isinstance(payload, dict):
            return payload
    except Exception:
        return {"can_answer": False, "answer": "", "evidence": []}

    return {"can_answer": False, "answer": "", "evidence": []}


def _normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []

    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        cleaned = _clean_text(item)
        if cleaned:
            normalized.append(cleaned)
    return normalized


def _clean_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).strip()


def _coerce_memory_type(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip().lower()
    if normalized in {"core", "normal"}:
        return normalized
    return ""


async def _parse_memory_save_request_via_llm(raw_text: str) -> dict[str, str]:
    """Extract memory content and explicit requested type semantically.

    This is intentionally language-agnostic and asks the active model to interpret
    the user's request instead of expanding keyword lists for each language.
    """
    try:
        settings = await load_settings()
        provider_id = settings.active_provider_id.strip()
        if not provider_id:
            return {}
        provider_config = settings.provider_configs.get(provider_id)
        if provider_config is None or not provider_config.model.strip() or not provider_config.api_key.strip():
            return {}
        provider = get_provider(provider_id)
        if provider is None:
            return {}

        prompt = (
            "Analyze this memory-save tool input semantically in any language.\n"
            "Extract the actual memory content that should be stored, removing command wording like requests to remember, "
            "save, store, not forget, or instructions about whether the memory is core/normal.\n"
            "If the user explicitly requested the memory type, set requested_memory_type to \"core\" or \"normal\". "
            "Do not classify the content yourself for this field; only use an explicit user request. "
            "If no type was explicitly requested, use an empty string.\n"
            "Keep the memory content in the user's original meaning/language unless the input already uses a third-person form.\n"
            "Return JSON only with this schema:\n"
            '{"memory_text":"...", "requested_memory_type":"core|normal|", "confidence":"high|medium|low", "reason":"..."}\n\n'
            f"Input:\n{raw_text}"
        )
        response_text, _ = await generate_with_retries(
            provider=provider,
            prompt=prompt,
            system_prompt="You extract memory-save requests semantically across languages. Return valid JSON only.",
            model=provider_config.model,
            api_key=provider_config.api_key,
            history=[],
            max_attempts=2,
        )
        parsed = _parse_json_object(response_text)
        memory_text = _clean_text(parsed.get("memory_text"))
        requested_type = _coerce_memory_type(parsed.get("requested_memory_type"))
        confidence = str(parsed.get("confidence", "")).strip().lower()
        if confidence not in {"high", "medium", "low"}:
            confidence = ""
        reason = _clean_text(parsed.get("reason"))
        result: dict[str, str] = {}
        if memory_text:
            result["memory_text"] = memory_text
        if requested_type:
            result["requested_memory_type"] = requested_type
        if confidence:
            result["confidence"] = confidence
        if reason:
            result["reason"] = reason
        return result
    except Exception:
        LOGGER.debug("Semantic memory-save parsing failed, falling back to local parsing")
        return {}


def _infer_requested_memory_type_from_text(value: object) -> str:
    if not isinstance(value, str):
        return ""

    lowered = _clean_text(value).lower()
    core_patterns = (
        "as core memory",
        "as a core memory",
        "as core",
        "core memory",
    )
    normal_patterns = (
        "as normal memory",
        "as a normal memory",
        "as normal",
        "normal memory",
    )
    core_index = min((lowered.find(pattern) for pattern in core_patterns if pattern in lowered), default=-1)
    normal_index = min((lowered.find(pattern) for pattern in normal_patterns if pattern in lowered), default=-1)

    if core_index == -1 and normal_index == -1:
        return ""
    if core_index == -1:
        return "normal"
    if normal_index == -1:
        return "core"
    return "core" if core_index < normal_index else "normal"


def _existing_memory_lookup(settings: Settings) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in getattr(settings, "core_memories", []):
        content = _clean_text(getattr(item, "content", ""))
        if content:
            mapping[content.lower()] = "core"
    for item in getattr(settings, "normal_memories", []):
        content = _clean_text(getattr(item, "content", ""))
        if content and content.lower() not in mapping:
            mapping[content.lower()] = "normal"
    return mapping


async def _infer_memory_type_via_llm(text: str) -> tuple[str, str, str]:
    """Classify a memory as core or normal using an LLM call.

    Falls back to the keyword-based heuristic if the LLM call fails.
    Returns (memory_type, confidence, reason).
    """
    try:
        settings = await load_settings()
        provider_id = settings.active_provider_id.strip()
        if not provider_id:
            return _infer_memory_type_from_text_fallback(text)
        provider_config = settings.provider_configs.get(provider_id)
        if provider_config is None or not provider_config.model.strip() or not provider_config.api_key.strip():
            return _infer_memory_type_from_text_fallback(text)
        provider = get_provider(provider_id)
        if provider is None:
            return _infer_memory_type_from_text_fallback(text)

        prompt = (
            "Classify this memory as \"core\" or \"normal\".\n\n"
            "CORE = Timeless facts about the user that are always true and do not expire.\n"
            "Examples: name, birthday, diet, allergies, stable preferences (\"prefers short answers\"), "
            "personality traits, family members, job, location, languages, communication style, long-term goals.\n\n"
            "NORMAL = Time-bound or episodic context that may change or expire.\n"
            "Examples: current projects, recent events, temporary states, tasks, decisions, plans.\n\n"
            f"Memory: \"{text}\"\n\n"
            "Return JSON only: {\"type\": \"core\" or \"normal\", \"confidence\": \"high\" or \"medium\" or \"low\", "
            "\"reason\": \"brief explanation\"}"
        )
        response_text, _ = await generate_with_retries(
            provider=provider,
            prompt=prompt,
            system_prompt="You are a precise memory classifier. Return valid JSON only.",
            model=provider_config.model,
            api_key=provider_config.api_key,
            history=[],
            max_attempts=2,
        )
        parsed = _parse_json_object(response_text)
        inferred_type = str(parsed.get("type", "normal")).strip().lower()
        if inferred_type not in {"core", "normal"}:
            inferred_type = "normal"
        confidence = str(parsed.get("confidence", "medium")).strip().lower()
        if confidence not in {"high", "medium", "low"}:
            confidence = "medium"
        reason = str(parsed.get("reason", "")).strip() or "LLM classification."
        return inferred_type, confidence, reason
    except Exception:
        LOGGER.debug("LLM memory type inference failed, falling back to keyword heuristic")
        return _infer_memory_type_from_text_fallback(text)


def _infer_memory_type_from_text_fallback(text: str) -> tuple[str, str, str]:
    """Keyword-based fallback for memory type inference when LLM is unavailable."""
    lowered = text.lower()
    core_score = 0.0

    strong_identity_markers = [
        "my name is",
        "call me",
        "i am ",
        "i'm ",
        "my pronouns",
    ]
    stable_preference_markers = [
        "i prefer",
        "i like ",
        "i dislike",
        "i hate ",
        "always",
        "never",
        "usually",
    ]
    long_term_constraint_markers = [
        "allergic",
        "do not",
        "don't",
        "must not",
        "cannot",
        "can't",
        "timezone",
        "diet",
        "vegetarian",
        "vegan",
    ]
    temporary_markers = [
        "today",
        "tomorrow",
        "this week",
        "tonight",
        "right now",
        "currently",
        "for now",
    ]

    if any(marker in lowered for marker in strong_identity_markers):
        core_score += 1.4
    if any(marker in lowered for marker in stable_preference_markers):
        core_score += 0.9
    if any(marker in lowered for marker in long_term_constraint_markers):
        core_score += 0.9
    if any(marker in lowered for marker in temporary_markers):
        core_score -= 1.1

    if core_score >= 2.1:
        return "core", "high", "Detected strong long-term identity/preference/constraint markers."
    return "normal", "default", "No high-confidence long-term markers; defaulted to normal memory."


def _strip_memory_intent_prefix(value: str) -> str:
    text = value.strip()
    if not text:
        return ""

    lowered = text.lower()
    separators = [":", "-", "\n"]
    remember_markers = (
        "remember",
        "don't forget",
        "dont forget",
        "memorize",
        "keep this in mind",
    )
    if any(marker in lowered for marker in remember_markers):
        for separator in separators:
            if separator in text:
                tail = text.split(separator, 1)[1].strip()
                if tail:
                    return tail

        prefix_patterns = (
            "please remember",
            "remember",
            "please memorize",
            "memorize",
            "please don't forget",
            "don't forget",
            "please dont forget",
            "dont forget",
            "please keep this in mind",
            "keep this in mind",
        )
        type_phrases = (
            "this as a core memory",
            "this as core memory",
            "this as core",
            "as a core memory",
            "as core memory",
            "as core",
            "this as a normal memory",
            "this as normal memory",
            "this as normal",
            "as a normal memory",
            "as normal memory",
            "as normal",
            "this",
            "that",
            "it",
        )
        lowered_text = text.lower()
        for prefix in prefix_patterns:
            if not lowered_text.startswith(prefix):
                continue
            candidate = text[len(prefix):].strip()
            for phrase in type_phrases:
                if candidate.lower().startswith(phrase):
                    candidate = candidate[len(phrase):].strip()
                    break
            if candidate:
                return candidate
    return text
