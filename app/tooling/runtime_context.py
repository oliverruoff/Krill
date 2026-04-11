"""Per-request runtime context shared with MCP plugins during orchestration."""

from contextvars import ContextVar, Token
from typing import TypedDict

from .execution import CancellationToken, build_conversation_key


class RuntimeContext(TypedDict):
    source_channel: str
    source_chat_id: str
    source_request_id: str
    conversation_key: str
    cancellation_token: CancellationToken | None


_RUNTIME_CONTEXT: ContextVar[RuntimeContext] = ContextVar(
    "runtime_context",
    default={
        "source_channel": "gateway",
        "source_chat_id": "",
        "source_request_id": "",
        "conversation_key": "gateway:",
        "cancellation_token": None,
    },
)


def set_runtime_context(
    *,
    source_channel: str,
    source_chat_id: str,
    source_request_id: str = "",
    cancellation_token: CancellationToken | None = None,
) -> Token[RuntimeContext]:
    payload: RuntimeContext = {
        "source_channel": str(source_channel or "gateway").strip() or "gateway",
        "source_chat_id": str(source_chat_id or "").strip(),
        "source_request_id": str(source_request_id or "").strip(),
        "conversation_key": build_conversation_key(source_channel, source_chat_id),
        "cancellation_token": cancellation_token,
    }
    return _RUNTIME_CONTEXT.set(payload)


def reset_runtime_context(token: Token[RuntimeContext]) -> None:
    _RUNTIME_CONTEXT.reset(token)


def get_runtime_context() -> RuntimeContext:
    return _RUNTIME_CONTEXT.get()


def get_cancellation_token() -> CancellationToken | None:
    return _RUNTIME_CONTEXT.get().get("cancellation_token")
