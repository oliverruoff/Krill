from typing import Protocol


class LLMProvider(Protocol):
    provider_id: str
    display_name: str
    available_models: list[dict[str, str]]

    async def generate(self, prompt: str, system_prompt: str) -> str:
        ...
