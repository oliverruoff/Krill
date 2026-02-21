from typing import Protocol


class LLMProvider(Protocol):
    provider_id: str
    display_name: str

    async def generate(self, prompt: str, system_prompt: str) -> str:
        ...
