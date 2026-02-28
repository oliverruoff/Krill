"""Public integration registry exports consumed by API startup and validation."""


def get_integration(integration_id: str):
    from .registry import get_integration as _get_integration

    return _get_integration(integration_id)


def get_integration_options():
    from .registry import get_integration_options as _get_integration_options

    return _get_integration_options()


def get_runtime_integrations():
    from .registry import get_runtime_integrations as _get_runtime_integrations

    return _get_runtime_integrations()


def is_supported_integration(integration_id: str) -> bool:
    from .registry import is_supported_integration as _is_supported_integration

    return _is_supported_integration(integration_id)


__all__ = ["get_integration", "get_integration_options", "get_runtime_integrations", "is_supported_integration"]
