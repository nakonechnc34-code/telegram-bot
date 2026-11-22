"""Convert uploaded Word standards into safely styled HTML without clipboard loss."""
from html import escape
from io import BytesIO
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from utils.security import sanitize_standard_html


def _run_html(run):
    value = run.text
    if not value:
        return ''
    value = escape(value).replace('\\n', '<br>')
    styles = []
    if run.font.color and run.font.color.rgb:
        styles.append('color:#' + str(run.font.color.rgb))
    if run.font.size:
        styles.append('font-size:' + str(round(run.font.size.pt, 2)) + 'pt')
    if run.font.name:
        styles.append('font-family:' + escape(run.font.name, quote=True))
    if run.bold:
        styles.append('font-weight:bold')
    if run.italic:
        styles.append('font-style:italic')
    if run.underline:
        styles.append('text-decoration:underline')
    if styles:
        return '<span style="' + ';'.join(styles) + '">' + value + '</span>'
    return value


def convert_standard_docx(data):
    document = Document(BytesIO(data))
    output = []
    for para in document.paragraphs:
        content = ''.join(_run_html(run) for run in para.runs)
        if not content and not para.text.strip():
            output.append('<p>&nbsp;</p>')
            continue
        styles = []
        alignment = {
            WD_ALIGN_PARAGRAPH.CENTER: 'center',
            WD_ALIGN_PARAGRAPH.RIGHT: 'right',
            WD_ALIGN_PARAGRAPH.JUSTIFY: 'justify',
        }.get(para.alignment)
        if alignment:
            styles.append('text-align:' + alignment)
        if para.paragraph_format.space_before:
            styles.append('margin-top:' + str(round(para.paragraph_format.space_before.pt, 2)) + 'pt')
        if para.paragraph_format.space_after:
            styles.append('margin-bottom:' + str(round(para.paragraph_format.space_after.pt, 2)) + 'pt')
        is_list = para._p.pPr is not None and para._p.pPr.find(qn('w:numPr')) is not None
        if is_list:
            content = '&#8226; ' + content
        attr = ' style="' + ';'.join(styles) + '"' if styles else ''
        output.append('<p' + attr + '>' + content + '</p>')
    return sanitize_standard_html(''.join(output))
