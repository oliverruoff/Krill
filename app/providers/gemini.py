import asyncio
import json
from urllib import error, request

from .base import LLMProvider


class GeminiProvider(LLMProvider):
    provider_id = "gemini"
    display_name = "Google Gemini"
    available_models = [
        {"id": "gemini-3.1-pro-preview", "label": "Gemini 3.1 Pro Preview"},
        {"id": "gemini-3-flash-preview", "label": "Gemini 3 Flash Preview"},
        {"id": "gemini-2.5-pro", "label": "Gemini 2.5 Pro"},
        {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
        {"id": "gemini-2.0-flash", "label": "Gemini 2.0 Flash"},
        {"id": "gemini-1.5-flash", "label": "Gemini 1.5 Flash"},
    ]

    async def generate(self, prompt: str, system_prompt: str, model: str, api_key: str) -> str:
        supported_models = {item["id"] for item in self.available_models}
        if model not in supported_models:
            raise RuntimeError("Unsupported Gemini model.")

        if not api_key.strip():
            raise RuntimeError("API key is required.")

        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "system_instruction": {"parts": [{"text": system_prompt}]},
        }

        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

        try:
            response_body = await asyncio.to_thread(_post_json_return_body, endpoint, payload)
        except error.HTTPError as exc:
            response_text = _safe_read_error(exc)
            raise RuntimeError(f"Gemini request failed ({exc.code}): {response_text}") from exc
        except error.URLError as exc:
            raise RuntimeError("Network error while contacting Gemini.") from exc
        except Exception as exc:
            raise RuntimeError("Unexpected error while contacting Gemini.") from exc

        text = _extract_text(response_body)
        if not text:
            raise RuntimeError("Gemini returned an empty response.")

        return text

    async def verify(self, model: str, api_key: str) -> tuple[bool, str]:
        supported_models = {item["id"] for item in self.available_models}
        if model not in supported_models:
            return False, "Unsupported Gemini model."

        if not api_key.strip():
            return False, "API key is required."

        payload = {
            "contents": [{"parts": [{"text": "Health check."}]}],
            "generationConfig": {"maxOutputTokens": 1},
        }

        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

        try:
            status_code = await asyncio.to_thread(_post_json_status, endpoint, payload)
        except error.HTTPError as exc:
            response_text = _safe_read_error(exc)
            if exc.code in {401, 403}:
                return False, "Gemini rejected the API key."

            return False, f"Gemini verification failed ({exc.code}): {response_text}"
        except error.URLError:
            return False, "Network error while contacting Gemini."
        except Exception:
            return False, "Unexpected error while verifying Gemini credentials."

        if status_code == 200:
            return True, "Gemini credentials verified."

        return False, f"Gemini returned unexpected status code {status_code}."


def _post_json_status(url: str, payload: dict[str, object]) -> int:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with request.urlopen(req, timeout=12) as response:
        response.read()
        return response.status


def _post_json_return_body(url: str, payload: dict[str, object]) -> dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _extract_text(payload: dict[str, object]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""

    first_candidate = candidates[0]
    if not isinstance(first_candidate, dict):
        return ""

    content = first_candidate.get("content")
    if not isinstance(content, dict):
        return ""

    parts = content.get("parts")
    if not isinstance(parts, list):
        return ""

    chunks: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue

        text = part.get("text")
        if isinstance(text, str):
            chunks.append(text)

    return "".join(chunks).strip()


def _safe_read_error(exc: error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="ignore")
    except Exception:
        return "No additional details."
