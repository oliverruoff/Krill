"""Local manager for WhatsApp sidecar lifecycle and API calls."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
import shutil
import base64
import zipfile
from pathlib import Path
from urllib import error, request

from app.config import BASE_DIR
from app.config import load_whatsapp_session_blob, save_whatsapp_session_blob

_SIDECAR_PORT = 18777
_SIDECAR_BASE = f"http://127.0.0.1:{_SIDECAR_PORT}"
_SIDECAR_DIR = BASE_DIR / "app" / "integrations" / "whatsapp" / "sidecar"
_AUTH_RUNTIME_DIR = BASE_DIR / "data" / "whatsapp_auth_runtime"
_SIDECAR_LOG_PATH = BASE_DIR / "data" / "whatsapp_sidecar.log"

_LOCK = asyncio.Lock()
_PROCESS: subprocess.Popen[str] | None = None
_LAST_START = 0.0


async def ensure_sidecar_running() -> None:
    global _PROCESS, _LAST_START
    async with _LOCK:
        if _PROCESS is not None and _PROCESS.poll() is None:
            return

        node_bin = "node"
        await asyncio.to_thread(_ensure_sidecar_dependencies)
        env = dict(os.environ)
        env["WA_SIDECAR_PORT"] = str(_SIDECAR_PORT)
        await _restore_session_from_db()
        _AUTH_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        env["WA_AUTH_DIR"] = str(_AUTH_RUNTIME_DIR)
        _SIDECAR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(_SIDECAR_LOG_PATH, "a", encoding="utf-8")
        _PROCESS = subprocess.Popen(
            [node_bin, "server.js"],
            cwd=str(_SIDECAR_DIR),
            env=env,
            stdout=log_handle,
            stderr=log_handle,
            text=True,
        )
        _LAST_START = time.time()

    await asyncio.to_thread(_wait_for_health)


async def stop_sidecar() -> None:
    global _PROCESS
    async with _LOCK:
        proc = _PROCESS
        _PROCESS = None
    if proc is None:
        return
    await _snapshot_session_to_db()
    try:
        proc.terminate()
    except Exception:
        pass


async def connect() -> dict[str, object]:
    await ensure_sidecar_running()
    payload = await asyncio.to_thread(_request_json, "POST", f"{_SIDECAR_BASE}/connect", {})
    await _snapshot_session_to_db()
    return payload


async def status() -> dict[str, object]:
    await ensure_sidecar_running()
    payload = await asyncio.to_thread(_request_json, "GET", f"{_SIDECAR_BASE}/status", None)
    state = str(payload.get("status", "")).strip().lower()
    if state in {"ready", "authenticated"}:
        await _snapshot_session_to_db()
    return payload


async def send_message(to_number: str, text: str) -> dict[str, object]:
    await ensure_sidecar_running()
    return await asyncio.to_thread(
        _request_json,
        "POST",
        f"{_SIDECAR_BASE}/send",
        {"to_number": to_number, "text": text},
    )


async def poll_events() -> list[dict[str, object]]:
    await ensure_sidecar_running()
    payload = await asyncio.to_thread(_request_json, "GET", f"{_SIDECAR_BASE}/events/poll", None)
    events = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(events, list):
        return []
    return [item for item in events if isinstance(item, dict)]


async def set_allowlist(numbers: set[str]) -> None:
    await ensure_sidecar_running()
    payload: dict[str, object] = {"numbers": sorted(numbers)}
    await asyncio.to_thread(_request_json, "POST", f"{_SIDECAR_BASE}/allowlist", payload)


async def list_contacts() -> list[dict[str, str]]:
    await ensure_sidecar_running()
    payload = await asyncio.to_thread(_request_json, "GET", f"{_SIDECAR_BASE}/contacts", None)
    contacts = payload.get("contacts") if isinstance(payload, dict) else None
    if not isinstance(contacts, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in contacts:
        if not isinstance(item, dict):
            continue
        number = normalize_phone_number(str(item.get("number", "")))
        if not number:
            continue
        name = str(item.get("name", "")).strip() or number
        normalized.append({"number": number, "name": name})
    return normalized


def normalize_phone_number(raw: str) -> str:
    cleaned = "".join(ch for ch in str(raw or "") if ch.isdigit() or ch == "+").strip()
    if not cleaned:
        return ""
    normalized = cleaned[1:] if cleaned.startswith("+") else cleaned
    if normalized.startswith("00"):
        normalized = normalized[2:]
    return "".join(ch for ch in normalized if ch.isdigit())


def parse_allowlist(raw: str) -> set[str]:
    text = str(raw or "").strip()
    if not text:
        return set()
    items: list[str] = []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                items = [str(item or "").strip() for item in parsed]
        except Exception:
            items = []
    if not items:
        if ";" in text:
            items = [part.strip() for part in text.split(";")]
        else:
            items = [part.strip() for part in text.split(",")]
    normalized = {normalize_phone_number(item) for item in items if item}
    return {item for item in normalized if item}


def _wait_for_health(timeout_seconds: float = 12.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            _request_json("GET", f"{_SIDECAR_BASE}/health", None)
            return
        except Exception:
            time.sleep(0.2)
    details = ""
    try:
        if _SIDECAR_LOG_PATH.exists():
            details = _SIDECAR_LOG_PATH.read_text(encoding="utf-8", errors="ignore")[-1200:].strip()
    except Exception:
        details = ""
    if details:
        raise RuntimeError(f"WhatsApp sidecar failed to start. Recent logs: {details}")
    raise RuntimeError("WhatsApp sidecar failed to start.")


def _request_json(method: str, url: str, payload: object | None) -> dict[str, object]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        if not isinstance(payload, dict):
            raise RuntimeError("Invalid sidecar payload type.")
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url=url, method=method, data=data, headers=headers)
    try:
        with request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            detail = ""
        raise RuntimeError(f"WhatsApp sidecar request failed ({exc.code}): {detail}") from exc


def _ensure_sidecar_dependencies() -> None:
    package_json = _SIDECAR_DIR / "package.json"
    if not package_json.exists():
        raise RuntimeError("WhatsApp sidecar package.json is missing.")
    dependency_marker = _SIDECAR_DIR / "node_modules" / "whatsapp-web.js"
    if dependency_marker.exists():
        return
    result = subprocess.run(
        ["npm", "install", "--omit=dev"],
        cwd=str(_SIDECAR_DIR),
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "npm install failed").strip()
        raise RuntimeError(f"WhatsApp sidecar dependency install failed: {detail}")


async def _restore_session_from_db() -> None:
    blob = await load_whatsapp_session_blob()
    if not blob.strip():
        return
    try:
        archive_bytes = base64.b64decode(blob, validate=True)
    except Exception:
        return
    shutil.rmtree(_AUTH_RUNTIME_DIR, ignore_errors=True)
    _AUTH_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = _AUTH_RUNTIME_DIR / "session.zip"
    archive_path.write_bytes(archive_bytes)
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(_AUTH_RUNTIME_DIR)
    except Exception:
        shutil.rmtree(_AUTH_RUNTIME_DIR, ignore_errors=True)
        _AUTH_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    finally:
        if archive_path.exists():
            archive_path.unlink(missing_ok=True)


async def _snapshot_session_to_db() -> None:
    if not _AUTH_RUNTIME_DIR.exists():
        return
    archive_path = _AUTH_RUNTIME_DIR / "session.zip"
    try:
        if archive_path.exists():
            archive_path.unlink(missing_ok=True)
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for file_path in _AUTH_RUNTIME_DIR.rglob("*"):
                if not file_path.is_file():
                    continue
                if file_path.name == "session.zip":
                    continue
                relative = file_path.relative_to(_AUTH_RUNTIME_DIR)
                zf.write(file_path, arcname=str(relative))
        encoded = base64.b64encode(archive_path.read_bytes()).decode("ascii")
        await save_whatsapp_session_blob(encoded)
    except Exception:
        return
    finally:
        if archive_path.exists():
            archive_path.unlink(missing_ok=True)
