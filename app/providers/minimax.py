"""MiniMax provider implementation."""

import asyncio
from collections.abc import Mapping
from http.client import RemoteDisconnected
import json
import re
import socket
from urllib import error, request

from .base import LLMProvider
from .errors import ProviderRequestError


class MiniMaxProvider(LLMProvider):
    provider_id = "minimax"
    display_name = "MiniMax"
    api_key_url = "https://platform.minimax.io/user-center/basic-information/interface-key"
    available_models = [
        {"id": "MiniMax-M2.7", "label": "MiniMax-M2.7", "token_limit": 204800, "supports_images": False},
        {"id": "MiniMax-M2.5", "label": "MiniMax-M2.5", "token_limit": 204800, "supports_images": False},
    ]

    async def generate(
        self,
        prompt: str,
        system_prompt: str,
        model: str,
        api_key: str,
        history: list[dict[str, str]],
    ) -> tuple[str, int | None]:
        cleaned_api_key = api_key.strip()
        if not cleaned_api_key:
            raise RuntimeError("API key is required.")

        payload = {
            "model": _resolve_model(model),
            "messages": _build_messages(history, prompt, system_prompt),
            **_sampling_settings_for_request(prompt, system_prompt),
        }
        endpoint = "https://api.minimax.io/v1/text/chatcompletion_v2"

        try:
            response_body = await asyncio.to_thread(_post_json_return_body, endpoint, payload, cleaned_api_key)
        except ProviderRequestError:
            raise
        except error.HTTPError as exc:
            raise _http_error_as_provider_error(exc) from exc
        except error.URLError as exc:
            raise _network_error_from_exception(exc) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise _timeout_error(str(exc) or "Network timeout while contacting MiniMax.") from exc
        except RemoteDisconnected as exc:
            raise ProviderRequestError(
                "Connection dropped while contacting MiniMax.",
                provider_id=self.provider_id,
                retry_class="network",
                retryable=True,
            ) from exc
        except Exception as exc:
            raise ProviderRequestError(
                "Unexpected error while contacting MiniMax.",
                provider_id=self.provider_id,
                retry_class="transient",
                retryable=True,
            ) from exc

        text = _extract_text(response_body)
        if not text:
            await asyncio.sleep(0.2)
            try:
                retry_body = await asyncio.to_thread(_post_json_return_body, endpoint, payload, cleaned_api_key)
            except Exception:
                retry_body = response_body

            text = _extract_text(retry_body)
            if not text:
                detail = _extract_empty_reason(retry_body)
                message = "MiniMax returned an empty response."
                if detail:
                    message = f"{message} {detail}"
                raise ProviderRequestError(
                    message,
                    provider_id=self.provider_id,
                    retry_class="empty_response",
                    retryable=_empty_response_retryable(retry_body),
                    response_preview=_payload_preview(retry_body),
                )
            response_body = retry_body

        used_tokens = _extract_total_tokens(response_body)
        return text, used_tokens

    async def verify(self, model: str, api_key: str) -> tuple[bool, str]:
        cleaned_api_key = api_key.strip()
        if not cleaned_api_key:
            return False, "API key is required."

        payload = {
            "model": _resolve_model(model),
            "messages": [{"role": "user", "content": "Health check."}],
            "max_completion_tokens": 16,
            **_sampling_settings_for_request("Health check.", "verification"),
        }
        endpoint = "https://api.minimax.io/v1/text/chatcompletion_v2"

        try:
            status_code = await asyncio.to_thread(_post_json_status, endpoint, payload, cleaned_api_key)
        except error.HTTPError as exc:
            response_text = _safe_read_error(exc)
            if exc.code == 401:
                return False, "MiniMax rejected the API key."
            if exc.code == 403:
                detail = _extract_error_detail(response_text)
                return False, f"MiniMax request was forbidden: {detail}"
            if exc.code == 429:
                detail = _extract_error_detail(response_text)
                return False, f"MiniMax rate limited the request: {detail}"

            return False, f"MiniMax verification failed ({exc.code}): {response_text}"
        except error.URLError as exc:
            reason = str(getattr(exc, "reason", "") or "").strip()
            detail = f" Details: {reason}" if reason else ""
            return False, f"Network error while contacting MiniMax.{detail}"
        except (TimeoutError, socket.timeout):
            return False, "Network timeout while contacting MiniMax."
        except ProviderRequestError as exc:
            return False, str(exc)
        except Exception:
            return False, "Unexpected error while verifying MiniMax credentials."

        if status_code == 200:
            return True, "MiniMax credentials verified."

        return False, f"MiniMax returned unexpected status code {status_code}."


def _resolve_model(model: str) -> str:
    resolved = model.strip()
    if not resolved:
        return "MiniMax-M2.7"

    return resolved


