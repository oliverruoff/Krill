from .base import LLMProvider
from .dummy import DummyProvider
from .gemini import GeminiProvider


_PROVIDERS: dict[str, LLMProvider] = {
    "dummy": DummyProvider(),
    "gemini": GeminiProvider(),
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
                "models": provider.available_models,
            }
        )

    return options


def get_provider_model_ids(provider_id: str) -> set[str]:
    provider = _PROVIDERS.get(provider_id)

    if provider is None:
        return set()

    return {model["id"] for model in provider.available_models}
