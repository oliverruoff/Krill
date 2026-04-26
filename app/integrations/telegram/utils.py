"""Shared utilities for Telegram integration."""
from __future__ import annotations

import html
import re

_TELEGRAM_TABLE_PLACEHOLDER_PREFIX = "KRILLTELEGRAMTABLE"
_TELEGRAM_TABLE_MAX_WIDTH = 42
_TELEGRAM_TABLE_FIRST_COLUMN_MAX_WIDTH = 10


def chunk_telegram_text(text: str, max_len: int = 3500) -> list[str]:
    """Split text into chunks suitable for Telegram messages.
    
    Args:
        text: Text to chunk.
        max_len: Maximum length per chunk (default 3500 for Telegram limit).
    
    Returns:
        List of text chunks, each <= max_len characters.
    """
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, max_len)
        if split_at <= 0:
            split_at = remaining.rfind(" ", 0, max_len)
        if split_at <= 0:
            split_at = max_len
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].lstrip()
    return [chunk for chunk in chunks if chunk]


def _split_markdown_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if "|" not in stripped:
        return []
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_markdown_table_separator(line: str) -> bool:
    cells = _split_markdown_table_row(line)
    if len(cells) < 2:
        return False
    return all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


def _parse_markdown_table_at(
    lines: list[str],
    index: int,
) -> tuple[int, list[str], list[str], list[list[str]], str] | None:
    if (
        index + 2 >= len(lines)
        or "|" not in lines[index]
        or not _is_markdown_table_separator(lines[index + 1])
    ):
        return None

    header = _split_markdown_table_row(lines[index])
    separator = _split_markdown_table_row(lines[index + 1])
    if len(header) < 2 or len(separator) != len(header):
        return None

    body_index = index + 2
    rows: list[list[str]] = []
    while body_index < len(lines):
        candidate = lines[body_index]
        if "|" not in candidate or _is_markdown_table_separator(candidate):
            break
        cells = _split_markdown_table_row(candidate)
        if not cells:
            break
        rows.append(cells)
        body_index += 1

    if not rows:
        return None

    raw_table = "".join(lines[index:body_index])
    return body_index, header, separator, rows, raw_table


def _table_alignments(separator_cells: list[str]) -> list[str]:
    alignments: list[str] = []
    for cell in separator_cells:
        marker = cell.replace(" ", "")
        if marker.startswith(":") and marker.endswith(":"):
            alignments.append("center")
        elif marker.endswith(":"):
            alignments.append("right")
        else:
            alignments.append("left")
    return alignments


def _normalize_table_row(cells: list[str], column_count: int) -> list[str]:
    normalized = list(cells[:column_count])
    while len(normalized) < column_count:
        normalized.append("")
    return normalized


def _format_table_cell(value: str, width: int, alignment: str) -> str:
    if alignment == "right":
        return value.rjust(width)
    if alignment == "center":
        return value.center(width)
    return value.ljust(width)


def _plain_table_cell(value: str) -> str:
    result = value.strip()
    result = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", result)
    result = re.sub(r"`([^`]+)`", r"\1", result)
    result = re.sub(r"\*\*(.+?)\*\*", r"\1", result)
    result = re.sub(r"__(.+?)__", r"\1", result)
    result = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"\1", result)
    result = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", result)
    return html.unescape(result)


def _wrap_table_text(value: str, width: int) -> list[str]:
    words = value.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        while len(current) > width:
            lines.append(current[:width])
            current = current[width:]
    if current:
        lines.append(current)
    return lines or [""]


def _mobile_column_widths(header: list[str], rows: list[list[str]]) -> list[int] | None:
    column_count = len(header)
    if column_count > 3:
        return None

    natural_widths = [
        max(len(row[index]) for row in [header, *rows])
        for index in range(column_count)
    ]
    separator_width = 3 * (column_count - 1)
    if sum(natural_widths) + separator_width <= _TELEGRAM_TABLE_MAX_WIDTH:
        return natural_widths

    if column_count == 2:
        first_width = min(natural_widths[0], _TELEGRAM_TABLE_FIRST_COLUMN_MAX_WIDTH)
        second_width = _TELEGRAM_TABLE_MAX_WIDTH - first_width - separator_width
        if second_width >= 16:
            return [first_width, second_width]

    available = _TELEGRAM_TABLE_MAX_WIDTH - separator_width
    min_width = 8
    if available < min_width * column_count:
        return None
    width = available // column_count
    return [min(max(natural_widths[index], min_width), width) for index in range(column_count)]


def _render_wrapped_table_row(cells: list[str], widths: list[int], alignments: list[str]) -> list[str]:
    wrapped_cells = [
        _wrap_table_text(cells[index], widths[index])
        for index in range(len(widths))
    ]
    line_count = max(len(lines) for lines in wrapped_cells)
    rendered: list[str] = []
    for line_index in range(line_count):
        parts: list[str] = []
        for column_index, lines in enumerate(wrapped_cells):
            value = lines[line_index] if line_index < len(lines) else ""
            parts.append(_format_table_cell(value, widths[column_index], alignments[column_index]))
        rendered.append(" | ".join(parts).rstrip())
    return rendered


def _render_compact_list_table(header: list[str], rows: list[list[str]]) -> str:
    rendered: list[str] = []
    for row_index, row in enumerate(rows, start=1):
        if row_index > 1:
            rendered.append("")
        entries = [
            f"{header[index]}: {row[index]}"
            for index in range(len(header))
            if row[index]
        ]
        wrapped = _wrap_table_text(" | ".join(entries), _TELEGRAM_TABLE_MAX_WIDTH)
        rendered.extend(wrapped)
    return "\n".join(rendered)