def _build_messages(history: list[dict[str, str]], prompt: str, system_prompt: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    system_parts: list[str] = []

    if system_prompt.strip():
        system_parts.append(system_prompt.strip())

    for item in history:
        role = item.get("role")
        content = item.get("content")
        if role not in {"system", "user", "assistant"} or not isinstance(content, str) or not content.strip():
            continue
        if role == "system":
            system_parts.append(content.strip())
            continue
        messages.append({"role": role, "content": content})

    if system_parts:
        messages.insert(0, {"role": "system", "content": "\n\n".join(system_parts)})

    messages.append({"role": "user", "content": prompt})
    return messages


def _sampling_settings_for_request(prompt: str, system_prompt: str) -> dict[str, object]:
    if system_prompt.strip().lower() == "verification":
        return {
            "temperature": 0.1,
            "top_p": 0.1,
        }
    if _looks_like_structured_generation(prompt, system_prompt):
        return {
            "temperature": 0.1,
            "top_p": 0.1,
        }
    return {
        "temperature": 0.7,
        "top_p": 0.9,
    }


def _looks_like_structured_generation(prompt: str, system_prompt: str) -> bool:
    combined = f"{system_prompt}\n{prompt}".lower()
    markers = (
        "tool selection phase",
        "return exactly one json object only",
        "no prose, no markdown, no code fences",
        '"action":"call_tool"',
        '"action":"respond"',
    )
    return any(marker in combined for marker in markers)


def _post_json_status(url: str, payload: dict[str, object], api_key: str) -> int:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    with request.urlopen(req, timeout=12) as response:
        response.read()
        return response.status


def _post_json_return_body(url: str, payload: dict[str, object], api_key: str) -> dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    with request.urlopen(req, timeout=30) as response:
        raw_text = response.read().decode("utf-8", errors="replace")

    try:
        payload_data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ProviderRequestError(
            "MiniMax returned malformed JSON.",
            provider_id="minimax",
            retry_class="server_error",
            retryable=True,
            response_preview=_truncate_preview(raw_text),
        ) from exc

    if not isinstance(payload_data, dict):
        raise ProviderRequestError(
            "MiniMax returned an invalid response payload.",
            provider_id="minimax",
            retry_class="server_error",
            retryable=True,
            response_preview=_truncate_preview(raw_text),
        )

    base_resp = payload_data.get("base_resp")
    if isinstance(base_resp, dict):
        status_code = base_resp.get("status_code")
        status_msg = str(base_resp.get("status_msg", "") or "").strip()
        if isinstance(status_code, int) and status_code != 0:
            raise ProviderRequestError(
                _provider_status_message(status_code, status_msg),
                provider_id="minimax",
                status_code=status_code,
                retry_class=_retry_class_for_base_status(status_code),
                retryable=_base_status_retryable(status_code),
                response_preview=_payload_preview(payload_data),
            )

    return payload_data


def _extract_text(payload: dict[str, object]) -> str:
    top_level_content = payload.get("content")
    if isinstance(top_level_content, str):
        sanitized_top_level = _sanitize_visible_text(top_level_content)
        if sanitized_top_level:
            return sanitized_top_level

    top_level_role = payload.get("role")
    if isinstance(top_level_role, str) and top_level_role == "assistant":
        top_level_parts = _extract_text_from_content_value(payload.get("content"))
        if top_level_parts:
            return top_level_parts

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""

    for choice in choices:
        if not isinstance(choice, dict):
            continue

        message = choice.get("message")
        if isinstance(message, dict):
            extracted = _extract_text_from_content_value(message.get("content"))
            if extracted:
                return extracted

        delta = choice.get("delta")
        if isinstance(delta, dict):
            extracted = _extract_text_from_content_value(delta.get("content"))
            if extracted:
                return extracted

    return ""


def _extract_text_from_content_value(content: object) -> str:
    if isinstance(content, str):
        sanitized = _sanitize_visible_text(content)
        if sanitized:
            return sanitized

    if isinstance(content, list):
        visible_parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                sanitized = _sanitize_visible_text(item)
                if sanitized:
                    visible_parts.append(sanitized)
                continue
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type", "") or "").strip().lower()
            if item_type and item_type != "text":
                continue
            text = item.get("text")
            if isinstance(text, str):
                sanitized = _sanitize_visible_text(text)
                if sanitized:
                    visible_parts.append(sanitized)
        combined = "\n".join(visible_parts).strip()
        if combined:
            return combined

    if isinstance(content, dict):
        for key in ("text", "content"):
            value = content.get(key)
            if isinstance(value, str):
                sanitized = _sanitize_visible_text(value)
                if sanitized:
                    return sanitized

    return ""


def _extract_total_tokens(payload: dict[str, object]) -> int | None:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None

    total = usage.get("total_tokens")
    if isinstance(total, int):
        return total

    total = usage.get("output_tokens")
    if isinstance(total, int):
        return total

    return None


def _sanitize_visible_text(content: str) -> str:
    stripped = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL | re.IGNORECASE)
    return stripped.strip()


