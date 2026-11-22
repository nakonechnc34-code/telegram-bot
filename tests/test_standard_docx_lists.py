"""Regression tests for Word numbered lists and legacy symbol bullets."""
from io import BytesIO
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from utils.standard_docx import convert_standard_docx


def test_word_numbered_items_are_not_bullets():
    doc = Document()
    numbering = doc.part.numbering_part.element
    decimal_ids = set()
    for abstract in numbering.findall(qn('w:abstractNum')):
        for lvl in abstract.findall(qn('w:lvl')):
            fmt = lvl.find(qn('w:numFmt'))
            if fmt is not None and fmt.get(qn('w:val')) == 'decimal':
                decimal_ids.add(abstract.get(qn('w:abstractNumId')))
    number_id = next(int(num.get(qn('w:numId'))) for num in numbering.findall(qn('w:num'))
                     if num.find(qn('w:abstractNumId')) is not None
                     and num.find(qn('w:abstractNumId')).get(qn('w:val')) in decimal_ids)
    for text in ('Смочите руки', 'Нанесите мыло'):
        p = doc.add_paragraph(text)
        pPr = p._p.get_or_add_pPr()
        numPr = OxmlElement('w:numPr')
        level = OxmlElement('w:ilvl'); level.set(qn('w:val'), '0')
        number = OxmlElement('w:numId'); number.set(qn('w:val'), str(number_id))
        numPr.append(level); numPr.append(number); pPr.append(numPr)
    buffer = BytesIO(); doc.save(buffer)
    html = convert_standard_docx(buffer.getvalue())
    assert '<ol' not in html
    assert '1. Смочите руки' in html
    assert '2. Нанесите мыло' in html
    assert '&#8226;' not in html


def test_private_use_bullet_is_readable():
    doc = Document()
    p = doc.add_paragraph()
    p.add_run('\uf0b7')
    p.add_run('  ')
    p.add_run('Перед началом').bold = True
    buffer = BytesIO(); doc.save(buffer)
    html = convert_standard_docx(buffer.getvalue())
    assert '• Перед началом' in html
    assert '&#xf0b7;' not in html
    assert '\uf0b7' not in html
    assert 'font-weight:bold' in html


def test_numbered_list_has_exact_six_sequential_labels():
    doc = Document()
    numbering = doc.part.numbering_part.element
    decimal_ids = {abstract.get(qn('w:abstractNumId')) for abstract in numbering.findall(qn('w:abstractNum'))
                   if any(fmt.get(qn('w:val')) == 'decimal' for fmt in abstract.findall('.//' + qn('w:numFmt')))}
    num_id = next(int(num.get(qn('w:numId'))) for num in numbering.findall(qn('w:num'))
                  if num.find(qn('w:abstractNumId')).get(qn('w:val')) in decimal_ids)
    for i in range(6):
        p = doc.add_paragraph('Шаг ' + str(i + 1))
        numPr = OxmlElement('w:numPr')
        level = OxmlElement('w:ilvl'); level.set(qn('w:val'), '0')
        number = OxmlElement('w:numId'); number.set(qn('w:val'), str(num_id))
        numPr.extend([level, number]); p._p.get_or_add_pPr().append(numPr)
    buf = BytesIO(); doc.save(buf)
    html = convert_standard_docx(buf.getvalue())
    for i in range(1, 7):
        assert f'{i}. Шаг {i}' in html
    assert '<ul' not in html and '<ol' not in html
