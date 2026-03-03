"""Base integration protocol and config field model for optional connectors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.config import Settings, TimedJob


class IntegrationConfigField(BaseModel):
    id: str
    label: str
    type: Literal["text", "password", "select", "textarea"] = "text"
    required: bool = False
    placeholder: str = ""
    description: str = ""


class IntegrationPlugin(ABC):
    integration_id: str
    display_name: str
    description: str
    config_fields: list[IntegrationConfigField]

    @abstractmethod
    async def verify(self, params: dict[str, str]) -> tuple[bool, str]:
        ...

    @abstractmethod
    def start(self) -> None:
        ...

    @abstractmethod
    async def stop(self) -> None:
        ...

    async def dispatch_timed_job(
        self,
        job: "TimedJob",
        text: str,
        settings: "Settings",
    ) -> None:
        """Deliver a timed job result via this integration.

        Default is a no-op. Integrations that support timed job output
        (e.g. Telegram) override this method.

        Args:
            job: The timed job that was executed.
            text: The formatted output text to deliver.
            settings: Current application settings.
        """

    def get_timed_job_channel_option(
        self,
        settings: "Settings",
    ) -> dict[str, object] | None:
        """Return a channel option dict for the timed job channel picker UI.

        Return None if this integration does not support timed job dispatch.
        Integrations that override dispatch_timed_job should also override this
        to expose availability and description for the UI.

        Args:
            settings: Current application settings.

        Returns:
            A dict with keys: id, label, description, available, default.
            Or None if this integration has no timed job channel.
        """
        return None