def _extract_empty_reason(payload: dict[str, object]) -> str:
    base_resp = payload.get("base_resp")
    details: list[str] = []
    if isinstance(base_resp, dict):
        status_code = base_resp.get("status_code")
        status_msg = base_resp.get("status_msg")
        if isinstance(status_code, int) and status_code != 0:
            details.append(f"MiniMax status code: {status_code}.")
        if isinstance(status_msg, str) and status_msg.strip():
            details.append(f"MiniMax status message: {status_msg.strip()}.")

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            finish_reason = choice.get("finish_reason")
            if isinstance(finish_reason, str) and finish_reason.strip():
                details.append(f"Finish reason: {finish_reason.strip()}.")

            message = choice.get("message")
            if isinstance(message, dict):
                reasoning_content = message.get("reasoning_content")
                if isinstance(reasoning_content, str) and reasoning_content.strip():
                    details.append("MiniMax returned reasoning content without visible reply text.")
                    break

    top_level_content = payload.get("content")
    if isinstance(top_level_content, str) and top_level_content.strip():
        details.append("Top-level content was present but no visible reply text could be parsed.")

    return " ".join(details).strip()


def _safe_read_error(exc: error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="ignore")
    except Exception:
        return "No additional details."


def _extract_error_detail(response_text: str) -> str:
    if not response_text.strip():
        return "No additional details."

    try:
        payload = json.loads(response_text)
    except Exception:
        return response_text

    if not isinstance(payload, dict):
        return response_text

    error_payload = payload.get("error")
    if isinstance(error_payload, dict):
        message = error_payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()

    message = payload.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()

    return response_text


def _http_error_as_provider_error(exc: error.HTTPError) -> ProviderRequestError:
    response_text = _safe_read_error(exc)
    detail = _extract_error_detail(response_text)
    if exc.code in {401, 403}:
        message = "MiniMax rejected the API key." if exc.code == 401 else f"MiniMax request was forbidden: {detail}"
        retryable = False
        retry_class = "auth"
    elif exc.code == 429:
        message = f"MiniMax request failed (429): {detail}"
        retryable = True
        retry_class = "rate_limit"
    elif exc.code in {500, 502, 503, 504}:
        message = f"MiniMax request failed ({exc.code}): {detail}"
        retryable = True
        retry_class = "server_error"
    else:
        message = f"MiniMax request failed ({exc.code}): {detail}"
        retryable = False
        retry_class = "http_error"
    return ProviderRequestError(
        message,
        provider_id="minimax",
        status_code=exc.code,
        headers=_normalize_headers(getattr(exc, "headers", None)),
        retry_class=retry_class,
        retryable=retryable,
        response_preview=_truncate_preview(response_text),
    )


def _network_error_from_exception(exc: error.URLError) -> ProviderRequestError:
    reason = str(getattr(exc, "reason", "") or "").strip()
    if isinstance(getattr(exc, "reason", None), TimeoutError):
        return _timeout_error(reason or "Network timeout while contacting MiniMax.")
    message = "Network error while contacting MiniMax."
    if reason:
        message = f"{message} Details: {reason}"
    return ProviderRequestError(
        message,
        provider_id="minimax",
        retry_class="network",
        retryable=True,
    )


def _timeout_error(detail: str) -> ProviderRequestError:
    message = "Network timeout while contacting MiniMax."
    if detail and detail != message:
        message = f"{message} Details: {detail}"
    return ProviderRequestError(
        message,
        provider_id="minimax",
        retry_class="timeout",
        retryable=True,
    )


def _normalize_headers(headers: object) -> dict[str, str]:
    if headers is None:
        return {}
    if isinstance(headers, Mapping):
        return {str(key): str(value) for key, value in headers.items()}
    return {}


def _provider_status_message(status_code: int, status_msg: str) -> str:
    label = "MiniMax returned an error response"
    if status_code == 1001:
        label = "MiniMax request timed out"
    elif status_code == 1002:
        label = "MiniMax rate limited the request"
    elif status_code == 1004:
        label = "MiniMax rejected the API key"
    elif status_code == 1008:
        label = "MiniMax account balance is insufficient"
    elif status_code == 1013:
        label = "MiniMax reported an internal server error"
    elif status_code == 1039:
        label = "MiniMax request exceeded the token limit"
    elif status_code == 2013:
        label = "MiniMax rejected the request parameters"
    if status_msg:
        return f"{label}: {status_msg}"
    return f"{label} (status code {status_code})."


def _retry_class_for_base_status(status_code: int) -> str:
    if status_code == 1002:
        return "rate_limit"
    if status_code == 1001:
        return "timeout"
    if status_code == 1013:
        return "server_error"
    if status_code in {1004, 1008, 2013, 1039}:
        return "invalid_request"
    return "server_error"


def _base_status_retryable(status_code: int) -> bool:
    return status_code in {1001, 1002, 1013}


def _empty_response_retryable(payload: dict[str, object]) -> bool:
    reason = _extract_empty_reason(payload).lower()
    retryable_markers = (
        "reasoning content",
        "status code: 1001",
        "status code: 1002",
        "status code: 1013",
    )
    return any(marker in reason for marker in retryable_markers)


def _payload_preview(payload: dict[str, object]) -> str:
    try:
        raw = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    except Exception:
        raw = str(payload)
    return _truncate_preview(raw)


def _truncate_preview(text: str, limit: int = 500) -> str:
    compact = str(text or "").strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."
