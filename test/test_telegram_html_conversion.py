"""Test markdown to HTML conversion for Telegram messages."""

from __future__ import annotations

import sys
from pathlib import Path

# Add repo root to path for imports
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

from app.integrations.telegram.worker import _markdown_to_html


def test_headlines():
    """Test headline conversion."""
    assert _markdown_to_html("# Headline") == "<b>Headline</b>"
    assert _markdown_to_html("## Subheadline") == "<b>Subheadline</b>"
    assert _markdown_to_html("### Third level") == "<b>Third level</b>"
    
    # Headlines in multi-line text
    text = """# Main Title
Some content here
## Section"""
    result = _markdown_to_html(text)
    assert "<b>Main Title</b>" in result
    assert "<b>Section</b>" in result
    print("[PASS] Headlines conversion")


def test_bullet_points():
    """Test bullet point conversion."""
    assert _markdown_to_html("* First item") == "• First item"
    assert _markdown_to_html("- Second item") == "• Second item"
    
    # Multi-line bullets
    text = """Points:
* First
* Second
* Third"""
    result = _markdown_to_html(text)
    assert result.count("•") == 3
    print("[PASS] Bullet points conversion")


def test_sub_bullets():
    """Test nested bullet points (indented)."""
    text = """* Main point
  * Sub point 1
  * Sub point 2
* Another main point"""
    result = _markdown_to_html(text)
    # Both main and sub bullets should have bullet characters
    assert result.count("•") == 4
    # Indentation should be preserved
    assert "  •" in result
    print("[PASS] Sub-bullet points conversion")


def test_blockquotes():
    """Test blockquote conversion."""
    assert _markdown_to_html("> This is a quote") == "▌<i>This is a quote</i>"
    
    # Multi-line quotes
    text = """> First quote
> Second line"""
    result = _markdown_to_html(text)
    assert result.count("▌") == 2
    assert result.count("<i>") == 2
    print("[PASS] Blockquotes conversion")


def test_bold_conversion():
    """Test bold markdown -> HTML conversion."""
    assert _markdown_to_html("**bold**") == "<b>bold</b>"
    assert _markdown_to_html("__bold__") == "<b>bold</b>"
    assert _markdown_to_html("text **bold** text") == "text <b>bold</b> text"
    print("[PASS] Bold conversion")


def test_italic_conversion():
    """Test italic markdown -> HTML conversion."""
    assert _markdown_to_html("*italic*") == "<i>italic</i>"
    assert _markdown_to_html("_italic_") == "<i>italic</i>"
    assert _markdown_to_html("text *italic* text") == "text <i>italic</i> text"
    print("[PASS] Italic conversion")


def test_inline_code_conversion():
    """Test inline code markdown -> HTML conversion."""
    assert _markdown_to_html("`code`") == "<code>code</code>"
    assert _markdown_to_html("text `code` text") == "text <code>code</code> text"
    assert _markdown_to_html("`function()`") == "<code>function()</code>"
    print("[PASS] Inline code conversion")


def test_code_block_conversion():
    """Test code block markdown -> HTML conversion."""
    result = _markdown_to_html("```\ncode\n```")
    assert "<pre>" in result and "</pre>" in result
    assert "code" in result
    
    result = _markdown_to_html("```python\ncode\n```")
    assert "<pre>" in result and "</pre>" in result
    print("[PASS] Code block conversion")


def test_link_conversion():
    """Test link markdown -> HTML conversion."""
    assert _markdown_to_html("[text](url)") == '<a href="url">text</a>'
    assert _markdown_to_html("[click here](https://example.com)") == '<a href="https://example.com">click here</a>'
    print("[PASS] Link conversion")


def test_html_entity_escaping():
    """Test HTML entities are properly escaped."""
    assert _markdown_to_html("<script>") == "&lt;script&gt;"
    assert _markdown_to_html("1 < 2 & 3 > 0") == "1 &lt; 2 &amp; 3 &gt; 0"
    assert _markdown_to_html("&test") == "&amp;test"
    print("[PASS] HTML entity escaping")


def test_mixed_formatting():
    """Test mixed markdown formatting."""
    text = "This is **bold** and *italic* with `code`"
    result = _markdown_to_html(text)
    assert "<b>bold</b>" in result
    assert "<i>italic</i>" in result
    assert "<code>code</code>" in result
    print("[PASS] Mixed formatting")


def test_underscores_in_text():
    """Test underscores in regular text don't get converted."""
    assert _markdown_to_html("file_name.txt") == "file_name.txt"
    assert _markdown_to_html("test_case_example") == "test_case_example"
    print("[PASS] Underscores in text preserved")


def test_urls_with_special_chars():
    """Test URLs with special characters are preserved."""
    url_text = "Visit https://example.com/path?arg=value&other=123"
    result = _markdown_to_html(url_text)
    # URLs should have & escaped to &amp;
    assert "&amp;" in result
    assert "https://example.com/path?arg=value" in result
    print("[PASS] URLs with special chars handled")


def test_list_items():
    """Test list items (bullets)."""
    text = """Points:
- First item
- Second item
- Third item"""
    result = _markdown_to_html(text)
    # Bullets are converted to Unicode bullet character •
    assert "• First item" in result
    assert result.count("•") == 3  # Three bullet points
    print("[PASS] List items handled")


def test_complex_llm_output():
    """Test realistic LLM output with multiple formatting types."""
    text = """Here's the answer:

**Important:** This is a *key point*.

Code example:
```python
def hello():
    print("hi")
```

More info:
- Use `function()` for this
- Check [documentation](https://example.com)
- Note: file_name.txt works!
"""
    result = _markdown_to_html(text)
    
    assert "<b>Important:</b>" in result
    assert "<i>key point</i>" in result
    assert "<pre>" in result
    assert "<code>function()</code>" in result
    assert '<a href="https://example.com">documentation</a>' in result
    assert "file_name.txt" in result
    
    print("[PASS] Complex LLM output")


def test_nested_formatting():
    """Test that nested formatting is handled (though may not be perfect)."""
    text = "**bold with *italic* inside**"
    result = _markdown_to_html(text)
    # Basic check - both tags should appear
    assert "<b>" in result or "<i>" in result
    print("[PASS] Nested formatting (basic)")


def test_empty_and_plain_text():
    """Test empty strings and plain text without markdown."""
    assert _markdown_to_html("") == ""
    assert _markdown_to_html("plain text") == "plain text"
    assert _markdown_to_html("just some words") == "just some words"
    print("[PASS] Empty and plain text")


def test_special_chars_outside_markdown():
    """Test special characters outside markdown contexts are preserved."""
    text = "Price: $100! Great deal (limited time)"
    result = _markdown_to_html(text)
    assert "Price:" in result
    assert "$100" in result
    assert "!" in result
    assert "(" in result
    print("[PASS] Special chars outside markdown preserved")


def main():
    """Run all tests."""
    print("Running Telegram markdown-to-HTML tests...\n")
    
    test_headlines()
    test_bullet_points()
    test_sub_bullets()
    test_blockquotes()
    test_bold_conversion()
    test_italic_conversion()
    test_inline_code_conversion()
    test_code_block_conversion()
    test_link_conversion()
    test_html_entity_escaping()
    test_mixed_formatting()
    test_underscores_in_text()
    test_urls_with_special_chars()
    test_list_items()
    test_complex_llm_output()
    test_nested_formatting()
    test_empty_and_plain_text()
    test_special_chars_outside_markdown()
    
    print("\n[SUCCESS] All markdown-to-HTML tests passed!")


if __name__ == "__main__":
    main()
