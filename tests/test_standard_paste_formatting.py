"""Standards retain safe pasted formatting without weakening global HTML sanitization."""
from utils.security import sanitize_html, sanitize_standard_html


def test_standards_preserve_document_styles():
    html = '<h2 style="color: red; text-align: center; font-size: 20px">Правила</h2><p style="line-height: 1.5; margin-bottom: 12px"><strong>Текст</strong></p>'
    result = sanitize_standard_html(html)
    for token in ('color: red', 'text-align: center', 'font-size: 20px', 'line-height: 1.5', 'margin-bottom: 12px', '<strong>Текст</strong>'):
        assert token in result


def test_standards_reject_scripts_event_handlers_and_unsafe_css():
    html = '<script>alert(1)</script><p onclick="alert(2)" style="color: red; position: fixed; background-image: url(https://evil.example/x)">Текст</p>'
    result = sanitize_standard_html(html)
    assert '<script' not in result
    assert 'onclick' not in result
    assert 'position:' not in result
    assert 'background-image' not in result
    assert 'color: red' in result


def test_general_sanitizer_still_strips_styles():
    assert 'style=' not in sanitize_html('<p style="color:red">Текст</p>')


def test_standard_endpoints_use_safe_style_sanitizer():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / 'routes' / 'content.py').read_text(encoding='utf-8')
    assert src.count('text = sanitize_standard_html((body.get("body") or "").strip())') == 2


def test_word_font_color_survives_standard_save():
    html = '<p><font color="#c00000"><b>Важный заголовок</b></font></p>'
    result = sanitize_standard_html(html)
    assert '<font color="#c00000">' in result
    assert '<b>Важный заголовок</b>' in result


def test_word_font_color_rejects_unsafe_attributes():
    html = '<font color="expression(alert(1))" onclick="alert(1)">Текст</font>'
    result = sanitize_standard_html(html)
    assert 'color=' not in result
    assert 'onclick' not in result
    assert '<font>Текст</font>' in result
