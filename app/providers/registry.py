from .base import LLMProvider
from .dummy import DummyProvider


_PROVIDERS: dict[str, LLMProvider] = {
    "dummy": DummyProvider(),
}


def is_supported_provider(provider_id: str) -> bool:
    return provider_id in _PROVIDERS


def get_provider_options() -> list[dict[str, str]]:
    options: list[dict[str, str]] = []

    for provider in _PROVIDERS.values():
        options.append({"id": provider.provider_id, "label": provider.display_name})

    return options
