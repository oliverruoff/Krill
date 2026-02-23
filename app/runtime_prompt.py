"""Helpers for building the runtime system prompt injected into model calls."""

from datetime import datetime

def compose_runtime_system_prompt(
    bot_name: str,
    system_prompt: str,
    memory_block: str = "",
    core_memories: list[dict[str, str]] | None = None,
) -> str:
    current_local_time = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M")
    invisible_context = (
        f"You are Krill assistant named '{bot_name}'. "
        f"This is the system prompt your user provided: {system_prompt}\n\n"
        f"Current datetime (server local): {current_local_time}\n"
        "Use time context only when relevant; do not mention it unless needed."
    )

    memory_lines: list[str] = []
    if isinstance(core_memories, list):
        for memory in core_memories:
            if not isinstance(memory, dict):
                continue
            content = memory.get("content")
            if not isinstance(content, str):
                continue
            normalized = content.strip()
            if normalized:
                memory_lines.append(f"- {normalized}")

    if memory_lines:
        joined_memory_lines = "\n".join(memory_lines)
        invisible_context = (
            f"{invisible_context}\n\n"
            "Core memories (background context from the user):\n"
            "Use these memories subtly and only when they are relevant and helpful. "
            "Do not repeatedly mention or announce these memories. "
            "Keep the response natural, personal, and context-aware.\n"
            f"{joined_memory_lines}"
        )

    if memory_block.strip():
        invisible_context = f"{invisible_context}\n\nCompacted conversation memory:\n{memory_block.strip()}"

    return invisible_context
