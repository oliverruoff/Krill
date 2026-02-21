from .base import LLMProvider


class DummyProvider(LLMProvider):
    provider_id = "dummy"
    display_name = "Dummy Provider"
    available_models = [
        {"id": "dummy-basic", "label": "Dummy Basic"},
    ]

    async def generate(self, prompt: str, system_prompt: str) -> str:
        return f"[dummy] {prompt}"
