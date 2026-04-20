"""Shared current-context chat summarization helpers."""

from __future__ import annotations

from .config import Settings
from .providers import get_provider
from .providers.resilience import generate_with_retries


async def summarize_chat_context(
    *,
    settings: Settings,
    history: list[dict[str, str]],
    memory_block: str = "",
) -> tuple[str, int | None]:
    active_provider_id = settings.active_provider_id.strip()
    provider_config = settings.provider_configs.get(active_provider_id)
    if provider_config is None:
        raise RuntimeError("Active provider is not configured.")

    provider = get_provider(active_provider_id)
    if provider is None:
        raise RuntimeError("Active provider is unavailable.")

    if not history and not memory_block.strip():
        return "No current chat context is available to summarize.", None

    summary_text, used_tokens = await generate_with_retries(
        provider=provider,
        prompt=_build_summary_prompt(memory_block),
        system_prompt=_summary_system_prompt(),
        model=provider_config.model,
        api_key=provider_config.api_key,
        history=history,
    )
    cleaned = summary_text.strip()
    if not cleaned:
        raise RuntimeError("Provider returned empty summary.")
    return cleaned, used_tokens


def _summary_system_prompt() -> str:
    return (
        "You summarize the current usable chat context for the user. "
        "Be factual, compact, and easy to scan. "
        "Do not invent facts or speculate. "
        "Prefer bullets over prose."
    )


def _build_summary_prompt(memory_block: str) -> str:
    lines = [
        "Summarize the current chat context for the user.",
        "Return plain text only.",
        "Use these sections exactly in this order:",
        "1) Current goal",
        "2) Confirmed context",
        "3) Open questions or pending work",
        "4) Constraints and preferences",
        "Keep each section concise.",
    ]
    if memory_block.strip():
        lines.append("Include this stored chat memory if still relevant:")
        lines.append(memory_block.strip())
    return "\n".join(lines)
