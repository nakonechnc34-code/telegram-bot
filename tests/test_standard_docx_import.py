"""DOCX import preserves original Word styling and sanitizes output."""
from io import BytesIO
from docx import Document
from docx.shared import RGBColor, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from utils.standard_docx import convert_standard_docx


def test_import_preserves_word_red_headings_and_alignment():
    document = Document()
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run('Правила мытья рук')
    run.bold = True
    run.font.color.rgb = RGBColor(255, 0, 0)
    run.font.size = Pt(18)
    buffer = BytesIO()
    document.save(buffer)
    html = convert_standard_docx(buffer.getvalue())
    assert 'color:#FF0000' in html
    assert 'font-weight:bold' in html
    assert 'font-size:18.0pt' in html or 'font-size:18pt' in html
    assert 'text-align:center' in html
    assert 'Правила мытья рук' in html


def test_import_escapes_document_text():
    document = Document()
    document.add_paragraph('<script>alert(1)</script>')
    buffer = BytesIO()
    document.save(buffer)
    html = convert_standard_docx(buffer.getvalue())
    assert '<script>' not in html
    assert '&lt;script&gt;' in html


def test_import_is_permission_checked_and_does_not_save():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / 'routes' / 'content.py').read_text(encoding='utf-8')
    segment = source.split("@routes.post('/api/admin/standard/import-docx')", 1)[1].split("@routes.post('/api/admin/standard/add')", 1)[0]
    assert 'get_admin_user(request)' in segment
    assert 'require_perm(admin, "standards_edit")' in segment
    assert 'convert_standard_docx(data)' in segment
    assert 'INSERT INTO standards' not in segment
