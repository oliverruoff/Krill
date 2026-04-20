"""MiniMax provider implementation."""

import asyncio
import json
import re
from urllib import error, request

from .base import LLMProvider


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
            "temperature": 1.0,
            "top_p": 0.95,
        }

        try:
            response_body = await asyncio.to_thread(_post_json_return_body, payload, cleaned_api_key)
        except error.HTTPError as exc:
            response_text = _safe_read_error(exc)
            raise RuntimeError(f"MiniMax request failed ({exc.code}): {response_text}") from exc
        except error.URLError as exc:
            raise RuntimeError("Network error while contacting MiniMax.") from exc
        except Exception as exc:
            raise RuntimeError("Unexpected error while contacting MiniMax.") from exc

        text = _extract_text(response_body)
        if not text:
            detail = _extract_empty_reason(response_body)
            if detail:
                raise RuntimeError(f"MiniMax returned an empty response. {detail}")
            raise RuntimeError("MiniMax returned an empty response.")

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
            "temperature": 1.0,
            "top_p": 0.95,
        }

        try:
            status_code = await asyncio.to_thread(_post_json_status, payload, cleaned_api_key)
        except error.HTTPError as exc:
            response_text = _safe_read_error(exc)
            if exc.code == 401:
                return False, "MiniMax rejected the API key."
            if exc.code == 403:
                detail = _extract_error_detail(response_text)
                return False, f"MiniMax request was forbidden: {detail}"

            return False, f"MiniMax verification failed ({exc.code}): {response_text}"
        except error.URLError:
            return False, "Network error while contacting MiniMax."
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

    if system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt})

    for item in history:
        role = item.get("role")
        content = item.get("content")
        if role not in {"system", "user", "assistant"} or not isinstance(content, str) or not content.strip():
            continue
        messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": prompt})
    return messages


def _post_json_status(payload: dict[str, object], api_key: str) -> int:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url="https://api.minimax.io/v1/text/chatcompletion_v2",
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


def _post_json_return_body(payload: dict[str, object], api_key: str) -> dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url="https://api.minimax.io/v1/text/chatcompletion_v2",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    with request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _extract_text(payload: dict[str, object]) -> str:
    top_level_content = payload.get("content")
    if isinstance(top_level_content, str):
        sanitized_top_level = _sanitize_visible_text(top_level_content)
        if sanitized_top_level:
            return sanitized_top_level

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return ""

    message = first_choice.get("message")
    if not isinstance(message, dict):
        return ""

    content = message.get("content")
    if isinstance(content, str):
        sanitized = _sanitize_visible_text(content)
        if sanitized:
            return sanitized

    if isinstance(content, list):
        visible_parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "text":
                continue
            text = item.get("text")
            if isinstance(text, str):
                sanitized = _sanitize_visible_text(text)
                if sanitized:
                    visible_parts.append(sanitized)
        combined = "\n".join(visible_parts).strip()
        if combined:
            return combined

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
        first_choice = choices[0]
        if isinstance(first_choice, dict):
            finish_reason = first_choice.get("finish_reason")
            if isinstance(finish_reason, str) and finish_reason.strip():
                details.append(f"Finish reason: {finish_reason.strip()}.")

            message = first_choice.get("message")
            if isinstance(message, dict):
                reasoning_content = message.get("reasoning_content")
                if isinstance(reasoning_content, str) and reasoning_content.strip():
                    details.append("MiniMax returned reasoning content without visible reply text.")

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
