"""Shared utilities for Telegram integration."""
from __future__ import annotations

import re


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
    
    return result
