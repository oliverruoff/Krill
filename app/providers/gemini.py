from .base import LLMProvider


class GeminiProvider(LLMProvider):
    provider_id = "gemini"
    display_name = "Google Gemini"
    available_models = [
        {"id": "gemini-3.1-pro", "label": "Gemini 3.1 Pro"},
        {"id": "gemini-3-flash", "label": "Gemini 3 Flash"},
        {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
    ]

    async def generate(self, prompt: str, system_prompt: str) -> str:
        return f"[gemini] {prompt}"
