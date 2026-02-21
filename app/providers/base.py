from typing import Protocol


class LLMProvider(Protocol):
    provider_id: str
    display_name: str
    api_key_url: str
    available_models: list[dict[str, object]]

    async def generate(
        self,
        prompt: str,
        system_prompt: str,
        model: str,
        api_key: str,
        history: list[dict[str, str]],
    ) -> tuple[str, int | None]:
        ...

    async def verify(self, model: str, api_key: str) -> tuple[bool, str]:
        ...
