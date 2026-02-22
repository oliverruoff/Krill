from typing import Protocol

from pydantic import BaseModel


class IntegrationConfigField(BaseModel):
    id: str
    label: str
    type: str = "text"
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
