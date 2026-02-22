"""Helpers for building the runtime system prompt injected into model calls."""

def compose_runtime_system_prompt(bot_name: str, system_prompt: str, memory_block: str = "") -> str:
    invisible_context = (
        f"You are Krill assistant named '{bot_name}'. "
        f"This is the system prompt your user provided: {system_prompt}"
    )

    if memory_block.strip():
        invisible_context = f"{invisible_context}\n\nCompacted conversation memory:\n{memory_block.strip()}"

    return invisible_context
