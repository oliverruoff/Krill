"""Minimal Telegram Bot API client helpers used by the Telegram worker."""

import json
import re
from urllib import parse, request

# All characters that must be escaped in Telegram MarkdownV2 when not used for formatting.
_MDV2_ESCAPE_RE = re.compile(r'([_*\[\]()~`>#+\-=|{}.!\\])')

# Markdown patterns to detect, convert, and protect from escaping.
# Groups: 1=fenced code (lang+content), 2=inline code, 3=bold **, 4=italic *,
#         5=underline __, 6=italic _, 7=strikethrough ~~
_MD_PATTERN = re.compile(
    r'```((?:[^\n]*\n)?[\s\S]*?)```'
    r'|`([^`\n]+)`'
    r'|\*\*([^\n*]+)\*\*'
    r'|\*([^\n*]+)\*'
    r'|__([^\n_]+)__'
    r'|_([^\n_]+)_'
    r'|~~([^\n~]+)~~'
)


def _escape_mdv2(s: str) -> str:
    """Escape a plain-text string for Telegram MarkdownV2."""
    return _MDV2_ESCAPE_RE.sub(r'\\\1', s)


def _escape_code(s: str) -> str:
    """Escape content inside Telegram MarkdownV2 code/pre entities (only backslash and backtick)."""
    return s.replace('\\', '\\\\').replace('`', '\\`')


def _markdown_to_mdv2(text: str) -> str:
    """Convert LLM markdown output to Telegram MarkdownV2.

    Preserves and converts common markdown formatting (bold, italic, code,
    underline, strikethrough) to their MarkdownV2 equivalents, while escaping
    all MarkdownV2 special characters in the surrounding plain text.
    """
    parts: list[str] = []
    pos = 0
    for m in _MD_PATTERN.finditer(text):
        parts.append(_escape_mdv2(text[pos:m.start()]))
        pos = m.end()
        if m.group(1) is not None:
            parts.append(f'```{_escape_code(m.group(1))}```')
        elif m.group(2) is not None:
            parts.append(f'`{_escape_code(m.group(2))}`')
        elif m.group(3) is not None:
            parts.append(f'*{_escape_mdv2(m.group(3))}*')
        elif m.group(4) is not None:
            parts.append(f'_{_escape_mdv2(m.group(4))}_')
        elif m.group(5) is not None:
            parts.append(f'__{_escape_mdv2(m.group(5))}__')
        elif m.group(6) is not None:
            parts.append(f'_{_escape_mdv2(m.group(6))}_')
        elif m.group(7) is not None:
            parts.append(f'~{_escape_mdv2(m.group(7))}~')
    parts.append(_escape_mdv2(text[pos:]))
    return ''.join(parts)


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
    payload = json.dumps({"chat_id": chat_id, "text": _markdown_to_mdv2(text), "parse_mode": "MarkdownV2"}).encode("utf-8")
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
