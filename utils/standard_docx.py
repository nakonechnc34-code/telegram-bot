"""Convert Word standards to sanitized HTML with colors and true list numbering."""
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
    # Symbol-font bullets are stored as private-use U+F0B7 in some Word files.
    value = value.replace('\uf0b7', '')
    value = escape(value).replace('\n', '<br>')
    styles = []
    if run.font.color and run.font.color.rgb:
        styles.append('color:#' + str(run.font.color.rgb))
    if run.font.size:
        styles.append('font-size:' + str(round(run.font.size.pt, 2)) + 'pt')
    if run.font.name and not (run.text.startswith('\uf0b7')):
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


def _list_kind(para, numbering):
    props = para._p.pPr
    if props is None or props.numPr is None or props.numPr.numId is None:
        return None, None
    num_id = props.numPr.numId.val
    for num in numbering.findall(qn('w:num')):
        if int(num.get(qn('w:numId'))) != num_id:
            continue
        abstract_id = num.find(qn('w:abstractNumId'))
        if abstract_id is None:
            break
        for abstract in numbering.findall(qn('w:abstractNum')):
            if abstract.get(qn('w:abstractNumId')) != abstract_id.get(qn('w:val')):
                continue
            level = props.numPr.ilvl.val if props.numPr.ilvl is not None else 0
            for lvl in abstract.findall(qn('w:lvl')):
                if int(lvl.get(qn('w:ilvl'))) == level:
                    fmt = lvl.find(qn('w:numFmt'))
                    return ('ul' if fmt is not None and fmt.get(qn('w:val')) == 'bullet' else 'ol'), num_id
    return 'ol', num_id


def convert_standard_docx(data):
    document = Document(BytesIO(data))
    numbering = document.part.numbering_part.element
    output = []
    list_counters = {}
    for para in document.paragraphs:
        kind, list_id = _list_kind(para, numbering)
        content = ''.join(_run_html(run) for run in para.runs)
        if kind:
            # Use explicit Word list labels. The admin editor resets native
            # ol/ul markers, so browser-generated bullets/numbers are unreliable.
            if kind == 'ol':
                list_counters[list_id] = list_counters.get(list_id, 0) + 1
                marker = str(list_counters[list_id]) + '.&nbsp;'
            else:
                marker = '•&nbsp;'
            output.append('<p style="margin-top:0;margin-bottom:0;padding-left:24px;text-indent:-24px">' + marker + content + '</p>')
            continue
        if not para.text.strip():
            output.append('<p>&nbsp;</p>')
            continue
        # Word documents often use trailing spaces to position text; do not
        # reproduce those as visible horizontal indentation in the editor.
        content = content.rstrip()
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
        # Word uses the private-use glyph for manual bullets. Normalize it to
        # a real bullet, keeping the following bold text and other formatting.
        if para.text.startswith('\uf0b7'):
            # Symbol-font bullet U+F0B7 is not a printable glyph in browsers.
            content = '•&nbsp;' + content.lstrip()
            styles.append('padding-left:24px')
            styles.append('text-indent:-16px')
        attr = ' style="' + ';'.join(styles) + '"' if styles else ''
        output.append('<p' + attr + '>' + content + '</p>')
    return sanitize_standard_html(''.join(output))
