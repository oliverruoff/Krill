"""Base integration protocol and config field model for optional connectors."""

from typing import Literal, Protocol

from pydantic import BaseModel


class IntegrationConfigField(BaseModel):
    id: str
    label: str
    type: Literal["text", "password", "select", "textarea"] = "text"
    required: bool = False
    placeholder: str = ""
    description: str = ""


class IntegrationPlugin(Protocol):
    integration_id: str
    display_name: str
    description: str
    config_fields: list[IntegrationConfigField]

    async def verify(self, params: dict[str, str]) -> tuple[bool, str]:
        ...

    def start(self) -> None:
        ...

    async def stop(self) -> None:
        ...
