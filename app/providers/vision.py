"""Image analysis helpers for provider/model combinations with vision support."""

from __future__ import annotations

import asyncio
import base64
import json
from urllib import error, request

from .registry import get_provider_model_supports_images


async def analyze_image(
    *,
    provider_id: str,
    model: str,
    api_key: str,
    image_bytes: bytes,
    mime_type: str,
    prompt: str,
) -> tuple[str, int | None]:
    provider_key = provider_id.strip().lower()
    model_id = model.strip()
    if not model_id:
        raise RuntimeError("Model is required for image analysis.")
    if not api_key.strip():
        raise RuntimeError("API key is required for image analysis.")
    if not image_bytes:
        raise RuntimeError("Image data is empty.")
    if not get_provider_model_supports_images(provider_key, model_id):
        raise RuntimeError(
            f"Selected model '{model_id}' on provider '{provider_key}' does not support image input. "
            "Please switch to a vision-capable model."
        )

    if provider_key == "gemini":
        return await _analyze_image_gemini(model_id=model_id, api_key=api_key, image_bytes=image_bytes, mime_type=mime_type, prompt=prompt)
    if provider_key == "openai":
        return await _analyze_image_openai(model_id=model_id, api_key=api_key, image_bytes=image_bytes, mime_type=mime_type, prompt=prompt)

    raise RuntimeError(
        f"Provider '{provider_key}' is not configured for image analysis in this build. "
        "Please use Gemini or OpenAI vision models."
    )


async def _analyze_image_gemini(*, model_id: str, api_key: str, image_bytes: bytes, mime_type: str, prompt: str) -> tuple[str, int | None]:
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": base64.b64encode(image_bytes).decode("utf-8"),
                        }
                    },
                ],
            }
        ]
    }
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"
    try:
        body = await asyncio.to_thread(_post_json_return_body, endpoint, payload, {"Content-Type": "application/json"})
    except error.HTTPError as exc:
        raise RuntimeError(f"Gemini image analysis failed ({exc.code}): {_safe_read_error(exc)}") from exc
    except error.URLError as exc:
        raise RuntimeError("Network error while contacting Gemini for image analysis.") from exc

    text = _extract_gemini_text(body)
    if not text:
        raise RuntimeError("Gemini returned empty image analysis.")
    return text, _extract_usage_total_tokens(body)


async def _analyze_image_openai(*, model_id: str, api_key: str, image_bytes: bytes, mime_type: str, prompt: str) -> tuple[str, int | None]:
    data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('utf-8')}"
    payload = {
        "model": model_id,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": data_url},
                ],
            }
        ],
    }
    try:
        body = await asyncio.to_thread(
            _post_json_return_body,
            "https://api.openai.com/v1/responses",
            payload,
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
    except error.HTTPError as exc:
        raise RuntimeError(f"OpenAI image analysis failed ({exc.code}): {_safe_read_error(exc)}") from exc
    except error.URLError as exc:
        raise RuntimeError("Network error while contacting OpenAI for image analysis.") from exc

    text = _extract_openai_text(body)
    if not text:
        raise RuntimeError("OpenAI returned empty image analysis.")
    return text, _extract_usage_total_tokens(body)


def _post_json_return_body(url: str, payload: dict[str, object], headers: dict[str, str]) -> dict[str, object]:
    raw = json.dumps(payload).encode("utf-8")
    req = request.Request(url=url, data=raw, headers=headers, method="POST")
    with request.urlopen(req, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def _extract_gemini_text(payload: dict[str, object]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    first = candidates[0]
    if not isinstance(first, dict):
        return ""
    content = first.get("content")
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
        if isinstance(text, str) and text.strip():
            chunks.append(text.strip())
    return "\n".join(chunks).strip()


def _extract_openai_text(payload: dict[str, object]) -> str:
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
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
    return "\n".join(chunks).strip()


def _extract_usage_total_tokens(payload: dict[str, object]) -> int | None:
    usage = payload.get("usageMetadata") if "usageMetadata" in payload else payload.get("usage")
    if not isinstance(usage, dict):
        return None
    total = usage.get("totalTokenCount") if "totalTokenCount" in usage else usage.get("total_tokens")
    if isinstance(total, int):
        return total
    return None


def _safe_read_error(exc: error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="ignore")
    except Exception:
        return "No additional details."
