"""Thin wrapper helpers for execution validation gates."""

from __future__ import annotations

from .execution import TaskIntent, ValidationResult, validate_tool_result

__all__ = ["TaskIntent", "ValidationResult", "validate_tool_result"]
