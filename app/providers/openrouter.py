import asyncio
import json
from urllib import error, request

from .base import LLMProvider


class OpenRouterProvider(LLMProvider):
    provider_id = "openrouter"
    display_name = "OpenRouter"
    api_key_url = "https://openrouter.ai/keys"
    available_models = [
        {"id": "free", "label": "Free", "token_limit": 200000},
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
        }

        try:
            response_body = await asyncio.to_thread(_post_json_return_body, payload, cleaned_api_key)
        except error.HTTPError as exc:
            response_text = _safe_read_error(exc)
            raise RuntimeError(f"OpenRouter request failed ({exc.code}): {response_text}") from exc
        except error.URLError as exc:
            raise RuntimeError("Network error while contacting OpenRouter.") from exc
        except Exception as exc:
            raise RuntimeError("Unexpected error while contacting OpenRouter.") from exc

        text = _extract_text(response_body)
        if not text:
            raise RuntimeError("OpenRouter returned an empty response.")

        used_tokens = _extract_total_tokens(response_body)
        return text, used_tokens

    async def verify(self, model: str, api_key: str) -> tuple[bool, str]:
        cleaned_api_key = api_key.strip()
        if not cleaned_api_key:
            return False, "API key is required."

        payload = {
            "model": _resolve_model(model),
            "messages": [{"role": "user", "content": "Health check."}],
            "max_tokens": 16,
        }

        try:
            status_code = await asyncio.to_thread(_post_json_status, payload, cleaned_api_key)
        except error.HTTPError as exc:
            response_text = _safe_read_error(exc)
            if exc.code == 401:
                return False, "OpenRouter rejected the API key."
            if exc.code == 403:
                detail = _extract_error_detail(response_text)
                return False, f"OpenRouter request was forbidden: {detail}"

            return False, f"OpenRouter verification failed ({exc.code}): {response_text}"
        except error.URLError:
            return False, "Network error while contacting OpenRouter."
        except Exception:
            return False, "Unexpected error while verifying OpenRouter credentials."

        if status_code == 200:
            return True, "OpenRouter credentials verified."

        return False, f"OpenRouter returned unexpected status code {status_code}."


def _resolve_model(model: str) -> str:
    resolved = model.strip()
    if not resolved:
        return "openrouter/free"

    lowered = resolved.lower()
    if lowered == "free":
        return "openrouter/free"

    if lowered in {"openrouter/free", "openrouter/auto"}:
        return lowered

    return resolved


def _build_messages(history: list[dict[str, str]], prompt: str, system_prompt: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []

    if system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt})

    for item in history:
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str) or not content.strip():
            continue
        messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": prompt})
    return messages


def _post_json_status(payload: dict[str, object], api_key: str) -> int:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url="https://openrouter.ai/api/v1/chat/completions",
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
        url="https://openrouter.ai/api/v1/chat/completions",
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
        return content.strip()

    return ""


def _extract_total_tokens(payload: dict[str, object]) -> int | None:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None

    total = usage.get("total_tokens")
    if isinstance(total, int):
        return total

    return None


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
