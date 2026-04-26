"""Shared utilities for Telegram integration."""
from __future__ import annotations

import html
import io
import re
from typing import Literal, TypedDict

_TELEGRAM_TABLE_PLACEHOLDER_PREFIX = "KRILLTELEGRAMTABLE"
_TELEGRAM_TABLE_IMAGE_MAX_CELL_WIDTH = 380
_TELEGRAM_TABLE_IMAGE_MIN_CELL_WIDTH = 80
_TELEGRAM_TABLE_IMAGE_PADDING_X = 14
_TELEGRAM_TABLE_IMAGE_PADDING_Y = 10
_TELEGRAM_TABLE_IMAGE_FONT_SIZE = 18
_TELEGRAM_TABLE_IMAGE_BORDER = 1


class TelegramMessagePart(TypedDict, total=False):
    type: Literal["text", "image"]
    text: str
    image_bytes: bytes
    filename: str


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


def _render_markdown_table(header: list[str], separator: list[str], rows: list[list[str]]) -> str:
    column_count = len(header)
    normalized_rows = [_normalize_table_row(row, column_count) for row in rows]
    all_rows = [header, *normalized_rows]
    widths = [
        max(len(row[index]) for row in all_rows)
        for index in range(column_count)
    ]
    alignments = _table_alignments(separator)

    rendered_rows = [
        " | ".join(
            _format_table_cell(cell, widths[index], alignments[index])
            for index, cell in enumerate(header)
        ),
        " | ".join("-" * widths[index] for index in range(column_count)),
    ]
    for row in normalized_rows:
        rendered_rows.append(
            " | ".join(
                _format_table_cell(cell, widths[index], alignments[index])
                for index, cell in enumerate(row)
            )
        )
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


def _plain_table_cell(value: str) -> str:
    result = value.strip()
    result = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", result)
    result = re.sub(r"`([^`]+)`", r"\1", result)
    result = re.sub(r"\*\*(.+?)\*\*", r"\1", result)
    result = re.sub(r"__(.+?)__", r"\1", result)
    result = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"\1", result)
    result = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", result)
    return html.unescape(result)


