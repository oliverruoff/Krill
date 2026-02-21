from .base import LLMProvider


class DummyProvider(LLMProvider):
    provider_id = "dummy"
    display_name = "Dummy Provider"
    available_models = [
        {"id": "dummy-basic", "label": "Dummy Basic"},
    ]

    async def generate(self, prompt: str, system_prompt: str) -> str:
        return f"[dummy] {prompt}"

    async def verify(self, model: str, api_key: str) -> tuple[bool, str]:
        if model != "dummy-basic":
            return False, "Unsupported dummy model."

        return True, "Dummy provider verified."
