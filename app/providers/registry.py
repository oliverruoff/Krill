"""Registry for available LLM providers and provider metadata helpers."""

from .base import LLMProvider
from .gemini import GeminiProvider
from .gemini_oauth import GeminiOAuthProvider
from .openai_codex_oauth import OpenAICodexOAuthProvider
from .openai import OpenAIProvider
from .openrouter import OpenRouterProvider


_PROVIDERS: dict[str, LLMProvider] = {
    "gemini": GeminiProvider(),
    "google_gemini_oauth": GeminiOAuthProvider(),
    "openai": OpenAIProvider(),
    "openai_codex_oauth": OpenAICodexOAuthProvider(),
    "openrouter": OpenRouterProvider(),
}


def is_supported_provider(provider_id: str) -> bool:
    return provider_id in _PROVIDERS


def get_provider_options() -> list[dict[str, object]]:
    options: list[dict[str, object]] = []

    for provider in _PROVIDERS.values():
        options.append(
            {
                "id": provider.provider_id,
                "label": provider.display_name,
                "api_key_url": provider.api_key_url,
                "auth_mode": str(getattr(provider, "auth_mode", "api_key") or "api_key"),
                "models": provider.available_models,
            }
        )

    return options


def get_provider_model_ids(provider_id: str) -> set[str]:
    provider = _PROVIDERS.get(provider_id)

    if provider is None:
        return set()

    model_ids: set[str] = set()

    for model in provider.available_models:
        model_id = model.get("id")
        if isinstance(model_id, str):
            model_ids.add(model_id)

    return model_ids


def get_provider_model_limit(provider_id: str, model_id: str) -> int | None:
    provider = _PROVIDERS.get(provider_id)
    if provider is None:
        return None

    for model in provider.available_models:
        if model.get("id") != model_id:
            continue

        token_limit = model.get("token_limit")
        if isinstance(token_limit, int) and token_limit > 0:
            return token_limit

    return None


def get_provider_model_supports_images(provider_id: str, model_id: str) -> bool:
    provider = _PROVIDERS.get(provider_id)
    if provider is None:
        return False

    for model in provider.available_models:
        if model.get("id") != model_id:
            continue
        return bool(model.get("supports_images", False))

    return False


def get_provider(provider_id: str) -> LLMProvider | None:
    return _PROVIDERS.get(provider_id)