def _render_markdown_table(header: list[str], separator: list[str], rows: list[list[str]]) -> str:
    column_count = len(header)
    normalized_header = [_plain_table_cell(cell) for cell in _normalize_table_row(header, column_count)]
    normalized_rows = [
        [_plain_table_cell(cell) for cell in _normalize_table_row(row, column_count)]
        for row in rows
    ]
    widths = _mobile_column_widths(normalized_header, normalized_rows)
    if widths is None:
        return _render_compact_list_table(normalized_header, normalized_rows)

    alignments = _table_alignments(separator)
    rendered_rows = _render_wrapped_table_row(normalized_header, widths, alignments)
    rendered_rows.append(" | ".join("-" * width for width in widths).rstrip())
    for row in normalized_rows:
        rendered_rows.extend(_render_wrapped_table_row(row, widths, alignments))
    return "\n".join(rendered_rows)


def _replace_markdown_tables(text: str) -> tuple[str, dict[str, str]]:
    lines = text.splitlines(keepends=True)
    output: list[str] = []
    table_html_by_placeholder: dict[str, str] = {}
    index = 0
    table_index = 0
    in_code_block = False

    while index < len(lines):
        line = lines[index]
        if line.lstrip().startswith("```"):
            in_code_block = not in_code_block
            output.append(line)
            index += 1
            continue

        parsed_table = None if in_code_block else _parse_markdown_table_at(lines, index)
        if parsed_table is not None:
            body_index, header, separator, rows, _raw_table = parsed_table
            placeholder = f"{_TELEGRAM_TABLE_PLACEHOLDER_PREFIX}{table_index}"
            table_index += 1
            rendered_table = _render_markdown_table(header, separator, rows)
            escaped_table = html.escape(rendered_table, quote=False)
            table_html_by_placeholder[placeholder] = f"<pre>{escaped_table}</pre>"
            output.append(placeholder)
            if lines[body_index - 1].endswith("\n"):
                output.append("\n")
            index = body_index
            continue

        output.append(line)
        index += 1

    return "".join(output), table_html_by_placeholder


def markdown_to_html(text: str) -> str:
    """Convert common markdown patterns to HTML for Telegram HTML parse_mode.
    
    Converts:
    - # Headline -> <b>Headline</b>
    - **bold** or *bold* -> <b>bold</b>
    - __italic__ or _italic_ -> <i>italic</i>
    - `code` -> <code>code</code>
    - ```code block``` -> <pre>code block</pre>
    - [link](url) -> <a href="url">link</a>
    - * bullet or - bullet -> • bullet (Unicode bullet)
    - > quote -> ▌quote (blockquote with visual marker)
    - Escapes HTML entities: <, >, &
    
    Args:
        text: Markdown-formatted text.
    
    Returns:
        HTML-formatted text safe for Telegram.
    """
    text, table_html_by_placeholder = _replace_markdown_tables(text)

    # Convert blockquotes FIRST, before escaping > character
    # > quote (must be at start of line) -> ▌<i>quote</i>
    text = re.sub(r'^>\s+(.+)$', r'▌⟪QUOTE⟫\1⟪/QUOTE⟫', text, flags=re.MULTILINE)
    
    # Convert headlines: # Headline or ## Headline or ### Headline (must be at start of line)
    # Do this before escaping # character
    text = re.sub(r'^#{1,3}\s+(.+)$', r'⟪HEADLINE⟫\1⟪/HEADLINE⟫', text, flags=re.MULTILINE)
    
    # Convert bullet points: * item or - item (at start of line)
    # Do this before escaping * character
    text = re.sub(r'^(\s*)[*\-]\s+', r'\1• ', text, flags=re.MULTILINE)
    
    # Now escape HTML entities in the text
    result = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    
    # Replace headline placeholders with HTML tags
    result = result.replace("⟪HEADLINE⟫", "<b>").replace("⟪/HEADLINE⟫", "</b>")
    
    # Replace blockquote placeholders with HTML tags
    result = result.replace("⟪QUOTE⟫", "<i>").replace("⟪/QUOTE⟫", "</i>")
    
    # Convert code blocks (triple backticks) - must be done before inline code
    # Pattern: ```optional_lang\ncode\n```
    result = re.sub(r'```(?:\w+)?\n?(.*?)\n?```', r'<pre>\1</pre>', result, flags=re.DOTALL)
    
    # Convert inline code (single backticks)
    result = re.sub(r'`([^`]+)`', r'<code>\1</code>', result)
    
    # Convert bold: **text** or __text__
    result = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', result)
    result = re.sub(r'__(.+?)__', r'<b>\1</b>', result)
    
    # Convert italic: *text* or _text_ (but not inside words or at start of line as bullet)
    # This must be done AFTER bullets are converted
    result = re.sub(r'(?<!\w)\*(.+?)\*(?!\w)', r'<i>\1</i>', result)
    result = re.sub(r'(?<!\w)_(.+?)_(?!\w)', r'<i>\1</i>', result)
    
    # Convert links: [text](url)
    result = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'<a href="\2">\1</a>', result)

    for placeholder, table_html in table_html_by_placeholder.items():
        result = result.replace(placeholder, table_html)
    
    return result
