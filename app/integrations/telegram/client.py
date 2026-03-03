"""Minimal Telegram Bot API client helpers used by the Telegram worker."""

import json
from urllib import parse, request


def telegram_get_me(token: str) -> dict[str, object]:
    url = f"https://api.telegram.org/bot{parse.quote(token, safe=':')}/getMe"
    req = request.Request(url=url, headers={"Accept": "application/json"}, method="GET")
    with request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def telegram_get_updates(token: str, offset: int, timeout_seconds: int) -> dict[str, object]:
    query = parse.urlencode({"offset": offset, "timeout": timeout_seconds, "allowed_updates": json.dumps(["message"])})
    url = f"https://api.telegram.org/bot{parse.quote(token, safe=':')}/getUpdates?{query}"
    req = request.Request(url=url, headers={"Accept": "application/json"}, method="GET")
    with request.urlopen(req, timeout=timeout_seconds + 10) as response:
        return json.loads(response.read().decode("utf-8"))


def telegram_send_message(token: str, chat_id: int, text: str, parse_mode: str | None = None) -> dict[str, object]:
    url = f"https://api.telegram.org/bot{parse.quote(token, safe=':')}/sendMessage"
    payload_dict: dict[str, object] = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload_dict["parse_mode"] = parse_mode
    payload = json.dumps(payload_dict).encode("utf-8")
    req = request.Request(
        url=url,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def telegram_get_file_path(token: str, file_id: str) -> str:
    query = parse.urlencode({"file_id": file_id})
    url = f"https://api.telegram.org/bot{parse.quote(token, safe=':')}/getFile?{query}"
    req = request.Request(url=url, headers={"Accept": "application/json"}, method="GET")
    with request.urlopen(req, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        raise RuntimeError("Telegram getFile returned no result.")
    path_value = result.get("file_path")
    if not isinstance(path_value, str) or not path_value.strip():
        raise RuntimeError("Telegram getFile returned no file_path.")
    return path_value.strip()


def telegram_download_file_bytes(token: str, file_path: str) -> bytes:
    url = f"https://api.telegram.org/file/bot{parse.quote(token, safe=':')}/{file_path.lstrip('/')}"
    req = request.Request(url=url, headers={"Accept": "*/*"}, method="GET")
    with request.urlopen(req, timeout=30) as response:
        return response.read()
