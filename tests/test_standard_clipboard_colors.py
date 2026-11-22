"""Regression guard: standards clipboard styling must be converted before save."""
from pathlib import Path


def test_standard_paste_resolves_word_css_colors():
    source = (Path(__file__).resolve().parents[1] / "frontend" / "admin.js").read_text(encoding="utf-8")
    assert "function preserveStandardClipboardColors(html)" in source
    assert "doc.querySelectorAll('style')" in source
    assert "el.style.color = colors.get(cls)" in source
    assert "cleanHTML(preserveStandardClipboardColors(html))" in source
    assert source.count("    bindStandardRichPaste();") == 2
