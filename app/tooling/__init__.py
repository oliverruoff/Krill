"""Public tooling exports for orchestrated generation entrypoints."""

from __future__ import annotations

from typing import Any


async def generate_with_tools(*args: Any, **kwargs: Any) -> Any:
    from .orchestrator import generate_with_tools as _generate_with_tools

    return await _generate_with_tools(*args, **kwargs)


__all__ = ["generate_with_tools"]
