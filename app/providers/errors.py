"""Shared provider error types and helpers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ProviderRequestError(RuntimeError):
    """Provider request failed with safe retry/debug metadata."""

    message: str
    provider_id: str = ""
    status_code: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    retry_class: str = "unknown"
    retryable: bool = False
    response_preview: str = ""
    retry_history: list[dict[str, object]] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__init__(self.message)

    @property
    def response_headers(self) -> dict[str, str]:
        return dict(self.headers)
