"""Google Gemini provider implementation for generation and verification calls."""

import asyncio
import json
from urllib import error, request

from .base import LLMProvider


class GeminiProvider(LLMProvider):
    provider_id = "gemini"
    display_name = "Google Gemini"
    api_key_url = "https://aistudio.google.com/app/apikey"
    available_models = [
        {"id": "gemini-3.1-pro-preview", "label": "Gemini 3.1 Pro Preview", "token_limit": 1048576, "supports_images": True},
        {"id": "gemini-3.1-flash-lite-preview", "label": "Gemini 3.1 Flash Lite Preview", "token_limit": 1048576, "supports_images": True},
        {"id": "gemini-3-flash-preview", "label": "Gemini 3 Flash Preview", "token_limit": 1048576, "supports_images": True},
        {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash", "token_limit": 1048576, "supports_images": True},
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

        contents, system_history_block = _build_contents(history, prompt)
        merged_system_prompt = system_prompt.strip()
        if system_history_block:
            if merged_system_prompt:
                merged_system_prompt = f"{merged_system_prompt}\n\nConversation system context:\n{system_history_block}"
            else:
                merged_system_prompt = f"Conversation system context:\n{system_history_block}"

        payload: dict[str, object] = {"contents": contents}
        if merged_system_prompt:
            payload["system_instruction"] = {"parts": [{"text": merged_system_prompt}]}

        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"

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
            await asyncio.sleep(0.2)
            try:
                retry_body = await asyncio.to_thread(_post_json_return_body, endpoint, payload)
            except Exception:
                retry_body = response_body

            text = _extract_text(retry_body)
            if not text:
                detail = _extract_empty_reason(retry_body)
                if "MALFORMED_FUNCTION_CALL" in detail:
                    fallback_prompt = merged_system_prompt.strip()
                    directive = (
                        "Important: return plain text only. Do not emit functionCall or functionResponse parts."
                    )
                    fallback_prompt = f"{fallback_prompt}\n\n{directive}" if fallback_prompt else directive
                    fallback_payload: dict[str, object] = {"contents": contents}
                    fallback_payload["system_instruction"] = {"parts": [{"text": fallback_prompt}]}
                    try:
                        fallback_body = await asyncio.to_thread(_post_json_return_body, endpoint, fallback_payload)
                        fallback_text = _extract_text(fallback_body)
                        if fallback_text:
                            response_body = fallback_body
                            text = fallback_text
                    except Exception:
                        pass

            if not text:
                detail = _extract_empty_reason(retry_body)
                if detail:
                    raise RuntimeError(f"Gemini returned an empty response. {detail}")
                raise RuntimeError("Gemini returned an empty response.")
            response_body = retry_body

        used_tokens = _extract_total_tokens(response_body)
        return text, used_tokens

    async def verify(self, model: str, api_key: str) -> tuple[bool, str]:
        model_id = model.strip()
        if not model_id:
            return False, "Model is required."

        if not api_key.strip():
            return False, "API key is required."

        payload = {
            "contents": [{"parts": [{"text": "Health check."}]}],
            "generationConfig": {"maxOutputTokens": 1},
        }

        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"

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


def _extract_total_tokens(payload: dict[str, object]) -> int | None:
    usage = payload.get("usageMetadata")
    if not isinstance(usage, dict):
        return None

    total = usage.get("totalTokenCount")
    if isinstance(total, int):
        return total

    return None


def _extract_empty_reason(payload: dict[str, object]) -> str:
    prompt_feedback = payload.get("promptFeedback")
    if isinstance(prompt_feedback, dict):
        block_reason = prompt_feedback.get("blockReason")
        if isinstance(block_reason, str) and block_reason.strip():
            return f"Blocked by Gemini policy ({block_reason})."

    candidates = payload.get("candidates")
    if isinstance(candidates, list) and candidates:
        first_candidate = candidates[0]
        if isinstance(first_candidate, dict):
            finish_reason = first_candidate.get("finishReason")
            if isinstance(finish_reason, str) and finish_reason.strip():
                return f"Finish reason: {finish_reason}."

    return ""


def _build_contents(history: list[dict[str, str]], prompt: str) -> tuple[list[dict[str, object]], str]:
    contents: list[dict[str, object]] = []
    system_lines: list[str] = []

    for item in history:
        role = item.get("role")
        content = item.get("content")

        if role not in {"system", "user", "assistant"} or not isinstance(content, str) or not content.strip():
            continue

        if role == "system":
            system_lines.append(content.strip())
            continue

        mapped_role = "user" if role == "user" else "model"
        contents.append({"role": mapped_role, "parts": [{"text": content}]})

    contents.append({"role": "user", "parts": [{"text": prompt}]})
    return contents, "\n\n".join(system_lines)


def _safe_read_error(exc: error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="ignore")
    except Exception:
        return "No additional details."
