#!/usr/bin/env python3
"""Docker-first end-to-end API test for Krill."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request
from uuid import uuid4


DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_ENV_FILE = ".env_test"
DEFAULT_IMAGE = "krill:e2e"


class E2EFailure(RuntimeError):
    """Raised when an E2E assertion or operation fails."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _step(message: str) -> None:
    print(f"\n[STEP] {message}")


def _ok(message: str) -> None:
    print(f"[OK] {message}")


def _run_cmd(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
    if check and process.returncode != 0:
        stderr = process.stderr.strip()
        stdout = process.stdout.strip()
        details = stderr or stdout or "No command output"
        raise E2EFailure(f"Command failed ({' '.join(args)}): {details}")
    return process


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        raise E2EFailure(f"Environment file not found: {path}")

    data: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if value and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]

        data[key] = value
    return data


def _extract_gemini_key(path: Path) -> str:
    data = _parse_env_file(path)
    for key_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        value = data.get(key_name, "").strip()
        if value:
            return value
    raise E2EFailure(
        f"No Gemini API key found in {path}. Expected GEMINI_API_KEY or GOOGLE_API_KEY."
    )


def _http_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 30,
) -> dict[str, Any] | list[Any]:
    body: bytes | None = None
    headers = {"Accept": "application/json"}

    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(url=url, data=body, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            response_body = response.read().decode("utf-8")
            return json.loads(response_body)
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise E2EFailure(f"HTTP {exc.code} at {url}: {detail}") from exc
    except error.URLError as exc:
        raise E2EFailure(f"Network error at {url}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise E2EFailure(f"Invalid JSON response from {url}") from exc


def _http_bytes(method: str, url: str, timeout: float = 30) -> bytes:
    req = request.Request(url=url, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return response.read()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise E2EFailure(f"HTTP {exc.code} at {url}: {detail}") from exc
    except error.URLError as exc:
        raise E2EFailure(f"Network error at {url}: {exc}") from exc


def _parse_sse_payload(stream_text: str) -> tuple[str, bool, list[str]]:
    assistant_text = ""
    saw_done = False
    errors: list[str] = []

    for block in stream_text.split("\n\n"):
        block = block.strip()
        if not block:
            continue

        event_name = "message"
        data_parts: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_parts.append(line[5:].strip())

        if not data_parts:
            continue

        raw_data = "".join(data_parts)
        try:
            payload = json.loads(raw_data)
        except json.JSONDecodeError:
            errors.append(f"Invalid SSE JSON payload: {raw_data[:120]}")
            continue

        if event_name == "token":
            token = payload.get("text")
            if isinstance(token, str):
                assistant_text += token
        elif event_name == "done":
            saw_done = True
        elif event_name == "error":
            detail = payload.get("detail")
            errors.append(str(detail) if detail else "Unknown SSE error.")

    return assistant_text.strip(), saw_done, errors


def _build_container(repo_root: Path, image_tag: str) -> None:
    _step(f"Building Docker image {image_tag}")
    _run_cmd(["docker", "build", "-t", image_tag, str(repo_root)])
    _ok("Docker image built")


def _start_container(image_tag: str, name: str) -> str:
    _step(f"Starting container {name}")
    _run_cmd(["docker", "run", "-d", "-P", "--name", name, image_tag])
    result = _run_cmd(["docker", "port", name, "8055/tcp"])
    mapped = result.stdout.strip()
    if not mapped or ":" not in mapped:
        raise E2EFailure(f"Unable to determine mapped port for container {name}")
    host_port = mapped.rsplit(":", 1)[-1]
    base_url = f"http://127.0.0.1:{host_port}"
    _ok(f"Container {name} reachable at {base_url}")
    return base_url


def _wait_for_ready(base_url: str, timeout_seconds: int = 90) -> None:
    _step("Waiting for API readiness")
    deadline = time.time() + timeout_seconds
    last_error = ""

    while time.time() < deadline:
        try:
            payload = _http_json("GET", f"{base_url}/api/settings", timeout=5)
            if isinstance(payload, dict):
                _ok("API is ready")
                return
            last_error = "Unexpected /api/settings payload"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        time.sleep(1.2)

    raise E2EFailure(f"Timed out waiting for API readiness. Last error: {last_error}")


def _ensure_model_available(base_url: str, model_id: str) -> None:
    _step("Checking provider and model availability")
    providers = _http_json("GET", f"{base_url}/api/providers")
    if not isinstance(providers, list):
        raise E2EFailure("/api/providers returned invalid payload")

    gemini_provider = None
    for provider in providers:
        if isinstance(provider, dict) and provider.get("id") == "gemini":
            gemini_provider = provider
            break

    if not isinstance(gemini_provider, dict):
        raise E2EFailure("Gemini provider not available in /api/providers")

    models = gemini_provider.get("models")
    if not isinstance(models, list):
        raise E2EFailure("Gemini provider models payload is invalid")

    has_model = any(isinstance(model, dict) and model.get("id") == model_id for model in models)
    if not has_model:
        raise E2EFailure(f"Model {model_id} not available for Gemini provider")
    _ok(f"Gemini provider and model {model_id} are available")


def _verify_provider(base_url: str, model_id: str, api_key: str) -> None:
    _step("Verifying Gemini credentials")
    payload = {
        "provider_id": "gemini",
        "model": model_id,
        "api_key": api_key,
    }
    response = _http_json("POST", f"{base_url}/api/providers/verify", payload)
    if not isinstance(response, dict) or not response.get("ok"):
        raise E2EFailure("Provider verification did not return ok=true")
    _ok("Provider credentials verified")


def _configure_fresh_system(base_url: str, model_id: str, api_key: str) -> dict[str, Any]:
    _step("Creating fresh system configuration")
    existing_settings = _http_json("GET", f"{base_url}/api/settings")
    if not isinstance(existing_settings, dict):
        raise E2EFailure("/api/settings returned invalid payload")

    existing_settings["bot_name"] = "KrillE2E"
    existing_settings["system_prompt"] = "Talk english. Be concise and friendly."
    existing_settings["setup_completed"] = True
    existing_settings["active_provider_id"] = "gemini"
    existing_settings["active_model_id"] = model_id
    existing_settings["provider_configs"] = {
        "gemini": {
            "api_key": api_key,
            "model": model_id,
        }
    }
    existing_settings["chats"] = []
    existing_settings["active_chat_id"] = ""
    existing_settings["daily_token_usage"] = []

    updated = _http_json("POST", f"{base_url}/api/settings", existing_settings)
    if not isinstance(updated, dict) or not updated.get("setup_completed"):
        raise E2EFailure("Failed to save setup-complete settings")

    _ok("Fresh system configured")
    return updated


def _run_single_chat(base_url: str, model_id: str, api_key: str, bot_name: str, system_prompt: str) -> str:
    _step("Running chat stream query: hi")
    payload = {
        "message": "hi",
        "history": [],
        "memory_block": "",
        "provider_id": "gemini",
        "model": model_id,
        "api_key": api_key,
        "bot_name": bot_name,
        "system_prompt": system_prompt,
    }

    req = request.Request(
        url=f"{base_url}/api/chat/stream",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=120) as response:
            stream_text = response.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise E2EFailure(f"Chat stream failed with HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise E2EFailure(f"Network error while calling chat stream: {exc}") from exc

    assistant_text, saw_done, errors = _parse_sse_payload(stream_text)
    if errors:
        raise E2EFailure(f"Chat stream emitted error event(s): {' | '.join(errors)}")
    if not saw_done:
        raise E2EFailure("Chat stream did not emit done event")
    if not assistant_text:
        raise E2EFailure("Chat stream returned empty assistant response")

    _ok("Chat stream completed without errors and returned text")
    return assistant_text


def _persist_chat_to_settings(base_url: str, assistant_text: str) -> None:
    _step("Persisting chat via /api/settings")
    settings = _http_json("GET", f"{base_url}/api/settings")
    if not isinstance(settings, dict):
        raise E2EFailure("/api/settings returned invalid payload while persisting chat")

    chat_id = f"chat-{uuid4()}"
    timestamp = _now_iso()
    chat = {
        "id": chat_id,
        "title": "hi",
        "type": "normal",
        "messages": [
            {
                "role": "user",
                "content": "hi",
                "timestamp": timestamp,
                "system_type": "",
                "tool_usage": [],
                "request_id": "",
                "status": "",
            },
            {
                "role": "assistant",
                "content": assistant_text,
                "timestamp": _now_iso(),
                "system_type": "",
                "tool_usage": [],
                "request_id": f"req-{uuid4()}",
                "status": "done",
            },
        ],
        "memory_block": "",
        "total_tokens_used": 0,
        "collapse_system_trace": True,
    }

    settings["chats"] = [chat]
    settings["active_chat_id"] = chat_id

    saved = _http_json("POST", f"{base_url}/api/settings", settings)
    if not isinstance(saved, dict):
        raise E2EFailure("Persisting chat returned invalid payload")

    chats = saved.get("chats")
    if not isinstance(chats, list) or len(chats) != 1:
        raise E2EFailure("Expected exactly one chat after persisting")
    _ok("Chat persisted")


def _set_google_mcp_fixture(base_url: str) -> None:
    _step("Persisting Google MCP OAuth fixture params")
    settings = _http_json("GET", f"{base_url}/api/settings")
    if not isinstance(settings, dict):
        raise E2EFailure("/api/settings returned invalid payload while setting Google MCP fixture")

    raw_mcp_configs = settings.get("mcp_configs")
    mcp_configs: dict[str, Any] = dict(raw_mcp_configs) if isinstance(raw_mcp_configs, dict) else {}
    mcp_configs["google_services"] = {
        "enabled": True,
        "params": {
            "access_mode": "read_write",
            "client_id": "fixture-client-id.apps.googleusercontent.com",
            "client_secret": "fixture-client-secret",
            "access_token": "fixture-access-token",
            "refresh_token": "fixture-refresh-token",
            "token_expiry": "2099-01-01T00:00:00+00:00",
            "connected_email": "fixture@example.com",
            "scopes": "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/calendar.events",
        },
    }
    settings["mcp_configs"] = mcp_configs

    saved = _http_json("POST", f"{base_url}/api/settings", settings)
    if not isinstance(saved, dict):
        raise E2EFailure("Saving Google MCP fixture returned invalid payload")
    _ok("Google MCP fixture params saved")


def _download_braindump(base_url: str, output_path: Path) -> bytes:
    _step("Downloading braindump export")
    payload = _http_bytes("GET", f"{base_url}/api/braindump/download")
    output_path.write_bytes(payload)
    if not payload.startswith(b"SQLite format 3\0"):
        raise E2EFailure("Downloaded braindump is not a valid SQLite database")
    _ok(f"Braindump downloaded to {output_path}")
    return payload


def _validate_brain_view(base_url: str) -> None:
    _step("Validating brain view endpoint")
    payload = _http_json("GET", f"{base_url}/api/braindump/view")
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise E2EFailure("/api/braindump/view returned invalid payload")

    tables = payload.get("tables")
    if not isinstance(tables, list) or not tables:
        raise E2EFailure("/api/braindump/view returned no tables")

    table_names = {table.get("name") for table in tables if isinstance(table, dict)}
    required = {"settings_core", "provider_configs", "chats", "chat_messages"}
    if not required.issubset(table_names):
        raise E2EFailure("/api/braindump/view missing required tables")

    _ok("Brain view endpoint looks good")


def _import_braindump(base_url: str, braindump_bytes: bytes) -> None:
    _step("Importing braindump into fresh instance")
    
    boundary = f"----KrillE2E{uuid4().hex}"
    parts = [
        f"--{boundary}",
        'Content-Disposition: form-data; name="file"; filename="braindump.db"',
        "Content-Type: application/x-sqlite3",
        "",
        "",
    ]
    body = "\r\n".join(parts).encode("utf-8") + braindump_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
    
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    }
    
    req = request.Request(f"{base_url}/api/braindump/import", data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=30) as response:
            resp_body = response.read().decode("utf-8")
            result = json.loads(resp_body)
            if not result.get("ok"):
                raise E2EFailure(f"Import failed: {resp_body}")
    except Exception as exc:
        raise E2EFailure(f"Import failed: {exc}")
        
    _ok("Braindump imported")


def _validate_restored_chat(base_url: str) -> None:
    _step("Validating restored chat state")
    state_payload = _http_json("GET", f"{base_url}/api/chat/state")
    if not isinstance(state_payload, dict):
        raise E2EFailure("/api/chat/state returned invalid payload")

    chats = state_payload.get("chats")
    if not isinstance(chats, list) or len(chats) != 1:
        raise E2EFailure("Expected exactly one chat after restore")

    chat = chats[0]
    if not isinstance(chat, dict):
        raise E2EFailure("Restored chat payload is invalid")
    messages = chat.get("messages")
    if not isinstance(messages, list):
        raise E2EFailure("Restored chat messages payload is invalid")

    has_user_hi = any(
        isinstance(message, dict)
        and message.get("role") == "user"
        and isinstance(message.get("content"), str)
        and str(message.get("content", "")).strip().lower() == "hi"
        for message in messages
    )
    has_assistant = any(
        isinstance(message, dict)
        and message.get("role") == "assistant"
        and isinstance(message.get("content"), str)
        and bool(str(message.get("content", "")).strip())
        for message in messages
    )

    if not has_user_hi:
        raise E2EFailure("Restored chat does not contain user message 'hi'")
    if not has_assistant:
        raise E2EFailure("Restored chat does not contain non-empty assistant message")

    _ok("Restore validation passed")


def _validate_restored_google_mcp(base_url: str) -> None:
    _step("Validating restored Google MCP params")
    settings = _http_json("GET", f"{base_url}/api/settings")
    if not isinstance(settings, dict):
        raise E2EFailure("/api/settings returned invalid payload while validating Google MCP restore")

    mcp_configs = settings.get("mcp_configs")
    if not isinstance(mcp_configs, dict):
        raise E2EFailure("Restored settings missing mcp_configs")

    google_config = mcp_configs.get("google_services")
    if not isinstance(google_config, dict):
        raise E2EFailure("Restored settings missing google_services MCP config")

    params = google_config.get("params")
    if not isinstance(params, dict):
        raise E2EFailure("Restored google_services params payload is invalid")

    expected_pairs = {
        "access_mode": "read_write",
        "client_id": "fixture-client-id.apps.googleusercontent.com",
        "client_secret": "fixture-client-secret",
        "access_token": "fixture-access-token",
        "refresh_token": "fixture-refresh-token",
        "connected_email": "fixture@example.com",
    }
    for key, expected in expected_pairs.items():
        if str(params.get(key, "")) != expected:
            raise E2EFailure(f"Restored google_services param mismatch for {key}")

    _ok("Google MCP params restored from braindump")


def _remove_container(name: str) -> None:
    _run_cmd(["docker", "rm", "-f", name], check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Docker-based Krill API E2E test.")
    parser.add_argument("--env-file", default=DEFAULT_ENV_FILE, help="Path to env file with Gemini API key.")
    parser.add_argument("--image", default=DEFAULT_IMAGE, help="Docker image tag to build and run.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini model id to use.")
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Keep downloaded braindump file after test run.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    env_file = Path(args.env_file)
    if not env_file.is_absolute():
        env_file = (repo_root / env_file).resolve()

    temp_dir_path = Path(tempfile.mkdtemp(prefix="krill-e2e-"))
    exported_braindump_path = temp_dir_path / "braindump-export.db"

    container_a = f"krill-e2e-a-{uuid4().hex[:8]}"
    container_b = f"krill-e2e-b-{uuid4().hex[:8]}"

    try:
        _step("Checking Docker availability")
        _run_cmd(["docker", "version"])
        _ok("Docker is available")

        api_key = _extract_gemini_key(env_file)
        _ok(f"Loaded API key from {env_file.name}")

        _build_container(repo_root, args.image)

        base_url_a = _start_container(args.image, container_a)
        _wait_for_ready(base_url_a)
        _ensure_model_available(base_url_a, args.model)
        _verify_provider(base_url_a, args.model, api_key)

        settings = _configure_fresh_system(base_url_a, args.model, api_key)
        assistant_text = _run_single_chat(
            base_url_a,
            args.model,
            api_key,
            str(settings.get("bot_name") or "KrillE2E"),
            str(settings.get("system_prompt") or ""),
        )

        _persist_chat_to_settings(base_url_a, assistant_text)
        _set_google_mcp_fixture(base_url_a)
        _validate_brain_view(base_url_a)
        exported_bytes = _download_braindump(base_url_a, exported_braindump_path)

        base_url_b = _start_container(args.image, container_b)
        _wait_for_ready(base_url_b)
        _import_braindump(base_url_b, exported_bytes)
        _validate_restored_chat(base_url_b)
        _validate_restored_google_mcp(base_url_b)

        print("\n[PASS] End-to-end Docker API test completed successfully.")
        print(f"[INFO] Exported braindump path: {exported_braindump_path}")
        return 0
    except E2EFailure as exc:
        print(f"\n[FAIL] {exc}")
        print("[HINT] Check container logs with:")
        print(f"       docker logs {container_a}")
        print(f"       docker logs {container_b}")
        return 1
    finally:
        _step("Cleaning up containers")
        _remove_container(container_a)
        _remove_container(container_b)
        _ok("Container cleanup complete")

        if args.keep_artifacts:
            _ok(f"Kept artifacts in {temp_dir_path}")
        else:
            try:
                for child in temp_dir_path.iterdir():
                    if child.is_file():
                        child.unlink()
                temp_dir_path.rmdir()
                _ok("Removed temporary artifacts")
            except Exception:  # noqa: BLE001
                print(f"[WARN] Failed to fully remove temporary artifacts at {temp_dir_path}")


if __name__ == "__main__":
    sys.exit(main())
