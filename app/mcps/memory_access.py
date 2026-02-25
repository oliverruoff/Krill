"""Memory Access MCP plugin for memory-grounded recall lookups."""

import json
from typing import Any

from app.config import load_settings
from app.providers import get_provider
from app.providers.resilience import generate_with_retries

from .base import MCPPlugin, McpConfigField, McpToolSpec


class MemoryAccessMCP(MCPPlugin):
    mcp_id = "memory_access"
    display_name = "Memory Access"
    description = (
        "Use this for memory-grounded recall. It helps when a user asks about prior discussions, "
        "what the assistant remembers, previously shared preferences/facts, or requests that require "
        "retrieving stored memories before answering."
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
            )
        ]

    async def verify(self, params: dict[str, str]) -> tuple[bool, str]:
        return True, "Memory Access MCP is ready without setup."

    async def call_tool(self, tool_id: str, arguments: dict[str, object], params: dict[str, str]) -> dict[str, object]:
        if tool_id != "lookup_memories":
            raise RuntimeError(f"Unsupported Memory Access tool: {tool_id}")

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
