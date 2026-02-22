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


def telegram_send_message(token: str, chat_id: int, text: str) -> dict[str, object]:
    url = f"https://api.telegram.org/bot{parse.quote(token, safe=':')}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = request.Request(
        url=url,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))