def _load_table_font(size: int, *, bold: bool = False):
    from PIL import ImageFont  # pylint: disable=import-outside-toplevel

    font_names = (
        ("C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/segoeui.ttf")
        if bold
        else ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf")
    )
    candidates = [
        *font_names,
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/local/share/fonts/DejaVuSans-Bold.ttf" if bold else "/usr/local/share/fonts/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text_width(draw, text: str, font) -> int:
    left, _top, right, _bottom = draw.textbbox((0, 0), text, font=font)
    return max(0, right - left)


def _text_height(draw, text: str, font) -> int:
    _left, top, _right, bottom = draw.textbbox((0, 0), text or "Ag", font=font)
    return max(1, bottom - top)


def _wrap_table_cell(draw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if _text_width(draw, candidate, font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        while _text_width(draw, current, font) > max_width and len(current) > 1:
            split_at = len(current)
            while split_at > 1 and _text_width(draw, current[:split_at], font) > max_width:
                split_at -= 1
            lines.append(current[:split_at])
            current = current[split_at:]
    if current:
        lines.append(current)
    return lines or [""]


def render_markdown_table_image(header: list[str], separator: list[str], rows: list[list[str]]) -> bytes:
    from PIL import Image, ImageDraw  # pylint: disable=import-outside-toplevel

    header_font = _load_table_font(_TELEGRAM_TABLE_IMAGE_FONT_SIZE, bold=True)
    body_font = _load_table_font(_TELEGRAM_TABLE_IMAGE_FONT_SIZE)
    measure_image = Image.new("RGB", (1, 1), "white")
    measure_draw = ImageDraw.Draw(measure_image)

    column_count = len(header)
    normalized_header = [_plain_table_cell(cell) for cell in _normalize_table_row(header, column_count)]
    normalized_rows = [
        [_plain_table_cell(cell) for cell in _normalize_table_row(row, column_count)]
        for row in rows
    ]
    alignments = _table_alignments(separator)
    column_widths: list[int] = []
    for index in range(column_count):
        values = [normalized_header[index], *[row[index] for row in normalized_rows]]
        width = max(_text_width(measure_draw, value, body_font) for value in values)
        width = max(_TELEGRAM_TABLE_IMAGE_MIN_CELL_WIDTH, min(width, _TELEGRAM_TABLE_IMAGE_MAX_CELL_WIDTH))
        column_widths.append(width)

    wrapped_header = [
        _wrap_table_cell(measure_draw, normalized_header[index], header_font, column_widths[index])
        for index in range(column_count)
    ]
    wrapped_rows = [
        [
            _wrap_table_cell(measure_draw, row[index], body_font, column_widths[index])
            for index in range(column_count)
        ]
        for row in normalized_rows
    ]
    body_line_height = _text_height(measure_draw, "Ag", body_font) + 5
    header_line_height = _text_height(measure_draw, "Ag", header_font) + 5
    row_heights = [
        max(len(lines) for lines in wrapped_header) * header_line_height + (_TELEGRAM_TABLE_IMAGE_PADDING_Y * 2),
        *[
            max(len(lines) for lines in wrapped_row) * body_line_height + (_TELEGRAM_TABLE_IMAGE_PADDING_Y * 2)
            for wrapped_row in wrapped_rows
        ],
    ]

    table_width = (
        sum(column_widths)
        + (column_count * _TELEGRAM_TABLE_IMAGE_PADDING_X * 2)
        + ((column_count + 1) * _TELEGRAM_TABLE_IMAGE_BORDER)
    )
    table_height = sum(row_heights) + ((len(row_heights) + 1) * _TELEGRAM_TABLE_IMAGE_BORDER)
    image = Image.new("RGB", (table_width, table_height), "#ffffff")
    draw = ImageDraw.Draw(image)

    grid_color = "#d4d7dd"
    header_background = "#f1f3f6"
    text_color = "#111827"
    y = 0
    all_wrapped_rows = [wrapped_header, *wrapped_rows]
    for row_index, wrapped_row in enumerate(all_wrapped_rows):
        row_height = row_heights[row_index]
        if row_index == 0:
            draw.rectangle((0, y, table_width, y + row_height), fill=header_background)
        x = 0
        for column_index, lines in enumerate(wrapped_row):
            cell_width = column_widths[column_index] + (_TELEGRAM_TABLE_IMAGE_PADDING_X * 2)
            draw.rectangle((x, y, x + cell_width, y + row_height), outline=grid_color, width=1)
            font = header_font if row_index == 0 else body_font
            line_height = header_line_height if row_index == 0 else body_line_height
            text_y = y + _TELEGRAM_TABLE_IMAGE_PADDING_Y
            for line in lines:
                line_width = _text_width(draw, line, font)
                if alignments[column_index] == "right":
                    text_x = x + cell_width - _TELEGRAM_TABLE_IMAGE_PADDING_X - line_width
                elif alignments[column_index] == "center":
                    text_x = x + ((cell_width - line_width) // 2)
                else:
                    text_x = x + _TELEGRAM_TABLE_IMAGE_PADDING_X
                draw.text((text_x, text_y), line, fill=text_color, font=font)
                text_y += line_height
            x += cell_width
        y += row_height

    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def render_telegram_message_parts(text: str) -> list[TelegramMessagePart]:
    lines = text.splitlines(keepends=True)
    parts: list[TelegramMessagePart] = []
    pending_text: list[str] = []
    index = 0
    table_index = 1
    in_code_block = False

    def flush_text() -> None:
        raw_text = "".join(pending_text).strip()
        pending_text.clear()
        if not raw_text:
            return
        for chunk in chunk_telegram_text(raw_text):
            parts.append({"type": "text", "text": markdown_to_html(chunk)})

    while index < len(lines):
        line = lines[index]
        if line.lstrip().startswith("```"):
            in_code_block = not in_code_block
            pending_text.append(line)
            index += 1
            continue

        parsed_table = None if in_code_block else _parse_markdown_table_at(lines, index)
        if parsed_table is None:
            pending_text.append(line)
            index += 1
            continue

        body_index, header, separator, rows, raw_table = parsed_table
        flush_text()
        try:
            parts.append(
                {
                    "type": "image",
                    "image_bytes": render_markdown_table_image(header, separator, rows),
                    "filename": f"telegram-table-{table_index}.png",
                }
            )
            table_index += 1
        except Exception:
            for chunk in chunk_telegram_text(raw_table.strip()):
                parts.append({"type": "text", "text": markdown_to_html(chunk)})
        index = body_index

    flush_text()
    return parts


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
