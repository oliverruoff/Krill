"""Helpers for building the runtime system prompt injected into model calls."""

from datetime import datetime

def compose_runtime_system_prompt(
    memory_block: str = "",
) -> str:
    current_local_time = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M")
    invisible_context = (
        f"Current datetime (server local): {current_local_time}\n"
        "Use time context only when relevant; do not mention it unless needed."
    )

    if memory_block.strip():
        invisible_context = f"{invisible_context}\n\nCompacted conversation memory:\n{memory_block.strip()}"

    return invisible_context
