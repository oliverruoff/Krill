from .base import LLMProvider


class DummyProvider(LLMProvider):
    provider_id = "dummy"
    display_name = "Dummy Provider"
    api_key_url = ""
    available_models = [
        {"id": "dummy-basic", "label": "Dummy Basic", "token_limit": 1000000},
    ]

    async def generate(
        self,
        prompt: str,
        system_prompt: str,
        model: str,
        api_key: str,
        history: list[dict[str, str]],
    ) -> tuple[str, int | None]:
        context_count = len(history)
        text = f"[dummy:{model}] ({context_count} prior messages) {prompt}"
        estimated_tokens = max(1, len((system_prompt + prompt).split()))
        return text, estimated_tokens

    async def verify(self, model: str, api_key: str) -> tuple[bool, str]:
        if model != "dummy-basic":
            return False, "Unsupported dummy model."

        return True, "Dummy provider verified."
