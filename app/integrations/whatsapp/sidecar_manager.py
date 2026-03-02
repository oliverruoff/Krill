"""Local manager for WhatsApp sidecar lifecycle and API calls."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import subprocess
import time
import shutil
import base64
import io
import zipfile
from pathlib import Path, PurePosixPath
from urllib import error, request

from app.config import BASE_DIR
from app.config import load_whatsapp_session_blob, save_whatsapp_session_blob

_SIDECAR_PORT = 18777
_SIDECAR_BASE = f"http://127.0.0.1:{_SIDECAR_PORT}"
_SIDECAR_DIR = BASE_DIR / "app" / "integrations" / "whatsapp" / "sidecar"
_RUNTIME_BASE_DIR = Path(tempfile.gettempdir()) / "krill_whatsapp_runtime"
_AUTH_RUNTIME_DIR = _RUNTIME_BASE_DIR / "auth"
_SIDECAR_LOG_PATH = _RUNTIME_BASE_DIR / "sidecar.log"

_AUTH_EXCLUDED_DIR_NAMES = {
    "cache",
    "code cache",
    "gpucache",
    "grshadercache",
    "dawncache",
    "component_crx_cache",
    "wasmttsengine",
    "widevinecdm",
    "ondeviceheadsuggestmodel",
    "zxcvbndata",
    "certificaterevocation",
    "safe browsing",
    "safebrowsing",
    "shadercache",
    "crashpad",
}
_AUTH_EXCLUDED_FILE_NAMES = {
    "browsermetrics-spare.pma",
}

_LOCK = asyncio.Lock()
_PROCESS: subprocess.Popen[str] | None = None
_LAST_START = 0.0


async def ensure_sidecar_running() -> None:
    global _PROCESS, _LAST_START
    async with _LOCK:
        if _PROCESS is not None and _PROCESS.poll() is None:
            return
        if await asyncio.to_thread(_sidecar_is_healthy):
            return

        node_bin = "node"
        puppeteer_executable = await asyncio.to_thread(_ensure_sidecar_dependencies)
        env = dict(os.environ)
        env["WA_SIDECAR_PORT"] = str(_SIDECAR_PORT)
        if puppeteer_executable:
            env["PUPPETEER_EXECUTABLE_PATH"] = puppeteer_executable
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
        try:
            await asyncio.to_thread(_request_json, "POST", f"{_SIDECAR_BASE}/shutdown", {})
        except Exception:
            pass
        await asyncio.sleep(0.5)
        await _snapshot_session_to_db()
        return
    try:
        proc.terminate()
    except Exception:
        pass
    for _ in range(30):
        if proc.poll() is not None:
            break
        await asyncio.sleep(0.1)
    await _snapshot_session_to_db()


def _sidecar_is_healthy() -> bool:
    try:
        _request_json("GET", f"{_SIDECAR_BASE}/health", None)
        return True
    except Exception:
        return False


async def connect() -> dict[str, object]:
    await ensure_sidecar_running()
    payload = await asyncio.to_thread(_request_json, "POST", f"{_SIDECAR_BASE}/connect", {})
    return payload


async def status() -> dict[str, object]:
    await ensure_sidecar_running()
    payload = await asyncio.to_thread(_request_json, "GET", f"{_SIDECAR_BASE}/status", None)
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


async def get_message_history(number: str, limit: int = 10) -> list[dict[str, Any]]:
    await ensure_sidecar_running()
    payload = await asyncio.to_thread(
        _request_json,
        "POST",
        f"{_SIDECAR_BASE}/messages/history",
        {"number": number, "limit": limit},
    )
    history = payload.get("history") if isinstance(payload, dict) else None
    if not isinstance(history, list):
        return []
    return [item for item in history if isinstance(item, dict)]



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


def _ensure_sidecar_dependencies() -> str | None:
    package_json = _SIDECAR_DIR / "package.json"
    if not package_json.exists():
        raise RuntimeError("WhatsApp sidecar package.json is missing.")
    if shutil.which("node") is None or shutil.which("npm") is None:
        raise RuntimeError("Node.js and npm are required for WhatsApp sidecar but were not found on PATH.")
    dependency_marker = _SIDECAR_DIR / "node_modules" / "whatsapp-web.js"
    if not dependency_marker.exists():
        try:
            result = subprocess.run(
                ["npm", "install", "--omit=dev"],
                cwd=str(_SIDECAR_DIR),
                capture_output=True,
                text=True,
                timeout=180,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("npm executable not found. Install Node.js and ensure npm is on PATH.") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "npm install failed").strip()
            raise RuntimeError(f"WhatsApp sidecar dependency install failed: {detail}")
    return _ensure_puppeteer_browser()


def _ensure_puppeteer_browser() -> str | None:
    check_script = (
        "const fs=require('node:fs');"
        "const puppeteer=require('puppeteer');"
        "const path=puppeteer.executablePath();"
        "if(path && fs.existsSync(path)){process.exit(0);}"
        "process.stderr.write(path || '');"
        "process.exit(1);"
    )
    check = subprocess.run(
        ["node", "-e", check_script],
        cwd=str(_SIDECAR_DIR),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if check.returncode == 0:
        return None

    local_executable = _detect_local_chromium_executable()
    if local_executable:
        return local_executable

    install_cmd = [
        "node",
        str(_SIDECAR_DIR / "node_modules" / "puppeteer" / "lib" / "cjs" / "puppeteer" / "node" / "cli.js"),
        "install",
        "chrome@stable",
    ]
    install = subprocess.run(
        install_cmd,
        cwd=str(_SIDECAR_DIR),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if install.returncode != 0:
        expected_path = (check.stderr or check.stdout or "").strip()
        _purge_puppeteer_cache(expected_path)
        install = subprocess.run(
            install_cmd,
            cwd=str(_SIDECAR_DIR),
            capture_output=True,
            text=True,
            timeout=300,
        )
    if install.returncode != 0:
        detail = (install.stderr or install.stdout or "puppeteer browser install failed").strip()
        raise RuntimeError(f"WhatsApp sidecar browser install failed: {detail}")

    recheck = subprocess.run(
        ["node", "-e", check_script],
        cwd=str(_SIDECAR_DIR),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if recheck.returncode != 0:
        expected = (check.stderr or check.stdout or "unknown executable path").strip()
        raise RuntimeError(
            "WhatsApp sidecar browser install completed but Chrome binary is still missing"
            + (f": {expected}" if expected else ".")
        )
    return None


def _purge_puppeteer_cache(expected_path: str) -> None:
    candidate = Path(expected_path)
    if expected_path and candidate.suffix.lower() == ".exe":
        cache_root = candidate.parent.parent.parent
        if cache_root.name == "chrome":
            shutil.rmtree(cache_root, ignore_errors=True)


def _detect_local_chromium_executable() -> str | None:
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/chromium-browser"),
        Path("/usr/bin/chromium"),
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return str(candidate)
    return None


async def _restore_session_from_db() -> None:
    blob = await load_whatsapp_session_blob()
    if not blob.strip():
        return
    try:
        archive_bytes = base64.b64decode(blob, validate=True)
    except Exception:
        return

    compacted_archive_bytes = _filter_session_archive_bytes(archive_bytes)
    if 0 < len(compacted_archive_bytes) < len(archive_bytes):
        try:
            compacted_blob = base64.b64encode(compacted_archive_bytes).decode("ascii")
            await save_whatsapp_session_blob(compacted_blob)
            archive_bytes = compacted_archive_bytes
        except Exception:
            pass

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
        file_candidates = [
            file_path
            for file_path in _AUTH_RUNTIME_DIR.rglob("*")
            if file_path.is_file()
            and file_path.name != "session.zip"
            and _should_include_auth_path(file_path)
        ]
        if not file_candidates:
            return
        if archive_path.exists():
            archive_path.unlink(missing_ok=True)
        archived_count = 0
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for file_path in file_candidates:
                relative = file_path.relative_to(_AUTH_RUNTIME_DIR)
                try:
                    zf.write(file_path, arcname=str(relative))
                    archived_count += 1
                except Exception:
                    continue
        if archived_count == 0:
            return
        encoded = base64.b64encode(archive_path.read_bytes()).decode("ascii")
        await save_whatsapp_session_blob(encoded)
    except Exception:
        return
    finally:
        if archive_path.exists():
            archive_path.unlink(missing_ok=True)


def _should_include_auth_path(file_path: Path) -> bool:
    try:
        relative = file_path.relative_to(_AUTH_RUNTIME_DIR)
    except ValueError:
        return False
    lowered_parts = [part.strip().lower() for part in relative.parts if part]
    if not lowered_parts:
        return False
    if any(part in _AUTH_EXCLUDED_DIR_NAMES for part in lowered_parts[:-1]):
        return False
    file_name = lowered_parts[-1]
    if file_name in _AUTH_EXCLUDED_FILE_NAMES:
        return False
    return True


def _should_include_archive_member(member_name: str) -> bool:
    lowered_parts = [part.strip().lower() for part in PurePosixPath(member_name).parts if part]
    if not lowered_parts:
        return False
    if any(part in _AUTH_EXCLUDED_DIR_NAMES for part in lowered_parts[:-1]):
        return False
    if lowered_parts[-1] in _AUTH_EXCLUDED_FILE_NAMES:
        return False
    return True


def _filter_session_archive_bytes(archive_bytes: bytes) -> bytes:
    if not archive_bytes:
        return archive_bytes
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as source_zip:
            members = [
                info
                for info in source_zip.infolist()
                if not info.is_dir() and _should_include_archive_member(info.filename)
            ]
            if not members:
                return archive_bytes

            output = io.BytesIO()
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target_zip:
                for info in members:
                    try:
                        data = source_zip.read(info.filename)
                    except Exception:
                        continue
                    target_zip.writestr(info.filename, data)

            filtered = output.getvalue()
            if not filtered:
                return archive_bytes
            return filtered
    except Exception:
        return archive_bytes
