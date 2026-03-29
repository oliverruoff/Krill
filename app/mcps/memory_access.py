"""Memory Access MCP plugin for memory-grounded recall lookups."""

from datetime import datetime, timezone
import json
import logging
from typing import Any

from app.config import MemoryEntry, Settings, load_settings, save_settings
from app.providers import get_provider
from app.providers.resilience import generate_with_retries

from .base import MCPPlugin, McpConfigField, McpToolSpec


LOGGER = logging.getLogger(__name__)


class MemoryAccessMCP(MCPPlugin):
    mcp_id = "memory_access"
    display_name = "Memory Access"
    description = (
        "Use this for memory-grounded recall and memory writes. It helps when a user asks about prior "
        "discussions/what is remembered, or when a user (in any language) asks to remember/memorize/don't forget something "
        "for future conversations."
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
                    "something (for example: remember, don't forget, memorize, keep this in mind), regardless of language."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "memory_text": {"type": "string", "minLength": 1},
                        "memory_type": {
                            "type": "string",
                            "enum": ["core", "normal"],
                            "description": (
                                "Optional memory type. If omitted, defaults to normal unless content is very "
                                "clearly a stable long-term core memory."
                            ),
                        },
                    },
                    "required": ["memory_text"],
                },
            )
        ]

    async def verify(self, params: dict[str, str]) -> tuple[bool, str]:
        return True, "Memory Access MCP is ready without setup."

    async def call_tool(self, tool_id: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
        del params
        if tool_id == "lookup_memories":
            return await _lookup_memories(arguments)
        if tool_id == "save_memory":
            return await _save_memory(arguments)
        raise RuntimeError(f"Unsupported Memory Access tool: {tool_id}")

    def tool_call_system_reminder(self, tool_id: str, params: dict[str, str]) -> str:
        del params
        if tool_id != "save_memory":
            return ""
        return (
            "Memory-save intent is language-agnostic; trigger save_memory based on semantic intent, not specific keywords. "
            "When saving memory: provide the memory text. The system will automatically classify it as core or normal. "
            "You may specify memory_type if you are confident, but it is not required."
        )


async def _lookup_memories(arguments: dict[str, object]) -> dict[str, object]:
    question = arguments.get("question")
    if not isinstance(question, str) or not question.strip():
        raise RuntimeError("Memory Access tool requires a non-empty 'question'.")
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

    memory_text = _clean_text(_strip_memory_intent_prefix(raw_memory_text))
    if not memory_text:
        raise RuntimeError("Save Memory requires a non-empty 'memory_text'.")

    explicit_type = _coerce_memory_type(arguments.get("memory_type"))
    inferred_type = "normal"
    inference_reason = "Defaulted to normal memory."
    confidence = "default"
    if explicit_type:
        target_type = explicit_type
        confidence = "explicit"
        inference_reason = "Memory type provided explicitly by tool arguments."
    else:
        inferred_type, confidence, inference_reason = await _infer_memory_type_via_llm(memory_text)
        target_type = inferred_type

    settings = await load_settings()
    existing_map = _existing_memory_lookup(settings)
    key = memory_text.lower()
    existing_type = existing_map.get(key)
    if existing_type:
        return {
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
    remember_markers = [
        "remember",
        "don't forget",
        "dont forget",
        "memorize",
        "keep this in mind"
    ]
    if any(marker in lowered for marker in remember_markers):
        for separator in separators:
            if separator in text:
                tail = text.split(separator, 1)[1].strip()
                if tail:
                    return tail
    return text
