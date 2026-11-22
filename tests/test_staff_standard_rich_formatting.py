"""Regression coverage for staff standard rendering of sanitized Word formatting."""
from pathlib import Path

STAFF_HTML = Path(__file__).resolve().parents[1] / 'frontend' / 'index.html'


def test_staff_standard_sanitizer_preserves_allowed_word_styles():
    source = STAFF_HTML.read_text(encoding='utf-8')
    sanitizer = source.split('function sanitizeStandardHtml(html) {', 1)[1].split('let _toastTimer', 1)[0]
    for property_name in ('color', 'font-weight', 'font-size', 'text-align', 'padding-left', 'text-indent'):
        assert f"'{property_name}'" in sanitizer
    assert "node.style.getPropertyValue(property)" in sanitizer
    assert "el.style.setProperty(property, value)" in sanitizer
    assert "allowedStyles.has" not in sanitizer or "allowedStyles" in sanitizer
    assert "el.setAttribute('style', node.getAttribute('style'))" not in sanitizer
    assert "el.innerHTML = node.innerHTML" not in sanitizer


def test_staff_standards_detail_uses_rich_html_sanitizer():
    source = STAFF_HTML.read_text(encoding='utf-8')
    assert "sanitizeStandardHtml(s.body || '')" in source
