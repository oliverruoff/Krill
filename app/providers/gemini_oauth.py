"""Google Gemini OAuth provider using bearer access tokens."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib import error, parse, request

from .base import LLMProvider


GEMINI_OAUTH_PROVIDER_ID = "google_gemini_oauth"
GEMINI_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GEMINI_OAUTH_MODEL_CANDIDATES: list[dict[str, object]] = [
    {"id": "gemini-3.1-pro-preview", "label": "Gemini 3.1 Pro Preview", "token_limit": 1048576, "supports_images": True},
    {"id": "gemini-3-flash-preview", "label": "Gemini 3 Flash Preview", "token_limit": 1048576, "supports_images": True},
    {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash", "token_limit": 1048576, "supports_images": True},
]


@dataclass
class GeminiOAuthCredentials:
    access_token: str
    refresh_token: str = ""
    expires_at_unix: int = 0
    client_id: str = ""
    client_secret: str = ""
    token_uri: str = GEMINI_OAUTH_TOKEN_URL
    email: str = ""


_TOKEN_CACHE_BY_ACCESS: dict[str, GeminiOAuthCredentials] = {}


class GeminiOAuthProvider(LLMProvider):
    provider_id = GEMINI_OAUTH_PROVIDER_ID
    display_name = "Google Gemini OAuth (Unofficial)"
    api_key_url = ""
    auth_mode = "oauth"
    oauth_provider_key = "google_gemini"
    available_models = GEMINI_OAUTH_MODEL_CANDIDATES

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

        credentials = parse_gemini_oauth_bundle(api_key)
        credentials = await asyncio.to_thread(resolve_fresh_credentials, credentials)

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

        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
        try:
            response_body = await asyncio.to_thread(_post_json_return_body, endpoint, payload, credentials)
        except error.HTTPError as exc:
            response_text = _safe_read_error(exc)
            raise RuntimeError(f"Gemini OAuth request failed ({exc.code}): {response_text}") from exc
        except error.URLError as exc:
            raise RuntimeError("Network error while contacting Gemini OAuth endpoint.") from exc
        except Exception as exc:
            raise RuntimeError("Unexpected error while contacting Gemini OAuth endpoint.") from exc

        text = _extract_text(response_body)
        if not text:
            detail = _extract_empty_reason(response_body)
            if detail:
                raise RuntimeError(f"Gemini OAuth returned an empty response. {detail}")
            raise RuntimeError("Gemini OAuth returned an empty response.")

        used_tokens = _extract_total_tokens(response_body)
        return text, used_tokens

    async def verify(self, model: str, api_key: str) -> tuple[bool, str]:
        model_id = model.strip()
        if not model_id:
            return False, "Model is required."

        try:
            credentials = parse_gemini_oauth_bundle(api_key)
            credentials = await asyncio.to_thread(resolve_fresh_credentials, credentials)
        except Exception as exc:
            return False, f"Gemini OAuth credentials are invalid: {exc}"

        payload = {
            "contents": [{"parts": [{"text": "Health check."}]}],
            "generationConfig": {"maxOutputTokens": 1},
        }
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
        try:
            status_code = await asyncio.to_thread(_post_json_status, endpoint, payload, credentials)
        except error.HTTPError as exc:
            response_text = _safe_read_error(exc)
            if exc.code in {401, 403}:
                return False, "Gemini OAuth token was rejected. Reconnect Gemini OAuth."
            return False, f"Gemini OAuth verification failed ({exc.code}): {response_text}"
        except error.URLError:
            return False, "Network error while contacting Gemini OAuth endpoint."
        except Exception as exc:
            return False, f"Unexpected error while verifying Gemini OAuth credentials: {exc}"

        if status_code == 200:
            return True, "Gemini OAuth credentials verified."
        return False, f"Gemini OAuth returned unexpected status code {status_code}."


def parse_gemini_oauth_bundle(raw: str) -> GeminiOAuthCredentials:
    text = str(raw).strip()
    if not text:
        raise RuntimeError("Gemini OAuth credentials are missing.")
    try:
        payload = json.loads(text)
    except Exception as exc:
        raise RuntimeError("Gemini OAuth credentials are not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Gemini OAuth payload must be an object.")

    token_obj = _find_token_object(payload)
    if token_obj is None:
        raise RuntimeError("Could not find OAuth token fields in payload.")

    access_token = str(token_obj.get("access_token", "")).strip()
    refresh_token = str(token_obj.get("refresh_token", "")).strip()
    client_id = str(token_obj.get("client_id", payload.get("client_id", ""))).strip()
    client_secret = str(token_obj.get("client_secret", payload.get("client_secret", ""))).strip()
    token_uri = str(token_obj.get("token_uri", payload.get("token_uri", GEMINI_OAUTH_TOKEN_URL))).strip() or GEMINI_OAUTH_TOKEN_URL
    email = str(token_obj.get("email", payload.get("email", ""))).strip()
    expires_at_unix = _extract_expiry_unix(token_obj)

    if not access_token:
        raise RuntimeError("Gemini OAuth token is missing access_token.")

    return GeminiOAuthCredentials(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at_unix=expires_at_unix,
        client_id=client_id,
        client_secret=client_secret,
        token_uri=token_uri,
        email=email,
    )


def serialize_gemini_oauth_bundle(credentials: GeminiOAuthCredentials) -> str:
    return json.dumps(
        {
            "provider": GEMINI_OAUTH_PROVIDER_ID,
            "access_token": credentials.access_token,
            "refresh_token": credentials.refresh_token,
            "expires_at_unix": credentials.expires_at_unix,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "token_uri": credentials.token_uri,
            "email": credentials.email,
        },
        separators=(",", ":"),
    )


def resolve_fresh_credentials(credentials: GeminiOAuthCredentials) -> GeminiOAuthCredentials:
    cached = _TOKEN_CACHE_BY_ACCESS.get(credentials.access_token)
    if cached is not None and _is_token_fresh(cached.expires_at_unix):
        return cached
    if _is_token_fresh(credentials.expires_at_unix):
        _TOKEN_CACHE_BY_ACCESS[credentials.access_token] = credentials
        return credentials
    refreshed = refresh_access_token(credentials)
    _TOKEN_CACHE_BY_ACCESS[refreshed.access_token] = refreshed
    return refreshed


def refresh_access_token(credentials: GeminiOAuthCredentials) -> GeminiOAuthCredentials:
    if not credentials.refresh_token:
        raise RuntimeError("Gemini OAuth access token expired and no refresh_token is available.")
    if not credentials.client_id or not credentials.client_secret:
        raise RuntimeError("Gemini OAuth access token expired and client credentials are missing.")

    token_url = credentials.token_uri.strip() or GEMINI_OAUTH_TOKEN_URL
    payload = parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": credentials.refresh_token,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
        }
    ).encode("utf-8")

    req = request.Request(
        url=token_url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    with request.urlopen(req, timeout=20) as response:
        body = json.loads(response.read().decode("utf-8"))

    access_token = str(body.get("access_token", "")).strip()
    if not access_token:
        raise RuntimeError("Gemini OAuth refresh did not return access_token.")
    refresh_token = str(body.get("refresh_token", "")).strip() or credentials.refresh_token
    expires_in_raw = body.get("expires_in")
    expires_in = int(expires_in_raw) if isinstance(expires_in_raw, int) else 3600
    expires_at_unix = int(time.time()) + max(60, min(86400, expires_in))

    return GeminiOAuthCredentials(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at_unix=expires_at_unix,
        client_id=credentials.client_id,
        client_secret=credentials.client_secret,
        token_uri=credentials.token_uri,
        email=credentials.email,
    )


def probe_supported_models(credentials: GeminiOAuthCredentials) -> dict[str, object]:
    fresh = resolve_fresh_credentials(credentials)
    supported: list[dict[str, object]] = []
    unsupported: list[dict[str, str]] = []
    for candidate in GEMINI_OAUTH_MODEL_CANDIDATES:
        model_id = str(candidate.get("id", "")).strip()
        if not model_id:
            continue
        payload = {
            "contents": [{"parts": [{"text": "Health check."}]}],
            "generationConfig": {"maxOutputTokens": 1},
        }
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
        try:
            status_code = _post_json_status(endpoint, payload, fresh)
            if status_code == 200:
                supported.append(dict(candidate))
            else:
                unsupported.append({"id": model_id, "reason": f"Unexpected status code {status_code}."})
        except error.HTTPError as exc:
            unsupported.append({"id": model_id, "reason": _extract_error_detail(_safe_read_error(exc)) or f"HTTP {exc.code}"})
        except Exception as exc:
            unsupported.append({"id": model_id, "reason": str(exc)})

    return {
        "credentials": fresh,
        "supported_models": supported,
        "unsupported_models": unsupported,
    }


def _is_token_fresh(expires_at_unix: int) -> bool:
    return isinstance(expires_at_unix, int) and expires_at_unix > int(time.time()) + 30


def _extract_expiry_unix(payload: dict[str, object]) -> int:
    expires_at = payload.get("expires_at_unix")
    if isinstance(expires_at, int):
        return expires_at
    if isinstance(expires_at, float):
        return int(expires_at)
    expiry_date = payload.get("expiry_date")
    if isinstance(expiry_date, int):
        return int(expiry_date // 1000 if expiry_date > 1_000_000_000_000 else expiry_date)
    expires_at_iso = payload.get("expires_at")
    if isinstance(expires_at_iso, str) and expires_at_iso.strip():
        try:
            dt = datetime.fromisoformat(expires_at_iso.replace("Z", "+00:00"))
            return int(dt.timestamp())
        except Exception:
            return 0
    return 0


def _find_token_object(payload: dict[str, object]) -> dict[str, object] | None:
    if "access_token" in payload:
        return payload
    for key in ("oauth", "token", "tokens", "credentials", "auth"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            found = _find_token_object(nested)
            if found is not None:
                return found
    for value in payload.values():
        if isinstance(value, dict):
            found = _find_token_object(value)
            if found is not None:
                return found
    return None


def _post_json_status(url: str, payload: dict[str, object], credentials: GeminiOAuthCredentials) -> int:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=url,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {credentials.access_token}"},
        method="POST",
    )
    with request.urlopen(req, timeout=12) as response:
        response.read()
        return response.status


def _post_json_return_body(url: str, payload: dict[str, object], credentials: GeminiOAuthCredentials) -> dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=url,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {credentials.access_token}"},
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
    return total if isinstance(total, int) else None


def _extract_empty_reason(payload: dict[str, object]) -> str:
    prompt_feedback = payload.get("promptFeedback")
    if isinstance(prompt_feedback, dict):
        block_reason = prompt_feedback.get("blockReason")
        if isinstance(block_reason, str) and block_reason.strip():
            return f"Blocked by Gemini policy ({block_reason})."
    candidates = payload.get("candidates")
    if isinstance(candidates, list) and candidates:
        first = candidates[0]
        if isinstance(first, dict):
            reason = first.get("finishReason")
            if isinstance(reason, str) and reason.strip():
                return f"Finish reason: {reason}."
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


def _extract_error_detail(raw_text: str) -> str:
    text = str(raw_text).strip()
    if not text:
        return ""
    try:
        payload = json.loads(text)
    except Exception:
        return text
    if not isinstance(payload, dict):
        return text
    error_payload = payload.get("error")
    if isinstance(error_payload, dict):
        message = error_payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    detail = payload.get("detail")
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    return text
