"""OpenAI provider implementation for generation and credential verification."""

import asyncio
import json
from urllib import error, request

from .base import LLMProvider


class OpenAIProvider(LLMProvider):
    provider_id = "openai"
    display_name = "OpenAI"
    api_key_url = "https://platform.openai.com/api-keys"
    available_models = [
        {"id": "gpt-5-nano", "label": "GPT-5 Nano", "token_limit": 400000},
        {"id": "gpt-5-mini", "label": "GPT-5 Mini", "token_limit": 400000},
        {"id": "gpt-5.2", "label": "GPT-5.2", "token_limit": 400000},
    ]

    async def generate(
        self,
        prompt: str,
        system_prompt: str,
        model: str,
        api_key: str,
        history: list[dict[str, str]],
    ) -> tuple[str, int | None]:
        model_id = model.strip()
        if not model_id:
            raise RuntimeError("Model is required.")

        if not api_key.strip():
            raise RuntimeError("API key is required.")

        payload = {
            "model": model_id,
            "input": _build_input(history, prompt, system_prompt),
        }

        try:
            response_body = await asyncio.to_thread(_post_json_return_body, payload, api_key)
        except error.HTTPError as exc:
            response_text = _safe_read_error(exc)
            raise RuntimeError(f"OpenAI request failed ({exc.code}): {response_text}") from exc
        except error.URLError as exc:
            raise RuntimeError("Network error while contacting OpenAI.") from exc
        except Exception as exc:
            raise RuntimeError("Unexpected error while contacting OpenAI.") from exc

        text = _extract_text(response_body)
        if not text:
            raise RuntimeError("OpenAI returned an empty response.")

        used_tokens = _extract_total_tokens(response_body)
        return text, used_tokens

    async def verify(self, model: str, api_key: str) -> tuple[bool, str]:
        model_id = model.strip()
        if not model_id:
            return False, "Model is required."

        if not api_key.strip():
            return False, "API key is required."

        payload = {
            "model": model_id,
            "input": [{"role": "user", "content": "Health check."}],
            "max_output_tokens": 16,
        }

        try:
            status_code = await asyncio.to_thread(_post_json_status, payload, api_key)
        except error.HTTPError as exc:
            response_text = _safe_read_error(exc)
            if exc.code in {401, 403}:
                return False, "OpenAI rejected the API key."

            return False, f"OpenAI verification failed ({exc.code}): {response_text}"
        except error.URLError:
            return False, "Network error while contacting OpenAI."
        except Exception:
            return False, "Unexpected error while verifying OpenAI credentials."

        if status_code == 200:
            return True, "OpenAI credentials verified."

        return False, f"OpenAI returned unexpected status code {status_code}."


def _build_input(history: list[dict[str, str]], prompt: str, system_prompt: str) -> list[dict[str, str]]:
    input_items: list[dict[str, str]] = []

    if system_prompt.strip():
        input_items.append({"role": "system", "content": system_prompt})

    for item in history:
        role = item.get("role")
        content = item.get("content")

        if role not in {"user", "assistant"} or not isinstance(content, str) or not content.strip():
            continue

        input_items.append({"role": role, "content": content})

    input_items.append({"role": "user", "content": prompt})
    return input_items


def _post_json_status(payload: dict[str, object], api_key: str) -> int:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url="https://api.openai.com/v1/responses",
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
        url="https://api.openai.com/v1/responses",
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
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    output = payload.get("output")
    if not isinstance(output, list):
        return ""

    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue

        content = item.get("content")
        if not isinstance(content, list):
            continue

        for part in content:
            if not isinstance(part, dict):
                continue

            if part.get("type") == "output_text":
                text = part.get("text")
                if isinstance(text, str) and text:
                    chunks.append(text)

    return "".join(chunks).strip()


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
