"""OpenAI Codex OAuth provider using ChatGPT subscription tokens."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request

from .base import LLMProvider


OPENAI_CODEX_OAUTH_PROVIDER_ID = "openai_codex_oauth"
OPENAI_CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
OPENAI_CODEX_DEFAULT_BASE_URL = "https://chatgpt.com/backend-api"
OPENAI_CODEX_JWT_CLAIM_PATH = "https://api.openai.com/auth"
OPENAI_CODEX_MODEL_CANDIDATES: list[dict[str, object]] = [
    {"id": "gpt-5.3-codex", "label": "GPT-5.3 Codex", "token_limit": 400000, "supports_images": False},
    {
        "id": "gpt-5.3-codex-spark",
        "label": "GPT-5.3 Codex Spark (faster/cheaper)",
        "token_limit": 400000,
        "supports_images": False,
    },
    {"id": "gpt-5.2-codex", "label": "GPT-5.2 Codex", "token_limit": 400000, "supports_images": False},
    {"id": "gpt-5.1-codex", "label": "GPT-5.1 Codex", "token_limit": 400000, "supports_images": False},
    {
        "id": "gpt-5.1-codex-mini",
        "label": "GPT-5.1 Codex Mini (budget)",
        "token_limit": 400000,
        "supports_images": False,
    },
    {
        "id": "gpt-5.1-codex-max",
        "label": "GPT-5.1 Codex Max",
        "token_limit": 400000,
        "supports_images": False,
    },
]


@dataclass
class OpenAICodexOAuthCredentials:
    access_token: str
    refresh_token: str
    expires_at_unix: int
    account_id: str


_TOKEN_CACHE_BY_REFRESH: dict[str, OpenAICodexOAuthCredentials] = {}


class OpenAICodexOAuthProvider(LLMProvider):
    provider_id = OPENAI_CODEX_OAUTH_PROVIDER_ID
    display_name = "OpenAI OAuth (ChatGPT/Codex)"
    api_key_url = ""
    auth_mode = "oauth"
    oauth_provider_key = "openai_codex"
    available_models = OPENAI_CODEX_MODEL_CANDIDATES

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

        try:
            credentials = parse_oauth_bundle(api_key)
            credentials = await asyncio.to_thread(resolve_fresh_credentials, credentials)
        except error.HTTPError as exc:
            response_text = _safe_read_error(exc)
            if exc.code in {401, 403}:
                raise RuntimeError("OpenAI OAuth refresh token was rejected. Reconnect your OpenAI account.") from exc
            raise RuntimeError(f"OpenAI OAuth credential refresh failed ({exc.code}): {response_text}") from exc
        except Exception as exc:
            raise RuntimeError(f"OpenAI OAuth credentials are invalid: {exc}") from exc

        payload = {
            "model": model_id,
            "store": False,
            "stream": True,
            "instructions": system_prompt.strip() or None,
            "input": _build_input(history, prompt),
            "text": {"verbosity": "medium"},
        }

        try:
            text, used_tokens = await asyncio.to_thread(_post_stream_collect_text_and_usage, payload, credentials)
        except error.HTTPError as exc:
            response_text = _safe_read_error(exc)
            raise RuntimeError(f"OpenAI OAuth request failed ({exc.code}): {response_text}") from exc
        except error.URLError as exc:
            raise RuntimeError("Network error while contacting OpenAI OAuth endpoint.") from exc
        except TimeoutError as exc:
            raise RuntimeError("Network timeout while contacting OpenAI OAuth endpoint.") from exc
        except Exception as exc:
            raise RuntimeError("Unexpected error while contacting OpenAI OAuth endpoint.") from exc

        if not text:
            raise RuntimeError("OpenAI OAuth provider returned an empty response.")

        return text, used_tokens

    async def verify(self, model: str, api_key: str) -> tuple[bool, str]:
        model_id = model.strip()
        if not model_id:
            return False, "Model is required."

        try:
            credentials = parse_oauth_bundle(api_key)
            credentials = await asyncio.to_thread(resolve_fresh_credentials, credentials)
        except error.HTTPError as exc:
            response_text = _safe_read_error(exc)
            if exc.code in {401, 403}:
                return False, "OpenAI OAuth refresh token was rejected. Reconnect your OpenAI account."
            return False, f"OpenAI OAuth credential refresh failed ({exc.code}): {response_text}"
        except Exception as exc:
            return False, f"OAuth credentials are invalid: {exc}"

        payload = _build_verify_payload(model_id)

        try:
            status_code = await asyncio.to_thread(_post_json_status, payload, credentials)
        except error.HTTPError as exc:
            response_text = _safe_read_error(exc)
            if exc.code in {401, 403}:
                return False, "OpenAI OAuth token was rejected. Please reconnect your OpenAI account."
            return False, f"OpenAI OAuth verification failed ({exc.code}): {response_text}"
        except error.URLError:
            return False, "Network error while contacting OpenAI OAuth endpoint."
        except Exception as exc:
            return False, f"Unexpected error while verifying OpenAI OAuth credentials: {exc}"

        if status_code == 200:
            return True, "OpenAI OAuth credentials verified."
        return False, f"OpenAI OAuth endpoint returned unexpected status code {status_code}."


def parse_oauth_bundle(raw: str) -> OpenAICodexOAuthCredentials:
    text = str(raw).strip()
    if not text:
        raise RuntimeError("OAuth credentials are missing. Click Connect OpenAI first.")
    try:
        payload = json.loads(text)
    except Exception as exc:
        raise RuntimeError("OAuth credentials are not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("OAuth credentials payload must be an object.")

    access_token = str(payload.get("access_token", "")).strip()
    refresh_token = str(payload.get("refresh_token", "")).strip()
    account_id = str(payload.get("account_id", "")).strip()
    expires_at_raw = payload.get("expires_at_unix")
    if isinstance(expires_at_raw, int):
        expires_at_unix = expires_at_raw
    elif isinstance(expires_at_raw, float):
        expires_at_unix = int(expires_at_raw)
    elif isinstance(expires_at_raw, str) and expires_at_raw.strip().isdigit():
        expires_at_unix = int(expires_at_raw.strip())
    else:
        expires_at_unix = 0

    if not access_token:
        raise RuntimeError("OAuth credentials are missing access_token.")
    if not refresh_token:
        raise RuntimeError("OAuth credentials are missing refresh_token.")
    if not account_id:
        inferred = extract_account_id_from_jwt(access_token)
        if not inferred:
            raise RuntimeError("OAuth credentials are missing account_id.")
        account_id = inferred

    return OpenAICodexOAuthCredentials(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at_unix=expires_at_unix,
        account_id=account_id,
    )


def serialize_oauth_bundle(credentials: OpenAICodexOAuthCredentials) -> str:
    return json.dumps(
        {
            "provider": OPENAI_CODEX_OAUTH_PROVIDER_ID,
            "access_token": credentials.access_token,
            "refresh_token": credentials.refresh_token,
            "expires_at_unix": credentials.expires_at_unix,
            "account_id": credentials.account_id,
        },
        separators=(",", ":"),
    )


def get_refreshed_bundle_for_persistence(raw_bundle: str) -> str | None:
    try:
        current = parse_oauth_bundle(raw_bundle)
    except Exception:
        return None

    refreshed = _TOKEN_CACHE_BY_REFRESH.get(current.refresh_token)
    if refreshed is None:
        return None

    refreshed_bundle = serialize_oauth_bundle(refreshed)
    if refreshed_bundle == str(raw_bundle).strip():
        return None

    return refreshed_bundle


def resolve_fresh_credentials(credentials: OpenAICodexOAuthCredentials) -> OpenAICodexOAuthCredentials:
    cached = _TOKEN_CACHE_BY_REFRESH.get(credentials.refresh_token)
    if cached is not None and cached.expires_at_unix > int(time.time()) + 30:
        return cached

    now = int(time.time())
    if credentials.expires_at_unix > now + 30:
        _TOKEN_CACHE_BY_REFRESH[credentials.refresh_token] = credentials
        return credentials

    original_refresh = credentials.refresh_token
    refreshed = refresh_access_token(original_refresh)
    _TOKEN_CACHE_BY_REFRESH[original_refresh] = refreshed
    _TOKEN_CACHE_BY_REFRESH[refreshed.refresh_token] = refreshed
    return refreshed


def refresh_access_token(refresh_token: str) -> OpenAICodexOAuthCredentials:
    payload = parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": get_openai_codex_public_client_id(),
        }
    ).encode("utf-8")

    req = request.Request(
        url=OPENAI_CODEX_OAUTH_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    with request.urlopen(req, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))

    access_token = str(body.get("access_token", "")).strip()
    next_refresh_token = str(body.get("refresh_token", "")).strip() or refresh_token
    expires_in = body.get("expires_in")
    expires_in_seconds = int(expires_in) if isinstance(expires_in, int) else 3600
    expires_at_unix = int(time.time()) + max(60, min(86400, expires_in_seconds))

    if not access_token:
        raise RuntimeError("OAuth refresh response did not include access_token.")

    account_id = extract_account_id_from_jwt(access_token)
    if not account_id:
        raise RuntimeError("Could not extract account id from refreshed OAuth token.")

    return OpenAICodexOAuthCredentials(
        access_token=access_token,
        refresh_token=next_refresh_token,
        expires_at_unix=expires_at_unix,
        account_id=account_id,
    )


def extract_account_id_from_jwt(token: str) -> str:
    parts = token.split(".")
    if len(parts) != 3:
        return ""
    payload_b64 = parts[1]
    padding = "=" * (-len(payload_b64) % 4)
    try:
        decoded = base64.urlsafe_b64decode((payload_b64 + padding).encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    auth_claim = payload.get(OPENAI_CODEX_JWT_CLAIM_PATH)
    if not isinstance(auth_claim, dict):
        return ""
    account_id = auth_claim.get("chatgpt_account_id")
    return str(account_id).strip() if isinstance(account_id, str) else ""


def get_openai_codex_public_client_id() -> str:
    # Same public client id used by Codex OAuth CLI tooling.
    return "app_EMoamEEZ73f0CkXaXp7hrann"


def build_openai_codex_authorize_url(*, state: str, code_challenge: str, redirect_uri: str) -> str:
    query = parse.urlencode(
        {
            "response_type": "code",
            "client_id": get_openai_codex_public_client_id(),
            "redirect_uri": redirect_uri,
            "scope": "openid profile email offline_access",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "originator": "pi",
        }
    )
    return f"https://auth.openai.com/oauth/authorize?{query}"


def exchange_openai_codex_code(*, code: str, code_verifier: str, redirect_uri: str) -> OpenAICodexOAuthCredentials:
    payload = parse.urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": get_openai_codex_public_client_id(),
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
        }
    ).encode("utf-8")

    req = request.Request(
        url=OPENAI_CODEX_OAUTH_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    with request.urlopen(req, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))

    access_token = str(body.get("access_token", "")).strip()
    refresh_token = str(body.get("refresh_token", "")).strip()
    expires_in = body.get("expires_in")
    expires_in_seconds = int(expires_in) if isinstance(expires_in, int) else 3600
    expires_at_unix = int(time.time()) + max(60, min(86400, expires_in_seconds))

    if not access_token or not refresh_token:
        raise RuntimeError("OAuth token exchange failed: missing access_token or refresh_token.")
    account_id = extract_account_id_from_jwt(access_token)
    if not account_id:
        raise RuntimeError("OAuth token exchange failed: missing account id in token.")

    credentials = OpenAICodexOAuthCredentials(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at_unix=expires_at_unix,
        account_id=account_id,
    )
    _TOKEN_CACHE_BY_REFRESH[credentials.refresh_token] = credentials
    return credentials


def _build_input(history: list[dict[str, str]], prompt: str) -> list[dict[str, object]]:
    input_items: list[dict[str, object]] = []

    for item in history:
        role = item.get("role")
        content = item.get("content")

        if role not in {"system", "user", "assistant"} or not isinstance(content, str) or not content.strip():
            continue

        if role == "assistant":
            mapped_role = "assistant"
            content_type = "output_text"
        else:
            mapped_role = "user"
            content_type = "input_text"

        input_items.append(
            {
                "role": mapped_role,
                "content": [{"type": content_type, "text": content}],
            }
        )

    input_items.append(
        {
            "role": "user",
            "content": [{"type": "input_text", "text": prompt}],
        }
    )
    return input_items


def _build_headers(credentials: OpenAICodexOAuthCredentials) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {credentials.access_token}",
        "chatgpt-account-id": credentials.account_id,
        "OpenAI-Beta": "responses=experimental",
        "originator": "krill",
        "accept": "text/event-stream",
    }


def _build_verify_payload(model_id: str) -> dict[str, object]:
    return {
        "model": model_id,
        "store": False,
        "stream": True,
        "instructions": "Health check.",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "Health check."}]}],
        "text": {"verbosity": "low"},
    }


def _post_json_status(payload: dict[str, object], credentials: OpenAICodexOAuthCredentials) -> int:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=f"{OPENAI_CODEX_DEFAULT_BASE_URL}/codex/responses",
        data=body,
        headers=_build_headers(credentials),
        method="POST",
    )

    with request.urlopen(req, timeout=18) as response:
        response.read()
        return response.status


def _post_json_return_body(payload: dict[str, object], credentials: OpenAICodexOAuthCredentials) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=f"{OPENAI_CODEX_DEFAULT_BASE_URL}/codex/responses",
        data=body,
        headers=_build_headers(credentials),
        method="POST",
    )

    with request.urlopen(req, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_stream_collect_text_and_usage(
    payload: dict[str, object],
    credentials: OpenAICodexOAuthCredentials,
) -> tuple[str, int | None]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=f"{OPENAI_CODEX_DEFAULT_BASE_URL}/codex/responses",
        data=body,
        headers=_build_headers(credentials),
        method="POST",
    )

    chunks: list[str] = []
    completed_response: dict[str, object] | None = None

    with request.urlopen(req, timeout=90) as response:
        raw = response.read().decode("utf-8", errors="ignore")

    for event in _parse_sse_events(raw):
        event_type = str(event.get("type", "")).strip()
        if event_type in {"response.output_text.delta", "response.output_text"}:
            delta = event.get("delta")
            if isinstance(delta, str) and delta:
                chunks.append(delta)
            text = event.get("text")
            if isinstance(text, str) and text:
                chunks.append(text)
            continue

        if event_type in {"response.completed", "response.done"}:
            response_payload = event.get("response")
            if isinstance(response_payload, dict):
                completed_response = response_payload

    text_value = "".join(chunks).strip()
    if not text_value and completed_response is not None:
        text_value = _extract_text(completed_response)

    used_tokens: int | None = None
    if completed_response is not None:
        used_tokens = _extract_total_tokens(completed_response)

    return text_value, used_tokens


def _parse_sse_events(raw_sse: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for block in raw_sse.split("\n\n"):
        if not block.strip():
            continue
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if not data_lines:
            continue
        data_text = "\n".join(data_lines).strip()
        if not data_text or data_text == "[DONE]":
            continue
        try:
            parsed = json.loads(data_text)
        except Exception:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


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
            part_type = str(part.get("type", ""))
            if part_type in {"output_text", "text"}:
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


def _extract_error_detail(raw_text: str) -> str:
    text = str(raw_text or "").strip()
    if not text:
        return ""
    try:
        payload = json.loads(text)
    except Exception:
        return text
    if not isinstance(payload, dict):
        return text
    detail = payload.get("detail")
    return str(detail).strip() if isinstance(detail, str) else text


def probe_supported_models(credentials: OpenAICodexOAuthCredentials) -> dict[str, object]:
    fresh_credentials = resolve_fresh_credentials(credentials)
    supported: list[dict[str, object]] = []
    unsupported: list[dict[str, str]] = []

    for model in OPENAI_CODEX_MODEL_CANDIDATES:
        model_id = str(model.get("id", "")).strip()
        if not model_id:
            continue
        payload = _build_verify_payload(model_id)
        try:
            status_code = _post_json_status(payload, fresh_credentials)
            if status_code == 200:
                supported.append(dict(model))
                continue
            unsupported.append({"id": model_id, "reason": f"Unexpected status code {status_code}."})
        except error.HTTPError as exc:
            reason = _extract_error_detail(_safe_read_error(exc))
            unsupported.append({"id": model_id, "reason": reason or f"HTTP {exc.code}"})
        except Exception as exc:
            unsupported.append({"id": model_id, "reason": str(exc)})

    return {
        "credentials": fresh_credentials,
        "supported_models": supported,
        "unsupported_models": unsupported,
    }
